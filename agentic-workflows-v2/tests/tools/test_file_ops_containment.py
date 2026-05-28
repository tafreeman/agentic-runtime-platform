"""Containment and fail-closed tests for ``agentic_v2.tools.builtin.file_ops``.

These tests exercise the invariant that file tools refuse to operate when
``AGENTIC_FILE_BASE_DIR`` is unset, and that absolute/traversal paths cannot
escape the configured sandbox root when it IS set.
"""

from __future__ import annotations

import importlib
import os
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_tools() -> Any:
    """Reload ``file_ops`` so ``_FILE_BASE_DIR`` picks up the patched env.

    ``_FILE_BASE_DIR`` is resolved at module import time via
    ``_get_settings()``, which is ``lru_cache``-wrapped.  To pick up a patched
    environment we must both clear the settings cache *and* reload the module.
    """
    from agentic_v2.settings import get_settings

    get_settings.cache_clear()
    import agentic_v2.tools.builtin.file_ops as mod

    importlib.reload(mod)
    return mod


# ---------------------------------------------------------------------------
# Fail-closed tests
# ---------------------------------------------------------------------------


async def test_file_read_fail_closed_when_base_dir_unset(tmp_path):
    """``file_read`` must return an error when AGENTIC_FILE_BASE_DIR is unset."""
    (tmp_path / "secret.txt").write_text("secret content")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGENTIC_FILE_BASE_DIR", None)
        mod = _import_tools()
        tool = mod.FileReadTool()
        result = await tool.execute(str(tmp_path / "secret.txt"))
    assert result.success is False
    assert "AGENTIC_FILE_BASE_DIR" in result.error


async def test_file_write_fail_closed_when_base_dir_unset(tmp_path):
    """``file_write`` must refuse writes when AGENTIC_FILE_BASE_DIR is unset."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGENTIC_FILE_BASE_DIR", None)
        mod = _import_tools()
        tool = mod.FileWriteTool()
        result = await tool.execute(str(tmp_path / "out.txt"), "hello")
    assert result.success is False
    assert "AGENTIC_FILE_BASE_DIR" in result.error


async def test_absolute_path_refused_when_base_dir_unset(tmp_path):
    """Regression: absolute paths like /etc/passwd must be refused when unset.

    This is the explicit regression scenario called out in the ticket — an LLM
    with prompt injection trying to ``file_read('/etc/passwd')`` must get an
    error result rather than silently reading the host filesystem.
    """
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGENTIC_FILE_BASE_DIR", None)
        mod = _import_tools()
        tool = mod.FileReadTool()
        # Use an absolute path that exists on Windows so a latent no-op fix
        # would otherwise succeed.  The exact path doesn't matter — what
        # matters is that validation rejects it before any I/O happens.
        result = await tool.execute("/etc/passwd")
    assert result.success is False
    assert "AGENTIC_FILE_BASE_DIR" in result.error


async def test_file_ops_work_when_base_dir_set(tmp_path):
    """Sanity: tools still succeed when the env var is set to a valid dir."""
    with patch.dict(os.environ, {"AGENTIC_FILE_BASE_DIR": str(tmp_path)}):
        mod = _import_tools()
        tool = mod.FileWriteTool()
        result = await tool.execute(str(tmp_path / "out.txt"), "hello")
    assert result.success is True


# ---------------------------------------------------------------------------
# Path traversal corpus
# ---------------------------------------------------------------------------


_TRAVERSAL_ATTEMPTS = [
    "/etc/passwd",
    "/root/.ssh/id_rsa",
    "../../etc/shadow",
    "../../../windows/system32/cmd.exe",
    "/proc/self/environ",
    "~/.aws/credentials",
]


@pytest.mark.parametrize("bad_path", _TRAVERSAL_ATTEMPTS)
async def test_path_traversal_rejected(tmp_path, bad_path):
    """Every traversal attempt must return ``success=False`` when base is set."""
    with patch.dict(os.environ, {"AGENTIC_FILE_BASE_DIR": str(tmp_path)}):
        mod = _import_tools()
        tool = mod.FileReadTool()
        result = await tool.execute(bad_path)
    assert result.success is False


# ---------------------------------------------------------------------------
# Cleanup: restore module state after the test module finishes so other test
# modules that import file_ops at collection time see a deterministic value.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _restore_file_ops_module():
    """Reload file_ops once more after this module's tests finish."""
    yield
    # Restore whatever the ambient env says (typically unset in CI).
    _import_tools()
