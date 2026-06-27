"""Cost attribution — the headline module.

Counts tokens per tool call, applies a pricing model, resolves the caller to a cost center, and
emits a structured :class:`CostRecord` to a pluggable sink. Drop it into a server and you can
answer "which business unit generated which spend" from the resulting JSONL (see the
``mcp-harness daily-rollup`` CLI).

Scope note (per the design's open question): v0.1 attributes **tool-side** tokens — the arguments
the tool received and the result it produced. Attribution of downstream *model* tokens generated
from a tool's output depends on the agent harness and is left to a future estimation hook.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.context import CallStatus, ToolCallContext
from ..core.middleware import RecordingMiddleware
from ..core.principal import Principal
from .sinks import Sink, resolve_sink

# A cost-center resolver maps a principal to an attribution bucket.
CostCenterResolver = Callable[[Principal], str]


class TokenCounter:
    """Counts tokens for arbitrary tool inputs/outputs.

    Uses ``tiktoken`` when installed and a model/encoding is configured; otherwise falls back to a
    fast ``len(text) / divisor`` heuristic. The heuristic is approximate by design — good enough
    for relative attribution, and the exact path is one ``pip install 'mcp-harness[tokens]'`` away.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        encoding: str | None = None,
        chars_per_token: float = 4.0,
    ) -> None:
        self.chars_per_token = chars_per_token
        self._encoder: Any | None = None
        if model or encoding:
            self._encoder = self._load_encoder(model, encoding)

    @staticmethod
    def _load_encoder(model: str | None, encoding: str | None) -> Any | None:
        try:
            import tiktoken  # type: ignore
        except ImportError:
            return None
        try:
            if encoding:
                return tiktoken.get_encoding(encoding)
            return tiktoken.encoding_for_model(model)  # type: ignore[arg-type]
        except Exception:
            try:
                return tiktoken.get_encoding("cl100k_base")
            except Exception:
                return None

    def count_text(self, text: str) -> int:
        if self._encoder is not None:
            return len(self._encoder.encode(text))
        if not text:
            return 0
        return max(1, round(len(text) / self.chars_per_token))

    def count(self, obj: Any) -> int:
        """Count tokens for any JSON-serializable object (dicts, lists, scalars)."""
        if obj is None:
            return 0
        if isinstance(obj, str):
            text = obj
        else:
            try:
                text = json.dumps(obj, default=str, separators=(",", ":"))
            except (TypeError, ValueError):
                text = str(obj)
        return self.count_text(text)


@dataclass(frozen=True)
class ModelPrice:
    """USD price per 1,000 input and output tokens."""

    input_per_1k: float
    output_per_1k: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1000.0 * self.input_per_1k
            + output_tokens / 1000.0 * self.output_per_1k
        )


class PricingModel:
    """Per-model USD pricing.

    The default rates are **illustrative** (loosely a mid-tier frontier model) so the example
    servers show non-zero spend. Configure real rates for production attribution.
    """

    #: Illustrative placeholder — override for production.
    DEFAULT_PRICE = ModelPrice(input_per_1k=0.0025, output_per_1k=0.01)

    def __init__(
        self,
        prices: Mapping[str, ModelPrice] | None = None,
        *,
        default: ModelPrice | None = None,
    ) -> None:
        self.prices = dict(prices or {})
        self.default = default or self.DEFAULT_PRICE

    @classmethod
    def flat(cls, input_per_1k: float, output_per_1k: float) -> PricingModel:
        return cls(default=ModelPrice(input_per_1k, output_per_1k))

    def price_for(self, model: str) -> ModelPrice:
        return self.prices.get(model, self.default)

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        return self.price_for(model).cost(input_tokens, output_tokens)


@dataclass
class CostRecord:
    """One attributed tool call. Serialized to the cost sink (one JSON object per call)."""

    timestamp: str
    trace_id: str
    tool: str
    principal_id: str
    cost_center: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    status: str
    duration_ms: float
    team: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_cost_center_resolver(
    spec: CostCenterResolver | Mapping[str, str] | str | None,
) -> CostCenterResolver:
    """Build a resolver from a callable, a ``{team: cost_center}`` mapping, a YAML path, or None."""
    if spec is None:
        return _default_cost_center
    if callable(spec):
        return spec
    if isinstance(spec, Mapping):
        mapping = dict(spec)
        return lambda p: mapping.get(p.team or "", mapping.get("*", _default_cost_center(p)))
    if isinstance(spec, str):
        import yaml

        with open(spec, encoding="utf-8") as fh:
            mapping = yaml.safe_load(fh) or {}
        return lambda p: mapping.get(p.team or "", mapping.get("*", _default_cost_center(p)))
    raise TypeError(f"Cannot interpret {spec!r} as a cost-center resolver")


def _default_cost_center(principal: Principal) -> str:
    cc = principal.claims.get("cost_center")
    if cc:
        return str(cc)
    if principal.team:
        return principal.team
    return "unattributed"


class CostTracking(RecordingMiddleware):
    """Middleware that attributes the cost of each tool call to a cost center.

    Args:
        sink: Where to emit :class:`CostRecord`\\ s. A :class:`Sink`, a callable taking the record
            dict, a ``"jsonl://path"`` URI, or ``None`` (stdout).
        pricing: A :class:`PricingModel`. Defaults to illustrative rates.
        token_counter: A :class:`TokenCounter`. Defaults to the heuristic counter.
        cost_center_resolver: Callable / ``{team: cc}`` mapping / YAML path / ``None``.
        model: Model name used for pricing and recorded on each row.
        count_arguments / count_result: Toggle input/output token counting.
    """

    name = "cost_tracking"

    def __init__(
        self,
        *,
        sink: Sink | Callable[[dict[str, Any]], Any] | str | None = None,
        pricing: PricingModel | None = None,
        token_counter: TokenCounter | None = None,
        cost_center_resolver: CostCenterResolver | Mapping[str, str] | str | None = None,
        model: str = "default",
        count_arguments: bool = True,
        count_result: bool = True,
    ) -> None:
        super().__init__()
        self.sink = resolve_sink(sink)
        self.pricing = pricing or PricingModel()
        self.counter = token_counter or TokenCounter()
        self.resolve_cost_center = make_cost_center_resolver(cost_center_resolver)
        self.model = model
        self.count_arguments = count_arguments
        self.count_result = count_result

    async def on_start(self, ctx: ToolCallContext) -> None:
        if self.count_arguments:
            ctx.input_tokens = self.counter.count(ctx.arguments)

    async def on_finish(self, ctx: ToolCallContext) -> None:
        if self.count_result and ctx.status is CallStatus.OK:
            ctx.output_tokens = self.counter.count(ctx.result)
        ctx.cost_usd = self.pricing.cost(self.model, ctx.input_tokens, ctx.output_tokens)
        ctx.cost_center = self.resolve_cost_center(ctx.principal)

        record = CostRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=ctx.trace_id,
            tool=ctx.tool,
            principal_id=ctx.principal.id,
            team=ctx.principal.team,
            cost_center=ctx.cost_center,
            model=self.model,
            input_tokens=ctx.input_tokens,
            output_tokens=ctx.output_tokens,
            total_tokens=ctx.total_tokens,
            cost_usd=round(ctx.cost_usd, 6),
            status=ctx.status.value,
            duration_ms=round(ctx.duration_ms, 3),
        )
        await self.sink.emit(record)


__all__ = [
    "CostTracking",
    "CostRecord",
    "PricingModel",
    "ModelPrice",
    "TokenCounter",
    "make_cost_center_resolver",
]
