"""Cost attribution: token counting, pricing, cost-center resolution, record emission."""

from __future__ import annotations

from mcp_harness import Harness
from mcp_harness.governance import CostTracking, PricingModel, TokenCounter
from mcp_harness.governance.cost_tracking import ModelPrice, make_cost_center_resolver
from mcp_harness.testing import HarnessTestClient, MockPrincipal


def test_token_counter_heuristic():
    counter = TokenCounter(chars_per_token=4.0)
    assert counter.count("") == 0
    assert counter.count_text("abcdefgh") == 2  # 8 chars / 4
    assert counter.count({"a": 1}) > 0


def test_pricing_model_cost():
    price = ModelPrice(input_per_1k=2.0, output_per_1k=4.0)
    assert price.cost(1000, 500) == 2.0 + 2.0
    model = PricingModel.flat(input_per_1k=1.0, output_per_1k=1.0)
    assert model.cost("default", 1000, 1000) == 2.0


def test_cost_center_resolver_variants():
    p = MockPrincipal("u", team="finance")
    assert make_cost_center_resolver(None)(p) == "finance"
    assert make_cost_center_resolver({"finance": "CC-100"})(p) == "CC-100"
    assert make_cost_center_resolver(lambda pr: "custom")(p) == "custom"


async def test_cost_record_emitted_with_attribution(list_sink):
    sink = list_sink
    h = Harness(
        name="t",
        middleware=[
            CostTracking(
                sink=sink,
                pricing=PricingModel.flat(input_per_1k=1.0, output_per_1k=1.0),
                cost_center_resolver={"finance": "CC-FINANCE"},
            )
        ],
    )

    @h.tool()
    async def search(q: str) -> dict:
        return {"hits": [1, 2, 3]}

    client = HarnessTestClient(h, principal=MockPrincipal("svc-a", team="finance"))
    await client.call("search", {"q": "acme"})

    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec["tool"] == "search"
    assert rec["principal_id"] == "svc-a"
    assert rec["team"] == "finance"
    assert rec["cost_center"] == "CC-FINANCE"
    assert rec["input_tokens"] > 0
    assert rec["output_tokens"] > 0
    assert rec["cost_usd"] > 0
    assert rec["status"] == "ok"


async def test_cost_record_on_error_has_no_output_tokens(list_sink):
    sink = list_sink
    h = Harness(name="t", middleware=[CostTracking(sink=sink)])

    @h.tool()
    async def boom(q: str) -> dict:
        raise RuntimeError("fail")

    client = HarnessTestClient(h, principal=MockPrincipal("svc-a", team="eng"))
    try:
        await client.call("boom", {"q": "x"})
    except RuntimeError:
        pass

    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec["status"] == "error"
    assert rec["output_tokens"] == 0
    assert rec["input_tokens"] > 0
