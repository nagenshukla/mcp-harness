"""``mcp-harness`` command-line interface.

Currently exposes ``daily-rollup``: aggregate a cost JSONL file (as produced by
:class:`~mcp_harness.governance.cost_tracking.CostTracking`) into a per-group spend report —
the report Finance asks for.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from . import __version__


@dataclass
class _Bucket:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    tools: set[str] = field(default_factory=set)

    def add(self, record: dict[str, Any]) -> None:
        self.calls += 1
        self.input_tokens += int(record.get("input_tokens", 0) or 0)
        self.output_tokens += int(record.get("output_tokens", 0) or 0)
        self.cost_usd += float(record.get("cost_usd", 0.0) or 0.0)
        if record.get("tool"):
            self.tools.add(str(record["tool"]))


def _read_records(path: str) -> Iterator[dict[str, Any]]:
    stream: TextIO = sys.stdin if path == "-" else open(path, encoding="utf-8")
    try:
        for line_no, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"warning: skipping malformed line {line_no}: {exc}", file=sys.stderr)
    finally:
        if stream is not sys.stdin:
            stream.close()


def _rollup(
    records: Iterable[dict[str, Any]], group_by: str, date_prefix: str | None
) -> dict[str, _Bucket]:
    buckets: dict[str, _Bucket] = defaultdict(_Bucket)
    for record in records:
        if date_prefix and not str(record.get("timestamp", "")).startswith(date_prefix):
            continue
        key = str(record.get(group_by) or "unattributed")
        buckets[key].add(record)
    return buckets


def _print_table(buckets: dict[str, _Bucket], group_by: str, out: TextIO) -> None:
    if not buckets:
        print("No cost records matched.", file=out)
        return
    rows = sorted(buckets.items(), key=lambda kv: kv[1].cost_usd, reverse=True)
    width = max(len(group_by), max(len(k) for k in buckets))
    header = f"{group_by:<{width}}  {'calls':>8}  {'in_tok':>10}  {'out_tok':>10}  {'cost_usd':>12}"
    print(header, file=out)
    print("-" * len(header), file=out)
    total = _Bucket()
    for key, bucket in rows:
        print(
            f"{key:<{width}}  {bucket.calls:>8}  {bucket.input_tokens:>10}  "
            f"{bucket.output_tokens:>10}  {bucket.cost_usd:>12.4f}",
            file=out,
        )
        total.calls += bucket.calls
        total.input_tokens += bucket.input_tokens
        total.output_tokens += bucket.output_tokens
        total.cost_usd += bucket.cost_usd
    print("-" * len(header), file=out)
    print(
        f"{'TOTAL':<{width}}  {total.calls:>8}  {total.input_tokens:>10}  "
        f"{total.output_tokens:>10}  {total.cost_usd:>12.4f}",
        file=out,
    )


def _daily_rollup(args: argparse.Namespace) -> int:
    buckets = _rollup(_read_records(args.path), args.group_by, args.date)
    if args.json:
        payload = {
            key: {
                "calls": b.calls,
                "input_tokens": b.input_tokens,
                "output_tokens": b.output_tokens,
                "cost_usd": round(b.cost_usd, 6),
                "tools": sorted(b.tools),
            }
            for key, b in buckets.items()
        }
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        _print_table(buckets, args.group_by, sys.stdout)
    return 0


_NEW_SERVER_TEMPLATE = '''\
"""Governed MCP server scaffolded by `mcp-harness init`.

Run it:  python {filename}
Then attribute spend:  mcp-harness daily-rollup {name}-costs.jsonl
"""

from mcp_harness import Harness
from mcp_harness.auth import APIKeyAuth
from mcp_harness.governance import CostTracking, Quotas
from mcp_harness.observability import StructuredLogging

harness = Harness(
    name="{name}",
    auth=APIKeyAuth(
        keys={{
            # Load real keys from a secret store via APIKeyAuth(key_loader=...).
            "sk-dev": {{"id": "dev", "team": "platform"}},
        }}
    ),
    middleware=[
        StructuredLogging(),
        Quotas(per_principal_per_minute=60),
        CostTracking(
            sink="jsonl://{name}-costs.jsonl",
            cost_center_resolver=lambda p: p.team or "unattributed",
        ),
    ],
)


@harness.tool()
async def echo(text: str) -> str:
    """Echo the input back. Replace with your real tools."""
    return text


if __name__ == "__main__":
    harness.run()  # stdio by default; transport="streamable-http" for HTTP
'''

_WRAP_TEMPLATE = '''\
"""Governed wrapper for `{module}.{var}`, generated by `mcp-harness wrap`.

