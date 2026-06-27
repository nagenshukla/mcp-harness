"""The `mcp-harness init` and `mcp-harness wrap` scaffolding commands (no MCP SDK needed)."""

from __future__ import annotations

from mcp_harness.cli import main


def test_init_creates_server_file(tmp_path, capsys):
    rc = main(["init", "my-svc", "--dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    created = tmp_path / "my_svc_server.py"
    assert created.exists()
    text = created.read_text(encoding="utf-8")
    assert "Harness(" in text
    assert 'name="my-svc"' in text
    assert "@harness.tool()" in text
    assert str(created) in out


def test_init_refuses_to_overwrite_without_force(tmp_path):
    assert main(["init", "dup", "--dir", str(tmp_path)]) == 0
    assert main(["init", "dup", "--dir", str(tmp_path)]) == 1
    # --force allows it.
    assert main(["init", "dup", "--dir", str(tmp_path), "--force"]) == 0


def test_wrap_detects_fastmcp_and_generates_companion(tmp_path):
    src = tmp_path / "myserver.py"
    src.write_text(
        "from mcp.server.fastmcp import FastMCP\n\nmcp = FastMCP('demo')\n",
        encoding="utf-8",
    )
    rc = main(["wrap", str(src)])
    assert rc == 0
    companion = tmp_path / "governed_myserver.py"
    assert companion.exists()
    text = companion.read_text(encoding="utf-8")
    assert "Harness.from_fastmcp" in text
    assert "from myserver import mcp as _server" in text
    # Original file is untouched.
    assert "Harness" not in src.read_text(encoding="utf-8")


def test_wrap_handles_aliased_import_var(tmp_path):
    src = tmp_path / "app.py"
    src.write_text("import mcp.server.fastmcp as f\nserver = f.FastMCP('x')\n", encoding="utf-8")
    assert main(["wrap", str(src)]) == 0
    text = (tmp_path / "governed_app.py").read_text(encoding="utf-8")
    assert "from app import server as _server" in text


def test_wrap_errors_when_no_fastmcp(tmp_path):
    src = tmp_path / "plain.py"
    src.write_text("x = 1\n", encoding="utf-8")
    assert main(["wrap", str(src)]) == 1


def test_wrap_errors_on_missing_file(tmp_path):
    assert main(["wrap", str(tmp_path / "nope.py")]) == 1
