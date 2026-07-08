"""Tests for Phase 2D enhanced tools (git, http, shell, code_analysis, search)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web

from agentic_v2.tools.builtin.build_ops import BuildAppTool
from agentic_v2.tools.builtin.code_analysis import AstDumpTool, CodeAnalysisTool
from agentic_v2.tools.builtin.git_ops import GitDiffTool, GitStatusTool, GitTool
from agentic_v2.tools.builtin.http_ops import HttpGetTool, HttpPostTool, HttpTool
from agentic_v2.tools.builtin.search_ops import GrepTool, SearchTool
from agentic_v2.tools.builtin.shell_ops import ShellExecTool, ShellTool

# Gated builtins (shell/http-post/build_app) self-gate on execute (ADR-047);
# approve-all so these tests exercise the tool bodies, not the approval gate.
pytestmark = pytest.mark.usefixtures("auto_approve_tools")

# ============================================================================
# Build Tool Tests
# ============================================================================


@pytest.mark.asyncio
async def test_build_app_tool_missing_root():
    """BuildAppTool should fail for a missing project root."""
    tool = BuildAppTool()
    result = await tool.execute(project_root="/definitely/not/a/real/path")

    assert not result.success
    assert "does not exist" in result.error.lower()


@pytest.mark.asyncio
async def test_build_app_tool_dry_run_python_detection(tmp_path: Path):
    """BuildAppTool dry-run should detect python stack and plan phases."""
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    tool = BuildAppTool()
    result = await tool.execute(project_root=str(tmp_path), dry_run=True)

    assert result.success
    assert result.data["detected_stack"] == "python"
    assert result.data["phase_results"]["install"]["skipped"]
    assert result.data["phase_results"]["install"]["reason"] == "dry_run"
    assert result.data["ready_for_release"]


@pytest.mark.asyncio
async def test_build_app_tool_exec_with_explicit_commands(tmp_path: Path):
    """BuildAppTool should execute explicit commands and report phase results."""
    tool = BuildAppTool()

    result = await tool.execute(
        project_root=str(tmp_path),
        stack_hint="unknown",
        install_command="python -c \"print('install-ok')\"",
        build_command="python -c \"print('build-ok')\"",
        test_command="python -c \"print('test-ok')\"",
        run_smoke=True,
        smoke_command="python -c \"print('smoke-ok')\"",
    )

    assert result.success
    assert result.data["ready_for_release"]
    assert not result.data["failed_phases"]
    assert result.data["phase_results"]["build"]["success"]
    assert "build-ok" in result.data["phase_results"]["build"]["stdout"]


# ============================================================================
# Git Tools Tests
# ============================================================================


@pytest.mark.asyncio
async def test_git_tool_status():
    """Test GitTool status command."""
    tool = GitTool()
    result = await tool.execute(command="status")

    # Should succeed or fail gracefully if not a git repo
    assert isinstance(result.success, bool)
    if result.success:
        assert "output" in result.data


@pytest.mark.asyncio
async def test_git_tool_invalid_command():
    """Test GitTool with invalid command."""
    tool = GitTool()
    result = await tool.execute(command="invalid_command")

    assert not result.success
    assert "not allowed" in result.error.lower()


@pytest.mark.asyncio
async def test_git_tool_nonexistent_cwd():
    """Test GitTool with non-existent working directory."""
    tool = GitTool()
    result = await tool.execute(command="status", cwd="/nonexistent/path")

    assert not result.success
    assert "does not exist" in result.error.lower()


@pytest.mark.asyncio
async def test_git_status_tool():
    """Test GitStatusTool convenience wrapper."""
    tool = GitStatusTool()
    result = await tool.execute()

    assert isinstance(result.success, bool)


@pytest.mark.asyncio
async def test_git_diff_tool():
    """Test GitDiffTool convenience wrapper."""
    tool = GitDiffTool()
    result = await tool.execute()

    assert isinstance(result.success, bool)


# ============================================================================
# HTTP Tools Tests
# ============================================================================


@pytest.fixture
def _disable_ssrf_guard_for_localhost(monkeypatch: pytest.MonkeyPatch):
    """Disable the SSRF private-IP guard so tests can reach a local test server.

    These tests intentionally use a 127.0.0.1 server; real SSRF
    protection is exercised by tests/test_ssrf_guard.py.
    """
    import agentic_v2.settings as settings_mod

    monkeypatch.setenv("AGENTIC_BLOCK_PRIVATE_IPS", "0")
    settings_mod.get_settings.cache_clear()
    yield
    settings_mod.get_settings.cache_clear()


@pytest_asyncio.fixture
async def http_test_server_base_url(
    _disable_ssrf_guard_for_localhost: None,
) -> str:
    """Start a small local HTTP server for offline-safe tests."""

    async def status_handler(request: web.Request) -> web.Response:
        code = int(request.match_info["code"])
        return web.Response(status=code, text=f"status={code}")

    async def delay_handler(request: web.Request) -> web.Response:
        seconds = float(request.match_info["seconds"])
        await asyncio.sleep(seconds)
        return web.Response(status=200, text="ok")

    async def post_handler(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        return web.json_response({"received": payload})

    app = web.Application()
    app.router.add_get("/status/{code}", status_handler)
    app.router.add_get("/delay/{seconds}", delay_handler)
    app.router.add_post("/post", post_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    # Retrieve the ephemeral port assigned by the OS
    server = site._server
    assert server is not None
    sockets = getattr(server, "sockets", None)
    assert sockets
    port = sockets[0].getsockname()[1]

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_http_tool_get(http_test_server_base_url: str):
    """Test HttpTool GET request."""
    tool = HttpTool()
    # Use a local test endpoint (offline-safe)
    result = await tool.execute(
        url=f"{http_test_server_base_url}/status/200", method="GET", timeout=10.0
    )

    assert result.success
    assert result.data["status"] == 200


@pytest.mark.asyncio
async def test_http_tool_invalid_method():
    """Test HttpTool with invalid method."""
    tool = HttpTool()
    result = await tool.execute(url="https://example.com", method="INVALID")

    assert not result.success
    assert "not allowed" in result.error.lower()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_http_tool_timeout(http_test_server_base_url: str):
    """Test HttpTool timeout handling."""
    tool = HttpTool()
    # Use a deliberately slow local endpoint
    result = await tool.execute(
        url=f"{http_test_server_base_url}/delay/10", method="GET", timeout=1.0
    )

    # Should timeout or fail
    assert not result.success


@pytest.mark.asyncio
async def test_http_get_tool(http_test_server_base_url: str):
    """Test HttpGetTool convenience wrapper."""
    tool = HttpGetTool()
    result = await tool.execute(url=f"{http_test_server_base_url}/status/200")

    assert result.success


@pytest.mark.asyncio
async def test_http_post_tool(http_test_server_base_url: str):
    """Test HttpPostTool convenience wrapper."""
    tool = HttpPostTool()
    result = await tool.execute(
        url=f"{http_test_server_base_url}/post", body={"test": "data"}
    )

    assert result.success
    assert result.data["status"] == 200


# ============================================================================
# Shell Tools Tests
# ============================================================================


@pytest.mark.asyncio
async def test_shell_tool_basic():
    """Test ShellTool with basic command."""
    tool = ShellTool()

    # Use cross-platform command
    if Path("/bin/echo").exists() or Path("/usr/bin/echo").exists():
        cmd = "echo hello"
    else:
        cmd = "echo hello"  # Windows uses cmd.exe

    result = await tool.execute(command=cmd)

    assert result.success
    assert "hello" in result.data["stdout"].lower()


@pytest.mark.asyncio
async def test_shell_tool_dangerous_command():
    """Test ShellTool blocks dangerous commands."""
    tool = ShellTool()
    result = await tool.execute(command="rm -rf /")

    assert not result.success
    assert "dangerous" in result.error.lower()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_shell_tool_timeout():
    """Test ShellTool timeout handling."""
    tool = ShellTool()

    # Use a Python sleep command (cross-platform)
    cmd = 'python -c "import time; time.sleep(10)"'

    result = await tool.execute(command=cmd, timeout=1.0)

    # Should fail due to timeout (exact error message may vary)
    assert not result.success


@pytest.mark.asyncio
async def test_shell_tool_nonexistent_cwd():
    """Test ShellTool with non-existent working directory."""
    tool = ShellTool()
    result = await tool.execute(command="echo test", cwd="/nonexistent/path")

    assert not result.success
    assert "does not exist" in result.error.lower()


@pytest.mark.asyncio
async def test_shell_exec_tool(monkeypatch: pytest.MonkeyPatch):
    """Test ShellExecTool with argument escaping."""
    monkeypatch.setenv("AGENTIC_SHELL_ALLOWED_COMMANDS", "python")
    tool = ShellExecTool()

    # Use Python to echo (cross-platform)
    result = await tool.execute(program="python", args=["-c", "print('hello')"])

    assert result.success
    assert "hello" in result.data["stdout"].lower()


# ============================================================================
# Code Analysis Tools Tests
# ============================================================================


@pytest.mark.asyncio
async def test_code_analysis_tool_basic():
    """Test CodeAnalysisTool with simple code."""
    tool = CodeAnalysisTool()

    code = """
