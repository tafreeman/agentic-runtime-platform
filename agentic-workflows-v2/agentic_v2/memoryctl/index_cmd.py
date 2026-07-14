"""Harvest-then-regenerate the MEMORY.md index (``memoryctl index``).

Design doc section 3 (load-bearing): Claude Code's native auto-memory
writes MEMORY.md directly during sessions without memoryctl's advisory
lock, so regeneration must never blind-overwrite. Index lines that are
not derived from existing topic files are harvested into a single
topic file per run first; only then is the index rebuilt
deterministically from topic-file frontmatter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from agentic_v2.memoryctl._shared import (
    ARCHIVE_DIR_NAME,
    DATE_FORMAT,
    SEVERITY_INFO,
    SEVERITY_WARN,
    STATUS_ACTIVE,
    VERIFY_MANUAL,
    CommandResult,
    Finding,
    MemoryctlConfig,
    acquire_lock,
    discover_memory_files,
    load_memory_doc,
    now_utc,
    serialize_frontmatter,
)

COMMAND_NAME = "index"
INDEX_HEADER = "# Memory Index"
HARVEST_NOTE = "**Why:** harvested from MEMORY.md by memoryctl index"
HARVEST_DAY_FORMAT = "%Y%m%d"
DESCRIPTION_MAX_CHARS = 200
TYPE_SEMANTIC = "semantic"
SUBTYPE_PROJECT = "project"

_LIST_LINE_RE = re.compile(r"^-\s+\[[^\]]*\]\(([^)]+)\)")


@dataclass(frozen=True)
class _IndexEntry:
    """Source data for one regenerated index line."""

    name: str
    file_name: str
    description: str
    updated: str


@dataclass(frozen=True)
class _HarvestPlan:
    """The unindexed lines and the single topic file they become."""

    path: Path
    lines: tuple[str, ...]
    content: str


@dataclass(frozen=True)
class _DirPlan:
    """Everything ``index`` would write for one memory directory."""

    index_path: Path
    harvests: tuple[_HarvestPlan, ...]
    entries: tuple[_IndexEntry, ...]
    index_content: str


def _format_updated(value: object) -> str:
    """Frontmatter ``updated`` value rendered as a YYYY-MM-DD string."""
    if isinstance(value, date):
        return value.strftime(DATE_FORMAT)
    if value is None:
        return ""
    return str(value)


def _harvest_candidates(index_path: Path, topic_names: frozenset[str]) -> list[str]:
    """Index lines not derived from existing topic files.

    A line survives (is *not* harvested) only when it is blank, a
    header, or a ``- [text](target.md) ...`` list entry whose target
    exists as a topic file — or existed and was moved to ``archive/``
    (an archived target's line is intentionally dropped on regeneration,
    not harvested back into a bogus topic file). Everything else was
    written by another writer and must be preserved as a topic file
    before regeneration.
    """
    if not index_path.is_file():
        return []
    archive_dir = index_path.parent / ARCHIVE_DIR_NAME
    archived_names = frozenset(p.name for p in archive_dir.glob("*.md"))
    candidates: list[str] = []
    for raw_line in index_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LIST_LINE_RE.match(line)
        if match is not None:
            name = Path(match.group(1)).name
            if name in topic_names or name in archived_names:
                continue
        candidates.append(line)
    return candidates


def _harvest_description(lines: tuple[str, ...], today_iso: str) -> str:
    """Index/description text for one run's harvested-content file."""
    text = (
        f"Unindexed MEMORY.md content harvested {today_iso} "
        f"({len(lines)} line(s)) — split during consolidation"
    )
    return text[:DESCRIPTION_MAX_CHARS]


def _harvest_doc_text(path: Path, lines: tuple[str, ...], today_iso: str) -> str:
    """Full file text for the harvested topic file with valid frontmatter."""
    meta: dict[str, object] = {
        "name": path.stem,
        "description": _harvest_description(lines, today_iso),
        "type": TYPE_SEMANTIC,
        "subtype": SUBTYPE_PROJECT,
        "created": today_iso,
        "updated": today_iso,
        "status": STATUS_ACTIVE,
        "verify": VERIFY_MANUAL,
    }
    body = "\n" + "\n".join(lines) + f"\n\n{HARVEST_NOTE}\n"
    return serialize_frontmatter(meta, body)


def _plan_harvests(
    target_dir: Path, candidates: list[str], day: str, today_iso: str
) -> tuple[_HarvestPlan, ...]:
    """Plan at most ONE harvest file holding every unindexed line.

    One file per run, not per line: a rich hand-written index must not
    be shredded into dozens of one-line fragments — the weekly
    consolidation pass splits the preserved document with full context.
    """
    if not candidates:
        return ()
    path = target_dir / f"harvested-{day}.md"
    suffix = 2
    while path.exists():
        path = target_dir / f"harvested-{day}-{suffix}.md"
        suffix += 1
    lines = tuple(candidates)
    return (
        _HarvestPlan(
            path=path, lines=lines, content=_harvest_doc_text(path, lines, today_iso)
        ),
    )


