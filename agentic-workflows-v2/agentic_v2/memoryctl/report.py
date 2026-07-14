"""Findings report writer/reader for the weekly LLM pass (design doc §6).

``write_report`` renders a maintain run's findings queue to
``<base>/reports/<YYYY-MM-DD>/findings.jsonl`` (machine handoff for the
weekly consolidation pass, §5.4) plus a human-readable ``report.md``,
where ``<base>`` is ``cfg.fleet_dir`` or the first memory dir. A second
write on the same day overwrites deterministically. ``run`` summarizes
the latest written report and never mutates anything.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from agentic_v2.memoryctl._shared import (
    DATE_FORMAT,
    SEVERITIES,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    CommandResult,
    Finding,
    MemoryctlConfig,
    acquire_lock,
    findings_to_jsonl,
    now_utc,
)

COMMAND_NAME = "report"
WRITE_COMMAND_NAME = "report.write"
CODE_LATEST = "report.latest"
CODE_WRITTEN = "report.written"
CODE_WOULD_WRITE = "report.would-write"
REPORTS_DIR_NAME = "reports"
FINDINGS_FILE_NAME = "findings.jsonl"
REPORT_FILE_NAME = "report.md"
TOP_ERROR_PATHS_LIMIT = 10


def write_report(
    cfg: MemoryctlConfig,
    results: Sequence[CommandResult],
    *,
    dry_run: bool = False,
) -> CommandResult:
    """Write ``findings.jsonl`` + ``report.md`` under ``<base>/reports/<date>/``.

    Locked via :func:`acquire_lock`; with ``dry_run`` the target paths are
    reported and nothing is written.
    """
    base = _report_base(cfg)
    date_str = now_utc().strftime(DATE_FORMAT)
    report_dir = base / REPORTS_DIR_NAME / date_str
    findings_path = report_dir / FINDINGS_FILE_NAME
    report_path = report_dir / REPORT_FILE_NAME
    all_findings = tuple(f for result in results for f in result.findings)
    if dry_run:
        return _would_write_result(findings_path, report_path, len(all_findings))
    base.mkdir(parents=True, exist_ok=True)
    with acquire_lock(cfg, base):
        report_dir.mkdir(parents=True, exist_ok=True)
        findings_path.write_text(findings_to_jsonl(all_findings), encoding="utf-8")
        report_path.write_text(_render_report_md(results, date_str), encoding="utf-8")
    written = Finding(
        code=CODE_WRITTEN,
        severity=SEVERITY_INFO,
        message=f"wrote {len(all_findings)} finding(s) to {report_dir}",
        path=findings_path,
        data={"finding_count": len(all_findings), "report_md": str(report_path)},
    )
    return CommandResult(
        name=WRITE_COMMAND_NAME,
        findings=(written,),
        changed=(findings_path, report_path),
        summary=f"report: wrote {report_dir}",
    )


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Summarize the latest ``reports/<date>/findings.jsonl`` if any exists.

    Read-only: ``dry_run`` is accepted for contract uniformity and changes
    nothing (there is no mutation to suppress).
    """
    del dry_run  # read-only command; parameter kept for the shared contract
    base = _report_base(cfg)
    latest = _latest_findings_file(base)
    if latest is None:
        return CommandResult(
            name=COMMAND_NAME,
            findings=(),
            changed=(),
            summary=f"report: no reports under {base / REPORTS_DIR_NAME}",
        )
    counts = _count_jsonl_severities(latest)
    total = sum(counts.values())
    date_str = latest.parent.name
    finding = Finding(
        code=CODE_LATEST,
        severity=SEVERITY_INFO,
        message=f"latest report {date_str}: {total} finding(s)",
        path=latest,
        data={"date": date_str, "total": total, "counts": counts},
    )
    by_severity = ", ".join(f"{counts[sev]} {sev}" for sev in SEVERITIES)
    return CommandResult(
        name=COMMAND_NAME,
        findings=(finding,),
        changed=(),
        summary=f"report: latest {date_str} — {by_severity}",
    )


