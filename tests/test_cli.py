"""The daily-rollup CLI."""

from __future__ import annotations

import json

from mcp_harness.cli import main

_RECORDS = [
    {"timestamp": "2026-06-27T10:00:00Z", "tool": "search", "cost_center": "finance",
     "team": "finance", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.5},
    {"timestamp": "2026-06-27T11:00:00Z", "tool": "list", "cost_center": "finance",
     "team": "finance", "input_tokens": 200, "output_tokens": 100, "cost_usd": 1.0},
    {"timestamp": "2026-06-27T12:00:00Z", "tool": "search", "cost_center": "platform",
     "team": "platform", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.05},
    {"timestamp": "2026-06-26T09:00:00Z", "tool": "search", "cost_center": "finance",
     "team": "finance", "input_tokens": 999, "output_tokens": 999, "cost_usd": 9.0},
]


def _write_jsonl(tmp_path):
    path = tmp_path / "costs.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in _RECORDS) + "\n", encoding="utf-8")
    return path


def test_daily_rollup_table(tmp_path, capsys):
    path = _write_jsonl(tmp_path)
    rc = main(["daily-rollup", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "finance" in out and "platform" in out
    assert "TOTAL" in out


def test_daily_rollup_json_grouped_by_team(tmp_path, capsys):
    path = _write_jsonl(tmp_path)
    rc = main(["daily-rollup", str(path), "--group-by", "team", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    # finance: 0.5 + 1.0 + 9.0 across all dates
    assert round(data["finance"]["cost_usd"], 2) == 10.5
    assert data["finance"]["calls"] == 3
    assert data["platform"]["calls"] == 1


def test_daily_rollup_date_filter(tmp_path, capsys):
    path = _write_jsonl(tmp_path)
    rc = main(["daily-rollup", str(path), "--group-by", "team", "--date", "2026-06-27", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    # The 2026-06-26 record is excluded -> finance is 0.5 + 1.0.
    assert round(data["finance"]["cost_usd"], 2) == 1.5
    assert data["finance"]["calls"] == 2
