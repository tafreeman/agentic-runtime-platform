"""Shared contract for memoryctl command modules.

Every command module in this package exposes::

    def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult

Command modules never mutate files when ``dry_run`` is true, and they
acquire the advisory file lock (:func:`acquire_lock`) before any
mutation. The lock only coordinates memoryctl-vs-memoryctl; Claude
Code's native auto-memory writes without it, which is why index
regeneration must harvest unknown index lines instead of
blind-overwriting (design doc §3).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml
from filelock import FileLock

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_ERROR = "error"
SEVERITIES = (SEVERITY_INFO, SEVERITY_WARN, SEVERITY_ERROR)

VALID_TYPES = ("semantic", "episodic", "procedural-proposal")
VALID_SUBTYPES = ("user", "project", "feedback", "reference")
REQUIRED_META_KEYS = ("name", "description", "type", "created", "updated", "status")
DATE_FORMAT = "%Y-%m-%d"
STATUS_ACTIVE = "active"
STATUS_SUPERSEDED_PREFIX = "superseded-by:"
VERIFY_MANUAL = "manual"

FRONTMATTER_FENCE = "---"
ARCHIVE_DIR_NAME = "archive"
DEFAULT_INDEX_NAME = "MEMORY.md"
LOCK_FILE_NAME = ".memoryctl.lock"

GIT_DATE_TIMEOUT_S = 10


@dataclass(frozen=True)
class Finding:
    """One machine-readable maintenance finding."""

    code: str
    severity: str
    message: str
    path: Path | None = None
    data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandResult:
    """Uniform result returned by every command module's ``run``."""

    name: str
    findings: tuple[Finding, ...]
    changed: tuple[Path, ...]
    summary: str


@dataclass(frozen=True)
class MemoryDoc:
    """A parsed memory/playbook markdown file."""

    path: Path
    meta: dict[str, object]
    body: str
    raw: str


@dataclass(frozen=True)
class MemoryctlConfig:
    """Paths and budgets for one memoryctl invocation."""

    memory_dirs: tuple[Path, ...]
    docs_dirs: tuple[Path, ...] = ()
    fleet_dir: Path | None = None
    index_name: str = DEFAULT_INDEX_NAME
    topic_line_cap: int = 150
    index_soft_cap: int = 150
    stale_days: int = 90
    retention_days: int = 90
    verify_timeout_s: int = 60
    lock_timeout_s: float = 30.0


def now_utc() -> datetime:
    """Current UTC time (single seam for tests to monkeypatch)."""
    return datetime.now(tz=UTC)


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Split ``text`` into (frontmatter mapping, body).

    Returns ``({}, text)`` when no valid frontmatter fence pair is
    present or the YAML block is not a mapping.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return {}, text
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER_FENCE:
            block = "".join(lines[1:i])
            body = "".join(lines[i + 1 :])
            try:
                loaded = yaml.safe_load(block)
            except yaml.YAMLError:
                return {}, text
            if not isinstance(loaded, dict):
                return {}, text
            return {str(k): v for k, v in loaded.items()}, body
    return {}, text


def serialize_frontmatter(meta: dict[str, object], body: str) -> str:
    """Render a memory file back to text with a YAML frontmatter block."""
    block = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"{FRONTMATTER_FENCE}\n{block}{FRONTMATTER_FENCE}\n{body}"


def load_memory_doc(path: Path) -> MemoryDoc:
    """Load and parse one markdown memory file."""
    raw = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    return MemoryDoc(path=path, meta=meta, body=body, raw=raw)


def discover_memory_files(root: Path, index_name: str = DEFAULT_INDEX_NAME) -> list[Path]:
    """Topic files under ``root``: ``*.md`` minus the index and archive/."""
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.glob("*.md")):
        if p.name == index_name:
            continue
        out.append(p)
    return out


def findings_to_jsonl(findings: tuple[Finding, ...] | list[Finding]) -> str:
    """Serialize findings as JSONL (one finding per line, sorted keys)."""
    rows: list[str] = []
    for f in findings:
        rows.append(
            json.dumps(
                {
                    "code": f.code,
                    "severity": f.severity,
                    "message": f.message,
                    "path": str(f.path) if f.path is not None else None,
                    "data": f.data,
                },
                sort_keys=True,
                default=str,
            )
        )
    return "\n".join(rows) + ("\n" if rows else "")


def acquire_lock(cfg: MemoryctlConfig, target_dir: Path) -> FileLock:
    """Advisory lock guarding memoryctl mutations under ``target_dir``.

    Only coordinates memoryctl processes with each other; other writers
    (Claude Code sessions) do not take this lock.
    """
    return FileLock(str(target_dir / LOCK_FILE_NAME), timeout=cfg.lock_timeout_s)


def git_last_commit_date(path: Path) -> datetime | None:
    """Last git commit date for ``path``, or None if untracked/no repo.

    Falls back to None (callers then use :func:`mtime_dt`) — the design
    doc requires mtime fallback because most target files are untracked.
    """
    cmd = ["git", "log", "-1", "--format=%cI", "--", path.name]
    try:
        proc = subprocess.run(  # fixed argv, no shell, trusted binary
            cmd,
            cwd=path.parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_DATE_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    stamp = proc.stdout.strip()
    if proc.returncode != 0 or not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def mtime_dt(path: Path) -> datetime:
    """File modification time as an aware UTC datetime."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
