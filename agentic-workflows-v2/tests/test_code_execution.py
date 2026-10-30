"""Tests for CodeExecutionTool: denylist checks and child-process execution."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from agentic_v2.tools.builtin.code_execution import CodeExecutionTool

# CodeExecutionTool self-gates on execute (ADR-047); approve-all so these tests
# exercise the denylist/safety logic, not the approval gate.
pytestmark = pytest.mark.usefixtures("auto_approve_tools")


class TestCodeSafetyChecker:
    """Tests for _check_code_safety blocklist."""

    def test_dangerous_import_blocked(self) -> None:
        """Import subprocess is blocked."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("import subprocess")
        assert result is not None
        assert "subprocess" in result

    def test_dangerous_from_import_blocked(self) -> None:
        """From subprocess import run is blocked."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("from subprocess import run")
        assert result is not None
        assert "subprocess" in result

    def test_dangerous_pattern_os_system_blocked(self) -> None:
        """os.system is blocked."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("os.system('ls')")
        assert result is not None
        assert "os.system" in result

    def test_open_call_blocked(self) -> None:
        """Open() is blocked by the denylist."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("f = open('file.txt')")
        assert result is not None
        assert "open(" in result

    def test_pathlib_blocked(self) -> None:
        """pathlib.Path() is blocked."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("pathlib.Path('/etc/passwd')")
        assert result is not None
        assert "pathlib.Path(" in result

    def test_sys_modules_access_blocked(self) -> None:
        """sys.modules access is blocked by the denylist."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("x = sys.modules['os']")
        assert result is not None
        assert "sys.modules" in result

    def test_loader_access_blocked(self) -> None:
        """__loader__ access is blocked by the denylist."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("x = builtins.__loader__")
        assert result is not None
        assert "__loader__" in result

    def test_safe_code_passes(self) -> None:
        """Regular math code passes safety check."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("x = 2 + 2\nprint(x)")
        assert result is None

    def test_safe_import_passes(self) -> None:
        """Import math is allowed."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("import math\nprint(math.pi)")
        assert result is None

    def test_denylist_disabled_allows_all(self) -> None:
        """When denylist=False, no code is blocked."""
        tool = CodeExecutionTool(denylist=False)
        result = tool._check_code_safety("import subprocess; subprocess.run(['ls'])")
        assert result is None

    def test_syntax_error_passes_safety(self) -> None:
        """Syntax errors pass safety check (caught at execution time)."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("def foo(:")
        assert result is None

    def test_socket_import_blocked(self) -> None:
        """Import socket is blocked."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("import socket")
        assert result is not None
        assert "socket" in result

    def test_importlib_pattern_blocked(self) -> None:
        """Importlib pattern is blocked."""
        tool = CodeExecutionTool(denylist=True)
        result = tool._check_code_safety("importlib.import_module('os')")
        assert result is not None


def test_code_execution_requires_approval() -> None:
    """The denylist is not a boundary; the approval gate is the real control."""
    assert CodeExecutionTool().requires_approval is True
    assert CodeExecutionTool(denylist=False).requires_approval is True


@pytest.mark.parametrize("value", [True, False])
def test_sandbox_keyword_is_a_deprecated_alias_for_denylist(value: bool) -> None:
    """``sandbox=`` still sets the denylist flag, but warns."""
    with pytest.deprecated_call(match="use denylist="):
        tool = CodeExecutionTool(sandbox=value)
    blocked = tool._check_code_safety("import os") is not None
    assert blocked is value


@pytest.mark.parametrize(("denylist", "sandbox"), [(True, False), (False, True)])
def test_sandbox_and_denylist_together_are_rejected(
    denylist: bool, sandbox: bool
) -> None:
    """A half-migrated call must not let the old keyword override the new one."""
    with pytest.raises(TypeError, match="denylist= only"):
        CodeExecutionTool(denylist=denylist, sandbox=sandbox)


def test_denylist_defaults_on() -> None:
    assert CodeExecutionTool()._check_code_safety("import os") is not None


