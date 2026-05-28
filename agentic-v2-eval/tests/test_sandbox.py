"""Tests for sandbox implementations."""

from __future__ import annotations

import sys

import pytest
from agentic_v2_eval.sandbox import ExecutionResult, LocalSubprocessSandbox, Sandbox


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_success_property_true(self):
        result = ExecutionResult(exit_code=0, stdout="ok", stderr="", duration_ms=10)
        assert result.is_success is True

    def test_success_property_false_exit_code(self):
        result = ExecutionResult(exit_code=1, stdout="", stderr="err", duration_ms=10)
        assert result.is_success is False

    def test_success_property_false_error(self):
        result = ExecutionResult(
            exit_code=0, stdout="", stderr="", duration_ms=10, error="boom"
        )
        assert result.is_success is False


class TestLocalSubprocessSandbox:
    """Tests for LocalSubprocessSandbox."""

    def test_implements_sandbox_abc(self):
        with LocalSubprocessSandbox() as sb:
            assert isinstance(sb, Sandbox)

    def test_run_command_echo(self):
        with LocalSubprocessSandbox() as sb:
            if sys.platform == "win32":
                result = sb.run_command(["cmd", "/c", "echo hello"])
            else:
                result = sb.run_command(["echo", "hello"])
            assert result.is_success
            assert "hello" in result.stdout

    def test_run_command_exit_code(self):
        with LocalSubprocessSandbox() as sb:
            if sys.platform == "win32":
                result = sb.run_command(["cmd", "/c", "exit 42"])
            else:
                result = sb.run_command(["sh", "-c", "exit 42"])
            assert result.exit_code == 42
            assert result.is_success is False

    def test_run_command_timeout(self):
        with LocalSubprocessSandbox(timeout=1) as sb:
            if sys.platform == "win32":
                result = sb.run_command(["ping", "-n", "10", "127.0.0.1"])
            else:
                result = sb.run_command(["sleep", "10"])
            assert result.is_success is False
            assert "timed out" in (result.error or "").lower()

    def test_run_command_not_found(self):
        with LocalSubprocessSandbox() as sb:
            result = sb.run_command(["nonexistent_command_xyz123"])
            assert result.is_success is False
            assert "not found" in (result.error or "").lower()

    def test_safe_mode_blocks_rm(self):
        with LocalSubprocessSandbox(safe_mode=True) as sb:
            result = sb.run_command(["rm", "-rf", "/"])
            assert result.is_success is False
            assert "blocked" in (result.error or "").lower()

    def test_safe_mode_off_allows_commands(self):
        with LocalSubprocessSandbox(safe_mode=False) as sb:
            # This won't actually delete anything dangerous, just tests the check
            if sys.platform == "win32":
                result = sb.run_command(["cmd", "/c", "echo safe_mode_off"])
            else:
                result = sb.run_command(["echo", "safe_mode_off"])
            assert result.is_success

    def test_write_and_read_file(self):
        with LocalSubprocessSandbox() as sb:
            sb.write_file("test.txt", "hello world")
            content = sb.read_file("test.txt")
            assert content == "hello world"

    def test_write_file_nested_path(self):
        with LocalSubprocessSandbox() as sb:
            sb.write_file("subdir/nested/test.txt", "nested content")
            content = sb.read_file("subdir/nested/test.txt")
            assert content == "nested content"

    def test_read_file_not_found(self):
        with LocalSubprocessSandbox() as sb, pytest.raises(FileNotFoundError):
            sb.read_file("nonexistent.txt")

    def test_path_escape_blocked_write(self):
        with LocalSubprocessSandbox() as sb:
            with pytest.raises(ValueError, match="escapes sandbox"):
                sb.write_file("../escape.txt", "bad")

    def test_path_escape_blocked_read(self):
        with LocalSubprocessSandbox() as sb:
            with pytest.raises(ValueError, match="escapes sandbox"):
                sb.read_file("../../../etc/passwd")

    def test_cwd_escape_blocked(self):
        with LocalSubprocessSandbox() as sb:
            result = sb.run_command(["echo", "test"], cwd="../..")
            assert result.is_success is False
            assert "escapes sandbox" in (result.error or "").lower()

    def test_exists(self):
        with LocalSubprocessSandbox() as sb:
            assert sb.exists("missing.txt") is False
            sb.write_file("present.txt", "here")
            assert sb.exists("present.txt") is True

    def test_run_python_script(self):
        with LocalSubprocessSandbox() as sb:
            sb.write_file("script.py", "print(2 + 2)")
            result = sb.run_command([sys.executable, "script.py"])
            assert result.is_success
            assert "4" in result.stdout

    def test_run_python_with_error(self):
        with LocalSubprocessSandbox() as sb:
            sb.write_file("bad.py", "raise ValueError('oops')")
            result = sb.run_command([sys.executable, "bad.py"])
            assert result.exit_code != 0
            assert "ValueError" in result.stderr

    def test_env_override(self):
        with LocalSubprocessSandbox() as sb:
            if sys.platform == "win32":
                result = sb.run_command(
                    ["cmd", "/c", "echo %MY_VAR%"], env={"MY_VAR": "hello123"}
                )
            else:
                result = sb.run_command(
                    ["sh", "-c", "echo $MY_VAR"], env={"MY_VAR": "hello123"}
                )
            assert "hello123" in result.stdout

    def test_duration_tracked(self):
        with LocalSubprocessSandbox() as sb:
            if sys.platform == "win32":
                result = sb.run_command(["cmd", "/c", "echo fast"])
            else:
                result = sb.run_command(["echo", "fast"])
            assert result.duration_ms >= 0

    def test_cleanup_on_exit(self):
        sb = LocalSubprocessSandbox()
        root = sb.root
        sb.write_file("temp.txt", "data")
        assert root.exists()
        sb.cleanup()
        assert not root.exists()
