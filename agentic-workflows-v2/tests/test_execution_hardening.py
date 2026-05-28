"""Regression tests for subprocess execution hardening."""

from __future__ import annotations

import pytest

from agentic_v2.tools.builtin.code_execution import CodeExecutionTool
from agentic_v2.tools.builtin.shell_ops import ShellTool


@pytest.mark.asyncio
async def test_shell_tool_rejects_shell_metacharacters() -> None:
    result = await ShellTool().execute("echo safe && echo unsafe")

    assert not result.success
    assert "metacharacters" in (result.error or "")


def test_code_execution_env_excludes_ambient_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-leak")
    monkeypatch.setenv("AGENTIC_API_KEY", "should-not-leak")

    env = CodeExecutionTool._subprocess_env()

    assert "OPENAI_API_KEY" not in env
    assert "AGENTIC_API_KEY" not in env
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
