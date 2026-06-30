"""Allow/deny lists and PII redaction."""

from __future__ import annotations

import pytest

from mcp_harness import Harness, PolicyDenied
from mcp_harness.policy import AllowList, DenyList, PIIRedaction, PIIRedactor, Rule
from mcp_harness.testing import HarnessTestClient, MockPrincipal


def _build(*middleware):
    h = Harness(name="t", middleware=list(middleware))

    @h.tool()
    async def search_customer(customer_id: str) -> dict:
        return {"id": customer_id}

    @h.tool()
    async def issue_refund(customer_id: str, region: str = "us") -> dict:
        return {"ok": True, "region": region}

    return h


async def test_allow_list_grants_matching_team():
    h = _build(AllowList([Rule(teams={"finance"}, tools=["search_customer"])]))
    client = HarnessTestClient(h, principal=MockPrincipal("svc-a", team="finance"))
    assert (await client.call("search_customer", {"customer_id": "c1"}))["id"] == "c1"


async def test_allow_list_denies_unlisted_principal():
    h = _build(AllowList([Rule(teams={"finance"}, tools=["search_customer"])]))
    client = HarnessTestClient(h, principal=MockPrincipal("svc-b", team="platform"))
    with pytest.raises(PolicyDenied):
        await client.call("search_customer", {"customer_id": "c1"})


async def test_allow_list_argument_constraint():
    h = _build(
        AllowList([Rule(principals={"svc-a"}, tools=["issue_refund"], args={"region": {"us"}})])
    )
    client = HarnessTestClient(h, principal=MockPrincipal("svc-a"))
    assert (await client.call("issue_refund", {"customer_id": "c1", "region": "us"}))["ok"]
    with pytest.raises(PolicyDenied, match="argument"):
        await client.call("issue_refund", {"customer_id": "c1", "region": "eu"})


async def test_allow_list_glob_tools():
    h = _build(AllowList([Rule(teams={"platform"}, tools=["search_*"])]))
    client = HarnessTestClient(h, principal=MockPrincipal("svc-a", team="platform"))
    assert await client.call("search_customer", {"customer_id": "c1"})


async def test_deny_list_blocks_matching():
    h = _build(DenyList([Rule(principals={"svc-bad"})]))
    bad = HarnessTestClient(h, principal=MockPrincipal("svc-bad"))
    good = HarnessTestClient(h, principal=MockPrincipal("svc-ok"))
    with pytest.raises(PolicyDenied):
        await bad.call("search_customer", {"customer_id": "c1"})
    assert await good.call("search_customer", {"customer_id": "c1"})


async def test_allow_list_from_yaml(tmp_path):
    policy = tmp_path / "p.yaml"
    policy.write_text(
        "default_allow: false\n"
        "rules:\n"
        "  - teams: [finance]\n"
        "    tools: [search_customer]\n",
        encoding="utf-8",
    )
    h = _build(AllowList.from_yaml(policy))
    client = HarnessTestClient(h, principal=MockPrincipal("svc-a", team="finance"))
    assert await client.call("search_customer", {"customer_id": "c1"})


async def test_deny_list_from_yaml(tmp_path):
    policy = tmp_path / "p.yaml"
    policy.write_text(
        "- principals: [svc-bad]\n",
        encoding="utf-8",
    )
    h = _build(DenyList.from_yaml(policy))
    bad = HarnessTestClient(h, principal=MockPrincipal("svc-bad"))
    good = HarnessTestClient(h, principal=MockPrincipal("svc-ok"))
    with pytest.raises(PolicyDenied):
        await bad.call("search_customer", {"customer_id": "c1"})
    assert await good.call("search_customer", {"customer_id": "c1"})


def test_pii_redactor_patterns():
    r = PIIRedactor()
    assert r.redact_text("reach me at a@b.com") == "reach me at [REDACTED_EMAIL]"
    assert "[REDACTED_SSN]" in r.redact_text("ssn 123-45-6789")
    nested = r.redact({"note": "call 415-555-1234", "ok": [1, "x@y.io"]})
    assert "[REDACTED_PHONE]" in nested["note"]
    assert nested["ok"][1] == "[REDACTED_EMAIL]"


def test_pii_redactor_extra_patterns():
    r = PIIRedactor(extra_patterns={"employee_id": (r"EMP-\d{4}", "[REDACTED_EMPLOYEE_ID]")})
    assert r.redact_text("badge EMP-1234") == "badge [REDACTED_EMPLOYEE_ID]"
    assert "[REDACTED_EMAIL]" in r.redact_text("a@b.com")


async def test_pii_redaction_middleware_redacts_result():
    h = Harness(name="t", middleware=[PIIRedaction()])

    @h.tool()
    async def leak() -> dict:
        return {"email": "secret@corp.com"}

    client = HarnessTestClient(h, principal=MockPrincipal())
    assert (await client.call("leak"))["email"] == "[REDACTED_EMAIL]"


async def test_pii_redaction_middleware_redacts_arguments():
    h = Harness(name="t", middleware=[PIIRedaction(redact_arguments=True, redact_result=False)])

    @h.tool()
    async def echo(note: str) -> dict:
        return {"note": note}

    client = HarnessTestClient(h, principal=MockPrincipal())
    result = await client.call("echo", {"note": "contact secret@corp.com"})
    assert result["note"] == "contact [REDACTED_EMAIL]"