def hello():
    return "world"

class MyClass:
    pass
"""

    result = await tool.execute(source=code, from_file=False)

    assert result.success
    assert result.data["functions"]["count"] == 1
    assert result.data["classes"]["count"] == 1
    assert "hello" in result.data["functions"]["names"]


@pytest.mark.asyncio
async def test_code_analysis_tool_syntax_error():
    """Test CodeAnalysisTool with syntax error."""
    tool = CodeAnalysisTool()
    result = await tool.execute(source="def invalid syntax", from_file=False)

    assert not result.success
    assert "syntax error" in result.error.lower()


@pytest.mark.asyncio
async def test_code_analysis_tool_file():
    """Test CodeAnalysisTool with file input."""
    tool = CodeAnalysisTool()

    # Create temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("def test():\n    pass\n")
        temp_path = f.name

    try:
        result = await tool.execute(source=temp_path, from_file=True)
        assert result.success
        assert result.data["functions"]["count"] == 1
    finally:
        Path(temp_path).unlink()


@pytest.mark.asyncio
async def test_code_analysis_tool_complexity():
    """Test CodeAnalysisTool complexity metrics."""
    tool = CodeAnalysisTool()

    code = """
def complex_function(x):
    if x > 0:
        for i in range(x):
            if i % 2 == 0:
                pass
    return x
