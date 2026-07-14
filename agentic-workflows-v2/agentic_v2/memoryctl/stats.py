"""Reduce fleet episode records into cumulative aggregates (design doc §6).

Reads ``<fleet_dir>/runs/<run-id>/episodes.jsonl`` files and merges their
playbook/model counts into ``<fleet_dir>/registry/stats.json``. Reduction
is idempotent by run id: a run whose id already appears in the stats
file's ``run_ids`` list is never reduced again, so re-running ``stats``
is always safe. Archived runs (``runs/archive/``) are skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agentic_v2.memoryctl._shared import (
    ARCHIVE_DIR_NAME,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    CommandResult,
    Finding,
    MemoryctlConfig,
    acquire_lock,
    now_utc,
)

COMMAND_NAME = "stats"
RUNS_DIR_NAME = "runs"
REGISTRY_DIR_NAME = "registry"
STATS_FILE_NAME = "stats.json"
EPISODES_FILE_NAME = "episodes.jsonl"
OUTCOME_SUCCESS = "success"
JSON_INDENT = 2


@dataclass
class _PlaybookAgg:
    """Mutable accumulator for one playbook's cumulative stats."""

    applied: int = 0
    succeeded: int = 0
    last_applied: str | None = None


@dataclass
class _ModelAgg:
    """Mutable accumulator for one model's cumulative stats."""

    uses: int = 0
    degraded: int = 0


@dataclass
class _StatsState:
    """In-memory view of the cumulative stats file."""

    run_ids: list[str] = field(default_factory=list)
    playbooks: dict[str, _PlaybookAgg] = field(default_factory=dict)
    models: dict[str, _ModelAgg] = field(default_factory=dict)


def stats_path(fleet_dir: Path) -> Path:
    """Location of the cumulative aggregates file under ``fleet_dir``."""
    return fleet_dir / REGISTRY_DIR_NAME / STATS_FILE_NAME


def _coerce_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _load_state(path: Path) -> _StatsState | None:
    """Parse an existing stats file; ``None`` when it exists but is corrupt."""
    if not path.is_file():
        return _StatsState()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(loaded, dict):
        return None
    state = _StatsState()
    raw_run_ids = loaded.get("run_ids")
    if isinstance(raw_run_ids, list):
        state.run_ids = [str(r) for r in raw_run_ids]
    raw_playbooks = loaded.get("playbooks")
    if isinstance(raw_playbooks, dict):
        for name, entry in raw_playbooks.items():
            if not isinstance(entry, dict):
                continue
            last = entry.get("last_applied")
            state.playbooks[str(name)] = _PlaybookAgg(
                applied=_coerce_int(entry.get("applied")),
                succeeded=_coerce_int(entry.get("succeeded")),
                last_applied=last if isinstance(last, str) else None,
            )
    raw_models = loaded.get("models")
    if isinstance(raw_models, dict):
        for name, entry in raw_models.items():
            if not isinstance(entry, dict):
                continue
            state.models[str(name)] = _ModelAgg(
                uses=_coerce_int(entry.get("uses")),
                degraded=_coerce_int(entry.get("degraded")),
            )
    return state


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _max_iso(current: str | None, candidate: str) -> str | None:
    """Later of two ISO timestamps; unparseable candidates are ignored."""
    parsed_candidate = _parse_ts(candidate)
    if parsed_candidate is None:
        return current
    parsed_current = _parse_ts(current) if current is not None else None
    if parsed_current is None or parsed_candidate > parsed_current:
        return candidate
    return current


def _reduce_episode(record: dict[str, object], state: _StatsState) -> None:
    """Fold one episode record into the accumulators."""
    playbook = record.get("playbook")
    if isinstance(playbook, str) and playbook:
        agg = state.playbooks.setdefault(playbook, _PlaybookAgg())
        agg.applied += 1
        if record.get("outcome") == OUTCOME_SUCCESS:
            agg.succeeded += 1
        ts = record.get("ts")
        if isinstance(ts, str):
            agg.last_applied = _max_iso(agg.last_applied, ts)
    model = record.get("model")
    if isinstance(model, str) and model:
        model_agg = state.models.setdefault(model, _ModelAgg())
        model_agg.uses += 1
        if bool(record.get("degraded")):
            model_agg.degraded += 1