def test_denylist_keyword_does_not_warn() -> None:
    """The new keyword and the default emit no deprecation warning."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        CodeExecutionTool()
        CodeExecutionTool(denylist=False)


class TestCodeExecution:
    """Tests for CodeExecutionTool.execute."""

    @pytest.mark.asyncio
    async def test_simple_print(self) -> None:
        """Print('hello') captures stdout."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute("print('hello')", timeout=10.0)
        assert result.success
        assert "hello" in result.data["stdout"]

    @pytest.mark.asyncio
    async def test_result_variable_captured(self) -> None:
        """Variable named 'result' is captured in output."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute("result = [1, 2, 3]", timeout=10.0)
        assert result.success
        assert result.data["result"] is not None
        assert "1" in result.data["result"]

    @pytest.mark.asyncio
    async def test_syntax_error_reported(self) -> None:
        """Syntax error in user code returns structured error."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute("def foo(:", timeout=10.0)
        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_runtime_error_reported(self) -> None:
        """1/0 returns error with traceback."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute("x = 1/0", timeout=10.0)
        assert not result.success
        assert "ZeroDivisionError" in result.error

    @pytest.mark.asyncio
    async def test_blocked_import_returns_safety_error(self) -> None:
        """Import subprocess returns safety error without executing."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute("import subprocess", timeout=10.0)
        assert not result.success
        assert "Blocked" in result.error

    @pytest.mark.asyncio
    async def test_safe_import_allowed(self) -> None:
        """Import math is allowed and works."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute("import math\nprint(math.pi)", timeout=10.0)
        assert result.success
        assert "3.14" in result.data["stdout"]

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.timeout(15)
    async def test_timeout_handling(self) -> None:
        """Long-running code is killed after timeout."""
        tool = CodeExecutionTool(denylist=False)
        result = await tool.execute(
            "import time\ntime.sleep(60)",
            timeout=2.0,
        )
        assert not result.success
        assert "timed out" in result.error

    @pytest.mark.asyncio
    @pytest.mark.timeout(20)
    async def test_timeout_kills_and_reaps_subprocess(self) -> None:
        """On timeout the child is explicitly killed and awaited, not left to GC."""
        import asyncio

        spawned: list[asyncio.subprocess.Process] = []
        real_create = asyncio.create_subprocess_exec
        calls: list[str] = []

        async def _spy_create(*args, **kwargs):
            proc = await real_create(*args, **kwargs)
            real_kill, real_wait = proc.kill, proc.wait

            def _kill() -> None:
                calls.append("kill")
                real_kill()

            async def _wait() -> int:
                calls.append("wait")
                return await real_wait()

            proc.kill = _kill  # type: ignore[method-assign]
            proc.wait = _wait  # type: ignore[method-assign]
            spawned.append(proc)
            return proc

        tool = CodeExecutionTool(denylist=False)
        with patch("asyncio.create_subprocess_exec", _spy_create):
            result = await tool.execute("import time\ntime.sleep(60)", timeout=1.0)

        assert not result.success
        assert "timed out" in result.error
        assert len(spawned) == 1
        assert calls.index("kill") < calls.index("wait")
        assert spawned[0].returncode is not None

    @pytest.mark.asyncio
    async def test_multiple_print_statements(self) -> None:
        """Multiple prints are all captured."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute("print('a')\nprint('b')\nprint('c')", timeout=10.0)
        assert result.success
        assert "a" in result.data["stdout"]
        assert "b" in result.data["stdout"]
        assert "c" in result.data["stdout"]

    @pytest.mark.asyncio
    async def test_tool_properties(self) -> None:
        """Tool has correct name, description, and tier."""
        tool = CodeExecutionTool()
        assert tool.name == "execute_python"
        assert "Python" in tool.description
        assert tool.tier == 0
        assert len(tool.examples) > 0


class TestSandboxEscapeCorpus:
    """Regression tests for sandbox escape vectors (S1-06)."""

    async def test_import_via_import_builtin_blocked(self) -> None:
        """__import__('os') must not succeed in sandbox."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute(
            "result = __import__('os').getcwd()",
            timeout=10.0,
        )
        # Either blocked at safety check or fails at runtime — must not succeed
        assert not result.success or result.data.get("result") is None

    async def test_loader_traversal_escape_blocked(self) -> None:
        """sys.modules loader traversal must be blocked by pattern scan."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute(
            "import sys\n"
            "result = sys.modules['builtins'].__loader__.load_module('os').getcwd()",
            timeout=10.0,
        )
        assert not result.success
        assert "sys.modules" in result.error or "Blocked" in result.error

    async def test_subclasses_hierarchy_escape_blocked(self) -> None:
        """().__class__.__base__.__subclasses__() traversal must be blocked."""
        tool = CodeExecutionTool(denylist=True)
        code = "result = ().__class__.__base__.__subclasses__()"
        safety_error = tool._check_code_safety(code)
        assert safety_error is not None
        assert "__subclasses__" in safety_error
        result = await tool.execute(code, timeout=10.0)
        assert not result.success
        assert "__subclasses__" in result.error or "Blocked" in result.error

    async def test_subclasses_popen_filter_escape_blocked(self) -> None:
        """object.__subclasses__() comprehension hunting Popen must be blocked."""
        tool = CodeExecutionTool(denylist=True)
        code = '[c for c in object.__subclasses__() if "Popen" in str(c)]'
        safety_error = tool._check_code_safety(code)
        assert safety_error is not None
        assert "__subclasses__" in safety_error
        result = await tool.execute(code, timeout=10.0)
        assert not result.success
        assert "__subclasses__" in result.error or "Blocked" in result.error

    @pytest.mark.skipif(os.name == "nt", reason="RLIMIT_AS not available on Windows")
    async def test_memory_bomb_timeout(self) -> None:
        """Memory allocation exceeding RLIMIT_AS must fail (POSIX only)."""
        tool = CodeExecutionTool(denylist=True)
        result = await tool.execute(
            "x = 'A' * (600 * 1024 * 1024)",  # 600 MB string — exceeds 512 MB limit
            timeout=5.0,
        )
        assert not result.success
