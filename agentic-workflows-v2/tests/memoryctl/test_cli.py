"""Tests for the ``memoryctl`` typer CLI, including maintain end-to-end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentic_v2.memoryctl import _shared
from agentic_v2.memoryctl.cli import app

runner = CliRunner()

RECENT_DATE = "2026-07-13"


def _write_topic(path: Path, name: str, status: str = "active") -> None:
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: durable fact {name}\n"
        "type: semantic\n"
        "subtype: project\n"
        f"created: {RECENT_DATE}\n"
        f"updated: {RECENT_DATE}\n"
        f'status: "{status}"\n'
        "verify: manual\n"
        "---\n"
        f"Body of {name}. No links here.\n",
        encoding="utf-8",
    )


@pytest.fixture
def cli_memory_dir(tmp_path: Path) -> Path:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_topic(memory_dir / "npm-over-npx.md", "npm-over-npx")
    _write_topic(memory_dir / "pnpm-eperm-fallback.md", "pnpm-eperm-fallback")
    return memory_dir


@pytest.fixture
def cli_fleet_dir(tmp_path: Path) -> Path:
    fleet = tmp_path / "fleet"
    run_dir = fleet / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "episodes.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-07-12T00:00:00Z",
                "playbook": "pb-cli",
                "model": "model-cli",
                "degraded": False,
                "outcome": "success",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return fleet


@pytest.fixture
def cli_no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep staleness off real git; mtime fallback is deterministic here."""
    monkeypatch.setattr(_shared, "git_last_commit_date", lambda _path: None)


def test_cli_stats_reduces_and_exits_zero(
    cli_memory_dir: Path, cli_fleet_dir: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "--memory-dir",
            str(cli_memory_dir),
            "--fleet-dir",
            str(cli_fleet_dir),
            "stats",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (cli_fleet_dir / "registry" / "stats.json").is_file()


def test_cli_missing_memory_dir_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["--memory-dir", str(tmp_path / "does-not-exist"), "stats"]
    )

    assert result.exit_code == 2


def test_cli_missing_fleet_dir_exits_two(cli_memory_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--memory-dir",
            str(cli_memory_dir),
            "--fleet-dir",
            str(tmp_path / "no-fleet"),
            "stats",
        ],
    )

    assert result.exit_code == 2


def test_cli_error_findings_exit_one(cli_memory_dir: Path, cli_fleet_dir: Path) -> None:
    registry = cli_fleet_dir / "registry"
    registry.mkdir()
    (registry / "stats.json").write_text("{corrupt", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--memory-dir",
            str(cli_memory_dir),
            "--fleet-dir",
            str(cli_fleet_dir),
            "stats",
        ],
    )

    assert result.exit_code == 1


def test_cli_archive_json_emits_parseable_jsonl(cli_memory_dir: Path) -> None:
    _write_topic(
        cli_memory_dir / "stale-fact.md",
        "stale-fact",
        status="superseded-by:[[npm-over-npx]]",
    )

    result = runner.invoke(
        app, ["--memory-dir", str(cli_memory_dir), "--json", "archive"]
    )

    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "expected at least one JSONL finding"
    parsed = [json.loads(line) for line in lines]
    assert any(row["code"] == "archive.superseded" for row in parsed)


@pytest.mark.usefixtures("cli_no_git")
def test_cli_maintain_end_to_end(cli_memory_dir: Path, cli_fleet_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--memory-dir",
            str(cli_memory_dir),
            "--fleet-dir",
            str(cli_fleet_dir),
            "maintain",
        ],
    )

    assert result.exit_code == 0, result.output
    # index regenerated, stats reduced, report written — the nightly set ran.
    assert (cli_memory_dir / "MEMORY.md").is_file()
    stats_file = cli_fleet_dir / "registry" / "stats.json"
    assert stats_file.is_file()
    data = json.loads(stats_file.read_text(encoding="utf-8"))
    assert data["run_ids"] == ["run-1"]
    reports_dir = cli_fleet_dir / "reports"
    report_days = list(reports_dir.iterdir())
    assert len(report_days) == 1
    assert (report_days[0] / "findings.jsonl").is_file()
    assert (report_days[0] / "report.md").is_file()


@pytest.mark.usefixtures("cli_no_git")
def test_cli_maintain_dry_run_writes_nothing(
    cli_memory_dir: Path, cli_fleet_dir: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "--memory-dir",
            str(cli_memory_dir),
            "--fleet-dir",
            str(cli_fleet_dir),
            "--dry-run",
            "maintain",
        ],
    )

    assert result.exit_code == 0, result.output
    assert not (cli_memory_dir / "MEMORY.md").exists()
    assert not (cli_fleet_dir / "registry" / "stats.json").exists()
    assert not (cli_fleet_dir / "reports").exists()


@pytest.mark.usefixtures("cli_no_git")
def test_cli_maintain_json_output_is_parseable(
    cli_memory_dir: Path, cli_fleet_dir: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "--memory-dir",
            str(cli_memory_dir),
            "--fleet-dir",
            str(cli_fleet_dir),
            "--json",
            "maintain",
        ],
    )

    assert result.exit_code == 0, result.output
    for line in result.stdout.splitlines():
        if line.strip():
            row = json.loads(line)
            assert {"code", "severity", "message"} <= row.keys()
