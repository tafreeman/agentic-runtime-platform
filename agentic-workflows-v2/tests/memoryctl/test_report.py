"""Tests for ``agentic_v2.memoryctl.report``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_v2.memoryctl import report
from agentic_v2.memoryctl._shared import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    CommandResult,
    Finding,
    MemoryctlConfig,
    findings_to_jsonl,
)

REPORT_FIXED_NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
REPORT_FIXED_DATE = "2026-07-14"


def _report_finding(code: str, severity: str, path: Path | None = None) -> Finding:
    return Finding(code=code, severity=severity, message=f"{code} message", path=path)


def _report_result(name: str, findings: tuple[Finding, ...]) -> CommandResult:
    return CommandResult(
        name=name, findings=findings, changed=(), summary=f"{name} summary"
    )


@pytest.fixture
def report_fleet_dir(tmp_path: Path) -> Path:
    return tmp_path / "fleet"


@pytest.fixture
def report_cfg(tmp_path: Path, report_fleet_dir: Path) -> MemoryctlConfig:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return MemoryctlConfig(memory_dirs=(memory_dir,), fleet_dir=report_fleet_dir)


@pytest.fixture
def report_frozen_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr("agentic_v2.memoryctl.report.now_utc", lambda: REPORT_FIXED_NOW)
    return REPORT_FIXED_NOW


@pytest.fixture
def report_sample_results(tmp_path: Path) -> list[CommandResult]:
    bad_path = tmp_path / "memory" / "broken.md"
    return [
        _report_result(
            "validate",
            (
                _report_finding("validate.schema", SEVERITY_ERROR, bad_path),
                _report_finding("validate.schema", SEVERITY_ERROR, bad_path),
                _report_finding("validate.ok", SEVERITY_INFO),
            ),
        ),
        _report_result(
            "dedupe",
            (_report_finding("dedupe.exact", SEVERITY_WARN, tmp_path / "a.md"),),
        ),
    ]


def test_write_report_writes_jsonl_and_markdown(
    report_cfg: MemoryctlConfig,
    report_fleet_dir: Path,
    report_frozen_now: datetime,
    report_sample_results: list[CommandResult],
    tmp_path: Path,
) -> None:
    result = report.write_report(report_cfg, report_sample_results)

    report_dir = report_fleet_dir / "reports" / REPORT_FIXED_DATE
    findings_path = report_dir / "findings.jsonl"
    report_path = report_dir / "report.md"
    assert result.name == "report.write"
    assert result.changed == (findings_path, report_path)
    all_findings = tuple(f for r in report_sample_results for f in r.findings)
    assert findings_path.read_text(encoding="utf-8") == findings_to_jsonl(all_findings)
    rendered = report_path.read_text(encoding="utf-8")
    assert f"# memoryctl report — {REPORT_FIXED_DATE}" in rendered
    assert "| validate | 3 | 2 | 0 | 1 | 0 | validate summary |" in rendered
    assert "| dedupe | 1 | 0 | 1 | 0 | 0 | dedupe summary |" in rendered
    assert "- error: 2" in rendered
    assert "- warn: 1" in rendered
    assert "- info: 1" in rendered
    assert f"- {tmp_path / 'memory' / 'broken.md'}: 2" in rendered
    assert result.findings[0].code == "report.written"
    assert result.findings[0].data["finding_count"] == 4


def test_write_report_same_day_overwrites_deterministically(
    report_cfg: MemoryctlConfig,
    report_fleet_dir: Path,
    report_frozen_now: datetime,
    report_sample_results: list[CommandResult],
) -> None:
    first = report.write_report(report_cfg, report_sample_results)
    findings_path, report_path = first.changed
    first_jsonl = findings_path.read_text(encoding="utf-8")
    first_md = report_path.read_text(encoding="utf-8")

    second = report.write_report(report_cfg, report_sample_results)

    assert second.changed == first.changed
    assert findings_path.read_text(encoding="utf-8") == first_jsonl
    assert report_path.read_text(encoding="utf-8") == first_md


def test_write_report_dry_run_writes_nothing(
    report_cfg: MemoryctlConfig,
    report_fleet_dir: Path,
    report_frozen_now: datetime,
    report_sample_results: list[CommandResult],
) -> None:
    result = report.write_report(report_cfg, report_sample_results, dry_run=True)

    assert not report_fleet_dir.exists()
    assert result.changed == ()
    assert [f.code for f in result.findings] == ["report.would-write"]
    assert result.findings[0].data["finding_count"] == 4
    assert "dry-run" in result.summary


def test_write_report_falls_back_to_first_memory_dir(
    tmp_path: Path, report_frozen_now: datetime
) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    cfg = MemoryctlConfig(memory_dirs=(memory_dir,))

    result = report.write_report(cfg, [])

    findings_path = memory_dir / "reports" / REPORT_FIXED_DATE / "findings.jsonl"
    assert findings_path in result.changed
    assert findings_path.read_text(encoding="utf-8") == ""
    rendered = (findings_path.parent / "report.md").read_text(encoding="utf-8")
    assert "- none" in rendered


def test_run_reads_latest_report_only(
    report_cfg: MemoryctlConfig, report_fleet_dir: Path
) -> None:
    reports_root = report_fleet_dir / "reports"
    old_dir = reports_root / "2026-07-01"
    new_dir = reports_root / "2026-07-14"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old_dir.joinpath("findings.jsonl").write_text(
        findings_to_jsonl((_report_finding("x", SEVERITY_INFO),)), encoding="utf-8"
    )
    new_dir.joinpath("findings.jsonl").write_text(
        findings_to_jsonl(
            (
                _report_finding("a", SEVERITY_ERROR),
                _report_finding("b", SEVERITY_ERROR),
                _report_finding("c", SEVERITY_INFO),
            )
        ),
        encoding="utf-8",
    )

    result = report.run(report_cfg)

    assert result.name == "report"
    assert result.changed == ()
    finding = result.findings[0]
    assert finding.code == "report.latest"
    assert finding.data["date"] == "2026-07-14"
    assert finding.data["total"] == 3
    assert finding.data["counts"] == {"info": 1, "warn": 0, "error": 2}
    assert "2026-07-14" in result.summary
    assert "2 error" in result.summary


def test_run_without_reports_returns_empty(report_cfg: MemoryctlConfig) -> None:
    result = report.run(report_cfg)

    assert result.findings == ()
    assert result.changed == ()
    assert "no reports" in result.summary


def test_run_skips_non_date_dirs_and_missing_findings(
    report_cfg: MemoryctlConfig, report_fleet_dir: Path
) -> None:
    reports_root = report_fleet_dir / "reports"
    junk_dir = reports_root / "not-a-date"
    junk_dir.mkdir(parents=True)
    junk_dir.joinpath("findings.jsonl").write_text(
        findings_to_jsonl((_report_finding("x", SEVERITY_ERROR),)), encoding="utf-8"
    )
    # Newer date dir without a findings.jsonl must also be skipped.
    (reports_root / "2026-07-20").mkdir()
    valid_dir = reports_root / "2026-07-14"
    valid_dir.mkdir()
    valid_dir.joinpath("findings.jsonl").write_text(
        findings_to_jsonl((_report_finding("y", SEVERITY_WARN),)), encoding="utf-8"
    )

    result = report.run(report_cfg)

    assert result.findings[0].data["date"] == "2026-07-14"
    assert result.findings[0].data["counts"] == {"info": 0, "warn": 1, "error": 0}


def test_run_skips_malformed_jsonl_lines(
    report_cfg: MemoryctlConfig, report_fleet_dir: Path
) -> None:
    report_dir = report_fleet_dir / "reports" / "2026-07-14"
    report_dir.mkdir(parents=True)
    valid_line = findings_to_jsonl((_report_finding("ok", SEVERITY_INFO),))
    report_dir.joinpath("findings.jsonl").write_text(
        "not json\n" + valid_line + "\n[1, 2]\n", encoding="utf-8"
    )

    result = report.run(report_cfg)

    assert result.findings[0].data["total"] == 1
    assert result.findings[0].data["counts"] == {"info": 1, "warn": 0, "error": 0}


def test_report_base_requires_a_directory() -> None:
    cfg = MemoryctlConfig(memory_dirs=())

    with pytest.raises(ValueError, match="fleet_dir or at least one memory dir"):
        report.run(cfg)