def _entries_from_files(paths: list[Path]) -> list[_IndexEntry]:
    """Index entries built from existing topic files' frontmatter."""
    entries: list[_IndexEntry] = []
    for path in paths:
        doc = load_memory_doc(path)
        entries.append(
            _IndexEntry(
                name=str(doc.meta.get("name") or path.stem),
                file_name=path.name,
                description=str(doc.meta.get("description") or ""),
                updated=_format_updated(doc.meta.get("updated")),
            )
        )
    return entries


def _render_index(entries: tuple[_IndexEntry, ...]) -> str:
    """Deterministic index text: header, blank line, name-sorted entries."""
    lines = [INDEX_HEADER, ""]
    for e in sorted(entries, key=lambda entry: entry.name):
        lines.append(
            f"- [{e.name}]({e.file_name}) — {e.description} (updated {e.updated})"
        )
    return "\n".join(lines) + "\n"


def _plan_dir(cfg: MemoryctlConfig, target_dir: Path) -> _DirPlan:
    """Compute (without writing) the full harvest + regeneration plan."""
    index_path = target_dir / cfg.index_name
    topic_files = discover_memory_files(target_dir, cfg.index_name)
    topic_names = frozenset(p.name for p in topic_files)
    candidates = _harvest_candidates(index_path, topic_names)
    today = now_utc().date()
    today_iso = today.isoformat()
    harvests = _plan_harvests(
        target_dir, candidates, today.strftime(HARVEST_DAY_FORMAT), today_iso
    )
    entries = _entries_from_files(topic_files) + [
        _IndexEntry(
            name=h.path.stem,
            file_name=h.path.name,
            description=_harvest_description(h.lines, today_iso),
            updated=today_iso,
        )
        for h in harvests
    ]
    return _DirPlan(
        index_path=index_path,
        harvests=harvests,
        entries=tuple(entries),
        index_content=_render_index(tuple(entries)),
    )


def _write_plan(plan: _DirPlan) -> tuple[Path, ...]:
    """Write harvested topic files then the regenerated index."""
    for harvest in plan.harvests:
        harvest.path.write_text(harvest.content, encoding="utf-8")
    plan.index_path.write_text(plan.index_content, encoding="utf-8")
    return tuple(h.path for h in plan.harvests) + (plan.index_path,)


def _plan_findings(
    plan: _DirPlan, cfg: MemoryctlConfig, *, dry_run: bool
) -> list[Finding]:
    """Findings describing one directory's harvest/regenerate plan."""
    findings: list[Finding] = []
    for harvest in plan.harvests:
        findings.append(
            Finding(
                code="index.harvested",
                severity=SEVERITY_INFO,
                message=(
                    f"harvested {len(harvest.lines)} unindexed line(s) "
                    f"into {harvest.path.name}"
                ),
                path=harvest.path,
                data={"lines": list(harvest.lines), "source": str(plan.index_path)},
            )
        )
    if len(plan.entries) > cfg.index_soft_cap:
        findings.append(
            Finding(
                code="index.over-soft-cap",
                severity=SEVERITY_WARN,
                message=(
                    f"index has {len(plan.entries)} entries "
                    f"(soft cap {cfg.index_soft_cap})"
                ),
                path=plan.index_path,
                data={"entries": len(plan.entries), "soft_cap": cfg.index_soft_cap},
            )
        )
    if dry_run:
        would_write = [str(h.path) for h in plan.harvests] + [str(plan.index_path)]
        findings.append(
            Finding(
                code="index.dry-run",
                severity=SEVERITY_INFO,
                message=f"dry run: would write {len(would_write)} file(s)",
                path=plan.index_path,
                data={"would_write": would_write},
            )
        )
    return findings


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Harvest unindexed MEMORY.md lines, then regenerate each index.

    With ``dry_run`` everything is computed but nothing is written:
    ``changed`` is empty and would-write paths are reported in the
    ``index.dry-run`` finding's data. All writes happen inside the
    advisory :func:`acquire_lock` for the target directory.
    """
    findings: list[Finding] = []
    changed: list[Path] = []
    entry_total = 0
    harvest_total = 0
    for memory_dir in cfg.memory_dirs:
        if not memory_dir.is_dir():
            findings.append(
                Finding(
                    code="index.missing-dir",
                    severity=SEVERITY_WARN,
                    message=f"memory dir does not exist: {memory_dir}",
                    path=memory_dir,
                )
            )
            continue
        if dry_run:
            plan = _plan_dir(cfg, memory_dir)
        else:
            with acquire_lock(cfg, memory_dir):
                plan = _plan_dir(cfg, memory_dir)
                changed.extend(_write_plan(plan))
        findings.extend(_plan_findings(plan, cfg, dry_run=dry_run))
        entry_total += len(plan.entries)
        harvest_total += sum(len(h.lines) for h in plan.harvests)
    return CommandResult(
        name=COMMAND_NAME,
        findings=tuple(findings),
        changed=tuple(changed),
        summary=(
            f"{len(cfg.memory_dirs)} dirs, {entry_total} entries, "
            f"{harvest_total} harvested"
        ),
    )
