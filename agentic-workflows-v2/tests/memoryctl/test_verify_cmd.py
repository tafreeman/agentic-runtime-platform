"""Tests for ``agentic_v2.memoryctl.verify_cmd``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.memoryctl import verify_cmd
from agentic_v2.memoryctl._shared import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    MemoryctlConfig,
    serialize_frontmatter,
)

# Quoted interpreter path so the command survives shell=True on both
# cmd.exe and POSIX shells (portable per-OS "exit 0"/"exit 1" stand-in).
PYTHON = f'"{sys.executable}"'
PASS_COMMAND = f'{PYTHON} -c "import sys; sys.exit(0)"'
FAIL_COMMAND = f"{PYTHON} -c \"import sys; sys.stderr.write('boom'); sys.exit(3)\""
SLEEP_COMMAND = f'{PYTHON} -c "import time; time.sleep(3)"'


def _write_verify_topic(memory_dir: Path, name: str, verify: str | None) -> Path:
    """Write a schema-shaped topic file, optionally with a verify command."""
    meta: dict[str, object] = {
        "name": name,
        "description": f"{name} description",
        "type": "semantic",
        "created": "2026-07-14",
        "updated": "2026-07-14",
        "status": "active",
    }
    if verify is not None:
        meta["verify"] = verify
    path = memory_dir / f"{name}.md"
    path.write_text(serialize_frontmatter(meta, f"body of {name}\n"), encoding="utf-8")
    return path


@pytest.fixture
def verify_cmd_memory_dir(tmp_path: Path) -> Path:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return memory_dir


@pytest.fixture
def verify_cmd_cfg(verify_cmd_memory_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(memory_dirs=(verify_cmd_memory_dir,), verify_timeout_s=30)


def test_pass_fail_and_manual(
    verify_cmd_cfg: MemoryctlConfig, verify_cmd_memory_dir: Path
) -> None:
    pass_path = _write_verify_topic(verify_cmd_memory_dir, "passes", PASS_COMMAND)
    fail_path = _write_verify_topic(verify_cmd_memory_dir, "fails", FAIL_COMMAND)
    _write_verify_topic(verify_cmd_memory_dir, "manual", "manual")
    _write_verify_topic(verify_cmd_memory_dir, "unset", None)

    result = verify_cmd.run(verify_cmd_cfg)

    assert result.name == "verify"
    assert result.changed == ()
    by_code = {f.code: f for f in result.findings}
    assert set(by_code) == {"verify.pass", "verify.fail"}
    assert by_code["verify.pass"].severity == SEVERITY_INFO
    assert by_code["verify.pass"].path == pass_path
    failure = by_code["verify.fail"]
    assert failure.severity == SEVERITY_ERROR
    assert failure.path == fail_path
    assert failure.data["returncode"] == 3
    assert "boom" in str(failure.data["stderr_tail"])
    assert "1 pass" in result.summary
    assert "1 fail" in result.summary
    assert "2 manual/unset" in result.summary


def test_timeout_produces_error_finding(verify_cmd_memory_dir: Path) -> None:
    cfg = MemoryctlConfig(memory_dirs=(verify_cmd_memory_dir,), verify_timeout_s=1)
    _write_verify_topic(verify_cmd_memory_dir, "sleeper", SLEEP_COMMAND)

    result = verify_cmd.run(cfg)

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.code == "verify.timeout"
    assert finding.severity == SEVERITY_ERROR
    assert finding.data["timeout_s"] == 1
    assert "1 timeout" in result.summary


def test_dry_run_lists_commands_and_executes_nothing(
    verify_cmd_cfg: MemoryctlConfig,
    verify_cmd_memory_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_verify_topic(verify_cmd_memory_dir, "passes", PASS_COMMAND)
    _write_verify_topic(verify_cmd_memory_dir, "manual", "manual")

    def _forbid(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry_run must not execute commands")

    monkeypatch.setattr(subprocess, "run", _forbid)
    result = verify_cmd.run(verify_cmd_cfg, dry_run=True)

    assert result.changed == ()
    assert [f.code for f in result.findings] == ["verify.would-run"]
    assert result.findings[0].data["command"] == PASS_COMMAND
    assert "would run 1 command(s)" in result.summary
    assert "1 manual/unset" in result.summary


def test_manual_and_unset_only_yields_no_findings(
    verify_cmd_cfg: MemoryctlConfig, verify_cmd_memory_dir: Path
) -> None:
    _write_verify_topic(verify_cmd_memory_dir, "manual", "manual")
    _write_verify_topic(verify_cmd_memory_dir, "unset", None)

    result = verify_cmd.run(verify_cmd_cfg)

    assert result.findings == ()
    assert "2 manual/unset" in result.summary


def test_stderr_tail_is_capped_at_300_chars(
    verify_cmd_cfg: MemoryctlConfig,
    verify_cmd_memory_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_verify_topic(verify_cmd_memory_dir, "noisy", "noisy-command")

    def _fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0], returncode=2, stdout="", stderr="x" * 1000
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    result = verify_cmd.run(verify_cmd_cfg)

    finding = result.findings[0]
    assert finding.code == "verify.fail"
    assert len(str(finding.data["stderr_tail"])) == 300


def test_index_file_is_never_verified(
    verify_cmd_cfg: MemoryctlConfig, verify_cmd_memory_dir: Path
) -> None:
    index = verify_cmd_memory_dir / verify_cmd_cfg.index_name
    index.write_text("# index\n", encoding="utf-8")

    result = verify_cmd.run(verify_cmd_cfg)

    assert result.findings == ()
    assert "0 manual/unset" in result.summary
