"""Basic PII redaction for tool inputs and outputs.

Ships with patterns for the most common identifiers (email, US SSN, phone, credit-card-like
numbers). This is a *starting point*, not a compliance product — add your own patterns via
``extra_patterns`` and review against your data classification before relying on it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..core.context import NextCall, ToolCallContext
from ..core.middleware import BaseMiddleware

#: name -> (compiled pattern, replacement token)
DEFAULT_PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    "email": (
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
        "[REDACTED_EMAIL]",
    ),
    "ssn": (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    "phone": (
        re.compile(r"\b(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b"),
        "[REDACTED_PHONE]",
    ),
    "credit_card": (re.compile(r"\b(?:\d[ \-]?){13,16}\b"), "[REDACTED_CC]"),
}


class PIIRedactor:
    """Recursively redacts PII in strings, dicts, and lists."""

    def __init__(
        self,
        *,
        patterns: Mapping[str, tuple[re.Pattern[str], str]] | None = None,
        extra_patterns: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        self.patterns: dict[str, tuple[re.Pattern[str], str]] = dict(
            patterns if patterns is not None else DEFAULT_PATTERNS
        )
        for name, (regex, replacement) in (extra_patterns or {}).items():
            self.patterns[name] = (re.compile(regex), replacement)

    def redact_text(self, text: str) -> str:
        for regex, replacement in self.patterns.values():
            text = regex.sub(replacement, text)
        return text

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            redacted = [self.redact(v) for v in value]
            return type(value)(redacted) if isinstance(value, tuple) else redacted
        return value


class PIIRedaction(BaseMiddleware):
    """Middleware that redacts PII from tool outputs (and optionally inputs).

    Args:
        redactor: A :class:`PIIRedactor`; defaults to the built-in patterns.
        redact_result: Redact the value returned to the client (default ``True``).
        redact_arguments: Redact arguments *before* the tool runs. Off by default because it
            changes what the tool receives — enable only when the tool tolerates redacted input.
    """

    name = "pii_redaction"

    def __init__(
        self,
        *,
        redactor: PIIRedactor | None = None,
        redact_result: bool = True,
        redact_arguments: bool = False,
    ) -> None:
        super().__init__()
        self.redactor = redactor or PIIRedactor()
        self.redact_result = redact_result
        self.redact_arguments = redact_arguments

    async def __call__(self, ctx: ToolCallContext, call_next: NextCall) -> Any:
        if self.redact_arguments:
            ctx.arguments = self.redactor.redact(ctx.arguments)
        result = await call_next(ctx)
        if self.redact_result:
            result = self.redactor.redact(result)
            ctx.result = result
        return result


__all__ = ["PIIRedactor", "PIIRedaction", "DEFAULT_PATTERNS"]
