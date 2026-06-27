"""Declarative allow/deny policy for which principals may call which tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ..core.context import NextCall, ToolCallContext
from ..core.middleware import BaseMiddleware
from ..core.principal import Principal
from ..errors import PolicyDenied


@dataclass
class Rule:
    """A single access rule.

    Empty ``principals``/``teams`` match everyone; empty ``tools`` matches every tool. ``args``
    maps an argument name to the set of permitted values (allow-list only).
    """

    principals: set[str] = field(default_factory=set)
    teams: set[str] = field(default_factory=set)
    tools: list[str] = field(default_factory=list)
    args: dict[str, set[Any]] = field(default_factory=dict)

    def subject_matches(self, principal: Principal) -> bool:
        if self.principals and principal.id not in self.principals and "*" not in self.principals:
            return False
        if self.teams and (principal.team not in self.teams) and "*" not in self.teams:
            return False
        return True

    def tool_matches(self, tool: str) -> bool:
        if not self.tools:
            return True
        return any(fnmatch(tool, pattern) for pattern in self.tools)

    def check_args(self, arguments: Mapping[str, Any]) -> tuple[bool, str | None]:
        for arg, allowed in self.args.items():
            if arguments.get(arg) not in allowed:
                return False, arg
        return True, None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Rule:
        def as_set(value: Any) -> set[str]:
            if value is None:
                return set()
            if isinstance(value, str):
                return {value}
            return set(value)

        args_raw = data.get("args", {}) or {}
        args = {
            k: set(v if isinstance(v, (list, tuple, set)) else [v])
            for k, v in args_raw.items()
        }
        return cls(
            principals=as_set(data.get("principals")),
            teams=as_set(data.get("teams")),
            tools=list(data.get("tools", []) or []),
            args=args,
        )


def _load_rules(rules: Sequence[Mapping[str, Any] | Rule]) -> list[Rule]:
    return [r if isinstance(r, Rule) else Rule.from_dict(r) for r in rules]


class AllowList(BaseMiddleware):
    """Permit a call only if some rule grants the principal access to the tool.

    Args:
        rules: Sequence of :class:`Rule` or rule dicts.
        default_allow: If no rule matches, allow the call (default: deny).
    """

    name = "allow_list"

    def __init__(
        self,
        rules: Sequence[Mapping[str, Any] | Rule],
        *,
        default_allow: bool = False,
    ) -> None:
        super().__init__()
        self.rules = _load_rules(rules)
        self.default_allow = default_allow

    @classmethod
    def from_yaml(cls, path: str | Path) -> AllowList:
        """Load from YAML: ``{default_allow: bool, rules: [...]}`` or a bare list of rules."""
        import yaml

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if isinstance(data, list):
            return cls(data)
        return cls(data.get("rules", []), default_allow=bool(data.get("default_allow", False)))

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall) -> Any:
        subject_tool_matched = False
        for rule in self.rules:
            if rule.subject_matches(ctx.principal) and rule.tool_matches(ctx.tool):
                subject_tool_matched = True
                ok, _bad = rule.check_args(ctx.arguments)
                if ok:
                    return await call_next(ctx)
        if self.default_allow:
            return await call_next(ctx)
        reason = (
            "argument constraints not satisfied"
            if subject_tool_matched
            else f"principal '{ctx.principal.id}' is not permitted"
        )
        raise PolicyDenied(ctx.tool, reason)


class DenyList(BaseMiddleware):
    """Reject a call if any rule matches the principal and tool.

    Argument constraints are an allow-list feature; ``DenyList`` matches on principal/team + tool.
    """

    name = "deny_list"

    def __init__(self, rules: Sequence[Mapping[str, Any] | Rule]) -> None:
        super().__init__()
        self.rules = _load_rules(rules)

    @classmethod
    def from_yaml(cls, path: str | Path) -> DenyList:
        import yaml

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        rules = data if isinstance(data, list) else data.get("rules", [])
        return cls(rules)

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall) -> Any:
        for rule in self.rules:
            if rule.subject_matches(ctx.principal) and rule.tool_matches(ctx.tool):
                raise PolicyDenied(ctx.tool, f"principal '{ctx.principal.id}' is blocked")
        return await call_next(ctx)


__all__ = ["AllowList", "DenyList", "Rule"]
