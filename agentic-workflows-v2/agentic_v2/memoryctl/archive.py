"""Tombstone moves and run-directory rotation (design doc §6).

Two responsibilities:

1. Topic files whose ``status`` starts with ``superseded-by:`` are moved
   into ``<memory dir>/archive/`` (name collisions get ``-1``, ``-2``, …
   suffixes).
2. Fleet run directories older than ``cfg.retention_days`` (by directory
   mtime) rotate into ``<fleet_dir>/runs/archive/<run-id>/`` — but only
   when their run id is already reduced into ``registry/stats.json``.
   Unreduced runs are never rotated (the design doc forbids destroying
   unreduced learning data); they get an ``archive.unreduced-run``
   warning instead.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from agentic_v2.memoryctl import index_cmd
from agentic_v2.memoryctl._shared import (
    ARCHIVE_DIR_NAME,
    SEVERITY_INFO,
    SEVERITY_WARN,
    STATUS_SUPERSEDED_PREFIX,
    CommandResult,
    Finding,
    MemoryctlConfig,
    acquire_lock,
    discover_memory_files,
    load_memory_doc,
    mtime_dt,
    now_utc,
)
from agentic_v2.memoryctl.stats import RUNS_DIR_NAME, stats_path

COMMAND_NAME = "archive"
MAX_COLLISION_SUFFIX = 1000


def _unique_destination(dest: Path) -> Path:
    """First non-existing variant of ``dest`` (``name``, ``name-1``, …)."""
    if not dest.exists():
        return dest
    for i in range(1, MAX_COLLISION_SUFFIX):
        candidate = dest.with_name(f"{dest.stem}-{i}{dest.suffix}")
        if not candidate.exists():
            return candidate
    msg = f"no free archive name for {dest} after {MAX_COLLISION_SUFFIX} tries"
    raise FileExistsError(msg)


def _superseded_files(cfg: MemoryctlConfig, memory_dir: Path) -> list[Path]:
    """Topic files in ``memory_dir`` whose status marks them superseded."""
    out: list[Path] = []
    for path in discover_memory_files(memory_dir, cfg.index_name):
        status = load_memory_doc(path).meta.get("status")
        if isinstance(status, str) and status.startswith(STATUS_SUPERSEDED_PREFIX):
            out.append(path)
    return out


def _move_finding(code: str, src: Path, dest: Path, *, dry_run: bool) -> Finding:
    verb = "would move" if dry_run else "moved"
    return Finding(
        code=code,
        severity=SEVERITY_INFO,
        message=f"{verb} {src.name} -> {dest}",
        path=src,
        data={"destination": str(dest)},
    )


def _archive_superseded(
    cfg: MemoryctlConfig,
    memory_dir: Path,
    *,
    dry_run: bool,
    findings: list[Finding],
    changed: list[Path],
) -> bool:
    """Move superseded topic files in one memory dir to its archive/.

    Returns True when files were actually moved (never on dry runs), so
    the caller can regenerate the index — the moves leave dangling index
    lines otherwise. Regeneration happens *after* this helper returns:
    ``FileLock`` instances on the same lock file are not reentrant
    across objects, so nesting ``index_cmd``'s lock inside ours would
    deadlock until timeout.
    """
    sources = _superseded_files(cfg, memory_dir)
    if not sources:
        return False
    archive_dir = memory_dir / ARCHIVE_DIR_NAME
    if dry_run:
        for src in sources:
            dest = _unique_destination(archive_dir / src.name)
            findings.append(
                _move_finding("archive.superseded", src, dest, dry_run=True)
            )
        return False
    with acquire_lock(cfg, memory_dir):
        archive_dir.mkdir(parents=True, exist_ok=True)
        for src in sources:
            dest = _unique_destination(archive_dir / src.name)
            src.rename(dest)
            findings.append(
                _move_finding("archive.superseded", src, dest, dry_run=False)
            )
            changed.append(dest)
    return True


def _reduced_run_ids(fleet_dir: Path) -> set[str]:
    """Run ids already reduced into stats.json (empty set when unreadable)."""
    path = stats_path(fleet_dir)
    if not path.is_file():
        return set()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    run_ids = loaded.get("run_ids") if isinstance(loaded, dict) else None
    if not isinstance(run_ids, list):
        return set()
    return {str(r) for r in run_ids}


def _rotation_candidates(
    cfg: MemoryctlConfig,
    fleet_dir: Path,
    findings: list[Finding],
) -> list[Path]:
    """Expired run dirs safe to rotate; warns on expired-but-unreduced runs."""
    runs_dir = fleet_dir / RUNS_DIR_NAME
    if not runs_dir.is_dir():
        return []
    reduced = _reduced_run_ids(fleet_dir)
    cutoff = now_utc() - timedelta(days=cfg.retention_days)
    candidates: list[Path] = []
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir() or run_dir.name == ARCHIVE_DIR_NAME:
            continue
        if mtime_dt(run_dir) >= cutoff:
            continue
        if run_dir.name not in reduced:
            findings.append(
                Finding(
                    code="archive.unreduced-run",
                    severity=SEVERITY_WARN,
                    message=(
                        f"run {run_dir.name} exceeds retention but is not "
                        "reduced into stats.json; leaving in place"
                    ),
                    path=run_dir,
                    data={"run_id": run_dir.name},
                )
            )
            continue
        candidates.append(run_dir)
    return candidates


def _rotate_runs(
    cfg: MemoryctlConfig,
    fleet_dir: Path,
    *,
    dry_run: bool,
    findings: list[Finding],
    changed: list[Path],
) -> None:
    """Rotate expired, reduced run dirs into runs/archive/."""
    candidates = _rotation_candidates(cfg, fleet_dir, findings)
    if not candidates:
        return
    archive_dir = fleet_dir / RUNS_DIR_NAME / ARCHIVE_DIR_NAME
    if dry_run:
        for run_dir in candidates:
            dest = _unique_destination(archive_dir / run_dir.name)
            findings.append(
                _move_finding("archive.rotated", run_dir, dest, dry_run=True)
            )
        return
    with acquire_lock(cfg, fleet_dir):
        archive_dir.mkdir(parents=True, exist_ok=True)
        for run_dir in candidates:
            dest = _unique_destination(archive_dir / run_dir.name)
            run_dir.rename(dest)
            findings.append(
                _move_finding("archive.rotated", run_dir, dest, dry_run=False)
            )
            changed.append(dest)


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Archive superseded topic files and rotate expired fleet runs."""
    findings: list[Finding] = []
    changed: list[Path] = []
    for memory_dir in cfg.memory_dirs:
        if not memory_dir.is_dir():
            continue
        moved = _archive_superseded(
            cfg, memory_dir, dry_run=dry_run, findings=findings, changed=changed
        )
        if moved:
            # Close the dangling-index window in the same command run:
            # the moved files' index lines would otherwise be harvested
            # as bogus topics by the next index pass (PR #205 review).
            index_result = index_cmd.run(replace(cfg, memory_dirs=(memory_dir,)))
            changed.extend(index_result.changed)
            findings.append(
                Finding(
                    code="archive.index-regenerated",
                    severity=SEVERITY_INFO,
                    message=(
                        f"regenerated {cfg.index_name} after archiving "
                        "superseded topic(s)"
                    ),
                    path=memory_dir / cfg.index_name,
                )
            )
    if cfg.fleet_dir is not None and cfg.fleet_dir.is_dir():
        _rotate_runs(
            cfg, cfg.fleet_dir, dry_run=dry_run, findings=findings, changed=changed
        )
    moves = sum(
        1 for f in findings if f.code in ("archive.superseded", "archive.rotated")
    )
    skipped = sum(1 for f in findings if f.code == "archive.unreduced-run")
    verb = "would move" if dry_run else "moved"
    summary = f"{verb} {moves} item(s); {skipped} unreduced run(s) left in place"
    return CommandResult(
        name=COMMAND_NAME,
        findings=tuple(findings),
        changed=tuple(changed),
        summary=summary,
    )