"""

    result = await tool.execute(source=code, metrics=["complexity"])

    assert result.success
    assert "complexity" in result.data
    assert result.data["complexity"]["cyclomatic"] > 1


@pytest.mark.asyncio
async def test_ast_dump_tool():
    """Test AstDumpTool."""
    tool = AstDumpTool()
    result = await tool.execute(source="x = 1")

    assert result.success
    assert "ast" in result.data
    assert "Module" in result.data["ast"]


# ============================================================================
# Search Tools Tests
# ============================================================================


@pytest.mark.asyncio
async def test_search_tool_regex():
    """Test SearchTool with regex mode."""
    tool = SearchTool()

    # Create temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world\ntest pattern\nhello again\n")
        temp_path = f.name

    try:
        result = await tool.execute(pattern="hello", path=temp_path, mode="regex")

        assert result.success
        assert result.data["total_matches"] == 2
    finally:
        Path(temp_path).unlink()


@pytest.mark.asyncio
async def test_search_tool_fuzzy():
    """Test SearchTool with fuzzy mode."""
    tool = SearchTool()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("HELLO world\ntest pattern\n")
        temp_path = f.name

    try:
        result = await tool.execute(pattern="hello", path=temp_path, mode="fuzzy")

        assert result.success
        assert result.data["total_matches"] >= 1
    finally:
        Path(temp_path).unlink()


@pytest.mark.asyncio
async def test_search_tool_semantic():
    """Test SearchTool with semantic mode."""
    tool = SearchTool()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("error handling code\nexception processing\n")
        temp_path = f.name

    try:
        result = await tool.execute(
            pattern="error handling", path=temp_path, mode="semantic"
        )

        assert result.success
        # Should find lines with related words
    finally:
        Path(temp_path).unlink()


@pytest.mark.asyncio
async def test_search_tool_nonexistent_path():
    """Test SearchTool with non-existent path."""
    tool = SearchTool()
    result = await tool.execute(pattern="test", path="/nonexistent/path")

    assert not result.success
    assert "does not exist" in result.error.lower()


@pytest.mark.asyncio
async def test_search_tool_invalid_mode():
    """Test SearchTool with invalid mode."""
    tool = SearchTool()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test")
        temp_path = f.name

    try:
        result = await tool.execute(pattern="test", path=temp_path, mode="invalid_mode")

        assert not result.success
        assert "invalid mode" in result.error.lower()
    finally:
        Path(temp_path).unlink()


@pytest.mark.asyncio
async def test_grep_tool():
    """Test GrepTool convenience wrapper."""
    tool = GrepTool()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test line\nanother line\n")
        temp_path = f.name

    try:
        result = await tool.execute(pattern="test", path=temp_path)
        assert result.success
    finally:
        Path(temp_path).unlink()


# ============================================================================
# Tool Schema Tests
# ============================================================================


def test_all_tools_have_valid_schemas():
    """Test that all new tools have valid schemas."""
    tools = [
        GitTool(),
        GitStatusTool(),
        GitDiffTool(),
        HttpTool(),
        HttpGetTool(),
        HttpPostTool(),
        ShellTool(),
        ShellExecTool(),
        CodeAnalysisTool(),
        AstDumpTool(),
        SearchTool(),
        GrepTool(),
    ]

    for tool in tools:
        schema = tool.get_schema()
        assert schema.name
        assert schema.description
        assert schema.parameters
        assert isinstance(schema.tier, int)
        assert 0 <= schema.tier <= 3


def test_tool_tiers():
    """Test that tools are assigned correct tiers."""
    # Tier 0 tools (no LLM needed)
    assert GitTool().tier == 0
    assert HttpTool().tier == 0
    assert ShellTool().tier == 0
    assert GrepTool().tier == 0

    # Tier 1 tools (small model)
    assert CodeAnalysisTool().tier == 1
    assert AstDumpTool().tier == 1

    # Tier 2 tools (medium model)
    assert SearchTool().tier == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