def _reduce_run(run_dir: Path, state: _StatsState, findings: list[Finding]) -> int:
    """Reduce one run directory's episodes; returns the episode count."""
    episodes_file = run_dir / EPISODES_FILE_NAME
    if not episodes_file.is_file():
        return 0
    count = 0
    lines = episodes_file.read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = None
        if not isinstance(record, dict):
            findings.append(
                Finding(
                    code="stats.bad-line",
                    severity=SEVERITY_WARN,
                    message=f"skipping malformed episode line {line_no}",
                    path=episodes_file,
                    data={"line": line_no},
                )
            )
            continue
        _reduce_episode(record, state)
        count += 1
    return count


def _new_run_dirs(fleet_dir: Path, known_run_ids: list[str]) -> list[Path]:
    """Unreduced run directories, sorted; skips ``runs/archive/``."""
    runs_dir = fleet_dir / RUNS_DIR_NAME
    if not runs_dir.is_dir():
        return []
    known = set(known_run_ids)
    return [
        p
        for p in sorted(runs_dir.iterdir())
        if p.is_dir() and p.name != ARCHIVE_DIR_NAME and p.name not in known
    ]


def _serialize_state(state: _StatsState) -> str:
    payload: dict[str, object] = {
        "run_ids": state.run_ids,
        "playbooks": {
            name: {
                "applied": agg.applied,
                "succeeded": agg.succeeded,
                "last_applied": agg.last_applied,
            }
            for name, agg in sorted(state.playbooks.items())
        },
        "models": {
            name: {"uses": agg.uses, "degraded": agg.degraded}
            for name, agg in sorted(state.models.items())
        },
        "updated": now_utc().isoformat(),
    }
    return json.dumps(payload, indent=JSON_INDENT, sort_keys=True) + "\n"


def _corrupt_result(path: Path) -> CommandResult:
    finding = Finding(
        code="stats.corrupt",
        severity=SEVERITY_ERROR,
        message="existing stats.json is unreadable; refusing to overwrite it",
        path=path,
    )
    return CommandResult(
        name=COMMAND_NAME,
        findings=(finding,),
        changed=(),
        summary="aborted: corrupt stats.json",
    )


def _reduce(cfg: MemoryctlConfig, fleet_dir: Path, *, dry_run: bool) -> CommandResult:
    """Read, reduce, and (unless dry-run) rewrite the stats file."""
    target = stats_path(fleet_dir)
    state = _load_state(target)
    if state is None:
        return _corrupt_result(target)
    findings: list[Finding] = []
    new_dirs = _new_run_dirs(fleet_dir, state.run_ids)
    for run_dir in new_dirs:
        episode_count = _reduce_run(run_dir, state, findings)
        verb = "would reduce" if dry_run else "reduced"
        findings.append(
            Finding(
                code="stats.reduced",
                severity=SEVERITY_INFO,
                message=f"{verb} run {run_dir.name} ({episode_count} episode(s))",
                path=run_dir,
                data={"run_id": run_dir.name, "episodes": episode_count},
            )
        )
    state.run_ids = [*state.run_ids, *sorted(d.name for d in new_dirs)]
    changed: tuple[Path, ...] = ()
    if new_dirs and not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_serialize_state(state), encoding="utf-8")
        changed = (target,)
    verb = "would reduce" if dry_run else "reduced"
    summary = f"{verb} {len(new_dirs)} new run(s) into {target.name}"
    return CommandResult(
        name=COMMAND_NAME,
        findings=tuple(findings),
        changed=changed,
        summary=summary,
    )


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Reduce unreduced episode records into cumulative aggregates."""
    fleet_dir = cfg.fleet_dir
    if fleet_dir is None or not fleet_dir.is_dir():
        finding = Finding(
            code="stats.no-fleet",
            severity=SEVERITY_INFO,
            message="no fleet directory configured; nothing to reduce",
        )
        return CommandResult(
            name=COMMAND_NAME,
            findings=(finding,),
            changed=(),
            summary="no fleet directory",
        )
    if dry_run:
        return _reduce(cfg, fleet_dir, dry_run=True)
    with acquire_lock(cfg, fleet_dir):
        return _reduce(cfg, fleet_dir, dry_run=False)