Routes the existing FastMCP server's tools through the mcp-harness governance pipeline
*without modifying the original file*. The original tools keep their schemas; calls now flow
through auth, quotas, cost attribution, and structured logging.

Run it:  python {out_name}
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from {module} import {var} as _server  # noqa: E402

from mcp_harness import Harness  # noqa: E402
from mcp_harness.governance import CostTracking, Quotas  # noqa: E402
from mcp_harness.observability import StructuredLogging  # noqa: E402

harness = Harness.from_fastmcp(
    _server,
    middleware=[
        StructuredLogging(),
        Quotas(per_principal_per_minute=60),
        CostTracking(
            sink="jsonl://{module}-costs.jsonl",
            cost_center_resolver=lambda p: p.team or "unattributed",
        ),
    ],
)

if __name__ == "__main__":
    harness.run()
'''

# Matches e.g.  ``mcp = FastMCP("name")``  or  ``server = mcp.server.fastmcp.FastMCP(...)``.
_FASTMCP_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*[\w.]*FastMCP\s*\(", re.MULTILINE)


def _write_file(path: Path, content: str, *, force: bool) -> bool:
    if path.exists() and not force:
        print(f"refusing to overwrite existing {path} (use --force)", file=sys.stderr)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _init(args: argparse.Namespace) -> int:
    name = args.name
    filename = f"{name.replace('-', '_')}_server.py"
    out = Path(args.dir) / filename
    content = _NEW_SERVER_TEMPLATE.format(name=name, filename=filename)
    if not _write_file(out, content, force=args.force):
        return 1
    print(f"Created {out}")
    print("Next:  pip install 'mcp-harness[server]'  &&  python", out)
    return 0


def _detect_fastmcp_var(source: str) -> str | None:
    match = _FASTMCP_ASSIGN.search(source)
    return match.group(1) if match else None


def _wrap(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.exists():
        print(f"no such file: {target}", file=sys.stderr)
        return 1
    var = _detect_fastmcp_var(target.read_text(encoding="utf-8"))
    if var is None:
        print(
            f"could not find a FastMCP instance (e.g. `server = FastMCP(...)`) in {target}.\n"
            "Wrap it manually:\n\n"
            f"    from {target.stem} import <your_server> as _server\n"
            "    from mcp_harness import Harness\n"
            "    harness = Harness.from_fastmcp(_server, middleware=[...])\n",
            file=sys.stderr,
        )
        return 1
    out = Path(args.out) if args.out else target.with_name(f"governed_{target.stem}.py")
    content = _WRAP_TEMPLATE.format(module=target.stem, var=var, out_name=out.name)
    if not _write_file(out, content, force=args.force):
        return 1
    print(f"Detected FastMCP server '{var}' in {target.name}.")
    print(f"Created {out} (original file untouched).")
    print(f"Next:  python {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-harness", description=__doc__)
    parser.add_argument("--version", action="version", version=f"mcp-harness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    rollup = sub.add_parser(
        "daily-rollup",
        help="Aggregate a cost JSONL file into a per-cost-center spend report.",
    )
    rollup.add_argument("path", help="Path to a cost JSONL file, or '-' for stdin.")
    rollup.add_argument(
        "--group-by",
        default="cost_center",
        help="Record field to group by (default: cost_center; e.g. team, tool, principal_id).",
    )
    rollup.add_argument(
        "--date",
        default=None,
        help="Only include records whose timestamp starts with this prefix (e.g. 2026-06-27).",
    )
    rollup.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    rollup.set_defaults(func=_daily_rollup)

    init = sub.add_parser("init", help="Scaffold a new governed MCP server file.")
    init.add_argument("name", nargs="?", default="governed-mcp", help="Server name.")
    init.add_argument("--dir", default=".", help="Directory to write the file into (default: .).")
    init.add_argument("--force", action="store_true", help="Overwrite if the file exists.")
    init.set_defaults(func=_init)

    wrap = sub.add_parser(
        "wrap",
        help="Generate a governed wrapper for an existing FastMCP server (original untouched).",
    )
    wrap.add_argument("path", help="Path to a Python file containing a FastMCP instance.")
    wrap.add_argument("--out", default=None, help="Output path (default: governed_<stem>.py).")
    wrap.add_argument("--force", action="store_true", help="Overwrite if the output exists.")
    wrap.set_defaults(func=_wrap)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