def _report_base(cfg: MemoryctlConfig) -> Path:
    """Fleet dir when configured, else the first memory dir (fail fast)."""
    if cfg.fleet_dir is not None:
        return cfg.fleet_dir
    if not cfg.memory_dirs:
        raise ValueError("report requires cfg.fleet_dir or at least one memory dir")
    return cfg.memory_dirs[0]


def _would_write_result(
    findings_path: Path, report_path: Path, finding_count: int
) -> CommandResult:
    """Dry-run result describing what a real write would produce."""
    finding = Finding(
        code=CODE_WOULD_WRITE,
        severity=SEVERITY_INFO,
        message=(
            f"would write {finding_count} finding(s) to "
            f"{findings_path} and {report_path}"
        ),
        path=findings_path,
        data={
            "finding_count": finding_count,
            "findings_jsonl": str(findings_path),
            "report_md": str(report_path),
        },
    )
    return CommandResult(
        name=WRITE_COMMAND_NAME,
        findings=(finding,),
        changed=(),
        summary=f"report (dry-run): would write {findings_path.parent}",
    )


def _render_report_md(results: Sequence[CommandResult], date_str: str) -> str:
    """Deterministic markdown: per-command table, severity counts, error paths."""
    all_findings = [f for result in results for f in result.findings]
    lines = [
        f"# memoryctl report — {date_str}",
        "",
        "## Commands",
        "",
        "| command | findings | errors | warns | infos | changed | summary |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        counts = Counter(f.severity for f in result.findings)
        summary = result.summary.replace("|", "\\|")
        lines.append(
            f"| {result.name} | {len(result.findings)} "
            f"| {counts[SEVERITY_ERROR]} | {counts[SEVERITY_WARN]} "
            f"| {counts[SEVERITY_INFO]} | {len(result.changed)} | {summary} |"
        )
    totals = Counter(f.severity for f in all_findings)
    lines += ["", "## Findings by severity", ""]
    lines += [f"- {sev}: {totals[sev]}" for sev in SEVERITIES]
    lines += ["", "## Top error paths", ""]
    top_paths = _top_error_paths(all_findings)
    if top_paths:
        lines += [f"- {path_str}: {count}" for path_str, count in top_paths]
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _top_error_paths(
    findings: Sequence[Finding], limit: int = TOP_ERROR_PATHS_LIMIT
) -> list[tuple[str, int]]:
    """Paths ranked by error-severity finding count (count desc, path asc)."""
    counter: Counter[str] = Counter(
        str(f.path)
        for f in findings
        if f.severity == SEVERITY_ERROR and f.path is not None
    )
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:limit]


def _latest_findings_file(base: Path) -> Path | None:
    """Newest ``reports/<YYYY-MM-DD>/findings.jsonl`` under ``base``, if any."""
    reports_root = base / REPORTS_DIR_NAME
    if not reports_root.is_dir():
        return None
    dated_dirs = [
        entry
        for entry in reports_root.iterdir()
        if entry.is_dir()
        and _is_report_date(entry.name)
        and (entry / FINDINGS_FILE_NAME).is_file()
    ]
    if not dated_dirs:
        return None
    return max(dated_dirs, key=lambda entry: entry.name) / FINDINGS_FILE_NAME


def _is_report_date(name: str) -> bool:
    """True when ``name`` parses as the report date format (YYYY-MM-DD)."""
    try:
        datetime.strptime(name, DATE_FORMAT)
    except ValueError:
        return False
    return True


def _count_jsonl_severities(path: Path) -> dict[str, int]:
    """Severity counts from a findings JSONL file (malformed lines skipped)."""
    counts = dict.fromkeys(SEVERITIES, 0)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        severity = row.get("severity") if isinstance(row, dict) else None
        if isinstance(severity, str) and severity in counts:
            counts[severity] += 1
    return counts
