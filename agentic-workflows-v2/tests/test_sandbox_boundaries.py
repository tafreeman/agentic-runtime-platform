"""Regression tests for the code-exec / shell / file-base sandbox boundaries."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.governance.approval import AutoApproveProvider, set_approval_provider
from agentic_v2.langchain import tools as lc_tools
from agentic_v2.tools.builtin.code_analysis import CodeAnalysisTool
from agentic_v2.tools.builtin.code_execution import CodeExecutionTool
from agentic_v2.tools.builtin.search_ops import GrepTool, SearchTool


@pytest.fixture(autouse=True)
def _approve_all():
    set_approval_provider(AutoApproveProvider())
    try:
        yield
    finally:
        set_approval_provider(None)


def _clear_settings_cache() -> None:
    from agentic_v2 import settings as settings_module

    settings_module.get_settings.cache_clear()


@pytest.fixture
def file_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENTIC_FILE_BASE_DIR", str(tmp_path))
    _clear_settings_cache()
    yield tmp_path
    _clear_settings_cache()


@pytest.fixture
def no_file_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTIC_FILE_BASE_DIR", raising=False)
    _clear_settings_cache()
    yield
    _clear_settings_cache()


# ---------------------------------------------------------------------------
# code_execution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        'from os import system; system("id")',
        "import os",
        "from posix import system",
        "import sys",
        "import io",
        "import builtins",
        "from pathlib import Path",
        "import os.path",
    ],
)
def test_filesystem_and_process_modules_are_blocked(code: str) -> None:
    assert CodeExecutionTool(sandbox=True)._check_code_safety(code) is not None


@pytest.mark.asyncio
async def test_runtime_import_of_os_is_blocked() -> None:
    """The in-child constrained __import__ also rejects os."""
    code = "import importlib\nm = importlib.import_module"  # pre-flight pattern hit
    result = await CodeExecutionTool(sandbox=True).execute(code=code)
    assert not result.success


@pytest.mark.asyncio
async def test_timeout_kills_and_reaps_child(monkeypatch: pytest.MonkeyPatch) -> None:
    procs: list[Any] = []
    real = asyncio.create_subprocess_exec

    async def _spy(*args: Any, **kwargs: Any) -> Any:
        proc = await real(*args, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spy)
    result = await CodeExecutionTool(sandbox=True).execute(
        code="while True:\n    pass\n", timeout=1.0
    )

    assert not result.success
    assert "timed out" in (result.error or "")
    assert len(procs) == 1
    assert procs[0].returncode is not None  # reaped, not left running


# ---------------------------------------------------------------------------
# langchain/tools.py: fail-closed file base
# ---------------------------------------------------------------------------


def test_outside_file_base_fails_closed_when_unset(no_file_base: None) -> None:
    err = lc_tools._outside_file_base("/etc/passwd")
    assert err is not None
    assert err.startswith("ERROR")
    assert "AGENTIC_FILE_BASE_DIR" in err


def test_file_tools_denied_when_base_unset(tmp_path: Path, no_file_base: None) -> None:
    target = tmp_path / "x.txt"
    target.write_text("secret", encoding="utf-8")

    assert "AGENTIC_FILE_BASE_DIR" in lc_tools.file_read.invoke({"path": str(target)})
    out = lc_tools.file_write.invoke({"path": str(tmp_path / "w.txt"), "content": "x"})
    assert "AGENTIC_FILE_BASE_DIR" in out
    assert not (tmp_path / "w.txt").exists()
    assert lc_tools.file_list.invoke({"directory": str(tmp_path)}).startswith("ERROR")


def test_file_read_inside_base_still_works(file_base: Path) -> None:
    (file_base / "a.txt").write_text("hello", encoding="utf-8")
    assert lc_tools.file_read.invoke({"path": str(file_base / "a.txt")}) == "hello"


# ---------------------------------------------------------------------------
# langchain/tools.py: shell_run policy + env
# ---------------------------------------------------------------------------


def test_shell_run_disabled_without_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTIC_SHELL_ALLOWED_COMMANDS", raising=False)
    out = lc_tools.shell_run.invoke({"command": "python --version"})
    assert out.startswith("ERROR")
    assert "disabled" in out


def test_shell_run_rejects_command_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_SHELL_ALLOWED_COMMANDS", "python")
    out = lc_tools.shell_run.invoke({"command": "whoami"})
    assert out.startswith("ERROR")
    assert "allowlist" in out


def test_shell_run_rejects_shell_metacharacters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_SHELL_ALLOWED_COMMANDS", "python")
    out = lc_tools.shell_run.invoke({"command": "python --version | cat"})
    assert out.startswith("ERROR")
    assert "metacharacters" in out


def test_shell_run_child_does_not_inherit_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "probe.py"
    script.write_text(
        "import os\nprint('LEAK=' + str(os.environ.get('OPENAI_API_KEY')))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTIC_SHELL_ALLOWED_COMMANDS", Path(sys.executable).stem)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")

    out = lc_tools.shell_run.invoke(
        {"command": f'{Path(sys.executable).stem} "{script}"'.replace('"', "")}
    )

    assert "LEAK=None" in out
    assert "sk-should-not-leak" not in out


# ---------------------------------------------------------------------------
# GrepTool case sensitivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grep_case_sensitive_true_is_honoured(tmp_path: Path) -> None:
    f = tmp_path / "t.txt"
    f.write_text("Token\ntoken\nTOKEN\n", encoding="utf-8")

    sensitive = await GrepTool().execute(
        pattern="token", path=str(f), case_sensitive=True
    )
    insensitive = await GrepTool().execute(pattern="token", path=str(f))

    assert [m["text"] for m in sensitive.data["matches"]] == ["token"]
    assert len(insensitive.data["matches"]) == 3


@pytest.mark.asyncio
async def test_search_regex_default_stays_case_insensitive(tmp_path: Path) -> None:
    f = tmp_path / "t.txt"
    f.write_text("Token\ntoken\n", encoding="utf-8")
    result = await SearchTool().execute(pattern="TOKEN", path=str(f), mode="regex")
    assert len(result.data["matches"]) == 2


# ---------------------------------------------------------------------------
# CodeAnalysisTool from_file containment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_analysis_from_file_fails_closed_without_base(
    tmp_path: Path, no_file_base: None
) -> None:
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    result = await CodeAnalysisTool().execute(source=str(f), from_file=True)
    assert not result.success
    assert "AGENTIC_FILE_BASE_DIR" in (result.error or "")


@pytest.mark.asyncio
async def test_code_analysis_from_file_rejects_outside_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("AGENTIC_FILE_BASE_DIR", str(base))
    _clear_settings_cache()
    try:
        result = await CodeAnalysisTool().execute(source=str(outside), from_file=True)
    finally:
        _clear_settings_cache()
    assert not result.success


@pytest.mark.asyncio
async def test_code_analysis_from_file_inside_base_works(file_base: Path) -> None:
    f = file_base / "m.py"
    f.write_text("def a():\n    pass\n", encoding="utf-8")
    result = await CodeAnalysisTool().execute(source=str(f), from_file=True)
    assert result.success
