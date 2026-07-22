"""Containment and fail-closed tests for ``agentic_v2.tools.builtin.git_ops``.

Mirrors ``tests/tools/test_file_ops_containment.py``: git tools must refuse to
operate when ``AGENTIC_FILE_BASE_DIR`` is unset, and a ``cwd`` outside the
configured sandbox root must be rejected (with no git subprocess ever
started) before falling through to the git-command execution path.

This is the cwd-containment half of audit finding ARP#2 — GitTool's ``cwd``
parameter was only existence-checked, so an agent-supplied ``cwd`` could
stage/commit in ANY git repository on disk. Approval gating for git ops is
explicitly OUT of scope here (ADR-047 ratified git as un-gated); these tests
only exercise the sandbox-containment invariant.
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import AsyncMock, patch

from agentic_v2.settings import get_settings
from agentic_v2.tools.builtin.git_ops import GitStatusTool, GitTool

# ---------------------------------------------------------------------------
# Fail-closed: AGENTIC_FILE_BASE_DIR unset
# ---------------------------------------------------------------------------


async def test_git_tool_fail_closed_when_base_dir_unset(tmp_path):
    """GitTool must refuse to run when AGENTIC_FILE_BASE_DIR is unset.

    No git subprocess may be started — the containment check must short
    circuit before ``asyncio.create_subprocess_exec`` is ever reached.
    """
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGENTIC_FILE_BASE_DIR", None)
        get_settings.cache_clear()
        tool = GitTool()
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_exec:
            result = await tool.execute(command="status", cwd=str(tmp_path))

    assert result.success is False
    assert "AGENTIC_FILE_BASE_DIR" in result.error
    mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# Containment: cwd outside the configured base is rejected
# ---------------------------------------------------------------------------


async def test_git_tool_cwd_outside_base_dir_rejected(tmp_path):
    """A cwd outside the configured base dir is rejected, no subprocess runs."""
    allowed_base = tmp_path / "allowed"
    allowed_base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with patch.dict(os.environ, {"AGENTIC_FILE_BASE_DIR": str(allowed_base)}):
        get_settings.cache_clear()
        tool = GitTool()
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_exec:
            result = await tool.execute(command="status", cwd=str(outside))

    assert result.success is False
    assert "escapes base directory" in result.error.lower()
    mock_exec.assert_not_called()


async def test_git_status_wrapper_cwd_outside_base_dir_rejected(tmp_path):
    """The convenience wrapper (GitStatusTool) inherits the same containment."""
    allowed_base = tmp_path / "allowed"
    allowed_base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with patch.dict(os.environ, {"AGENTIC_FILE_BASE_DIR": str(allowed_base)}):
        get_settings.cache_clear()
        tool = GitStatusTool()
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_exec:
            result = await tool.execute(cwd=str(outside))

    assert result.success is False
    assert "escapes base directory" in result.error.lower()
    mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# Sanity: a cwd inside the configured base dir still works
# ---------------------------------------------------------------------------


async def test_git_tool_cwd_inside_base_dir_still_works(tmp_path):
    """A cwd inside (here: equal to) the configured base dir is unaffected."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    with patch.dict(os.environ, {"AGENTIC_FILE_BASE_DIR": str(tmp_path)}):
        get_settings.cache_clear()
        tool = GitTool()
        result = await tool.execute(command="status", cwd=str(tmp_path))

    assert result.success is True
    assert "output" in result.data
