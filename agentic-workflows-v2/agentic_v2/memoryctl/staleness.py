"""``memoryctl staleness`` — age checks over memory and docs (read-only, TIER_0).

Implements the design doc §6 ``staleness`` row — the automated version of
the "look at doc dates" problem (§1):

- Memory topic file whose ``updated`` frontmatter date is older than
  ``cfg.stale_days`` -> warn ``stale.memory``.
- Semantic memory with ``verify: manual`` that is older than
  ``cfg.stale_days`` -> warn ``stale.unverifiable`` (design §4.1: facts
  that cannot be command-verified are flagged for human review).
- Docs (``cfg.docs_dirs``, recursive ``*.md``): freshness is the last git
  commit date, falling back to file mtime for untracked files (design
  §1/§12 Phase 0) -> older than ``cfg.stale_days`` -> warn ``stale.doc``.

Time and git access go through ``_shared`` module attributes
(``_shared.now_utc``, ``_shared.git_last_commit_date``,
``_shared.mtime_dt``) so tests can monkeypatch them without real repos.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from agentic_v2.memoryctl import _shared
from agentic_v2.memoryctl._shared import (
    DATE_FORMAT,
    SEVERITY_WARN,
    VERIFY_MANUAL,
    CommandResult,
    Finding,
    MemoryctlConfig,
    discover_memory_files,
    load_memory_doc,
)

COMMAND_NAME = "staleness"

CODE_MEMORY = "stale.memory"
CODE_UNVERIFIABLE = "stale.unverifiable"
CODE_DOC = "stale.doc"

SOURCE_GIT = "git"
SOURCE_MTIME = "mtime"

TYPE_META_KEY = "type"
TYPE_SEMANTIC = "semantic"
UPDATED_META_KEY = "updated"
VERIFY_META_KEY = "verify"

OLDEST_SAMPLE_SIZE = 5


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Report memory files and docs older than ``cfg.stale_days``.

    Read-only: ``dry_run`` is accepted for contract uniformity but has no
    effect because this command never mutates files.
    """
    del dry_run  # read-only command; accepted for the shared contract only
    now = _shared.now_utc()
    findings: list[Finding] = []
    for root in cfg.memory_dirs:
        for path in discover_memory_files(root, cfg.index_name):
            findings.extend(_memory_findings(path, now, cfg.stale_days))
    for docs_root in cfg.docs_dirs:
        findings.extend(_doc_findings(docs_root, now, cfg.stale_days))
    return CommandResult(
        name=COMMAND_NAME,
        findings=tuple(findings),
        changed=(),
        summary=_summarize(findings),
    )


def _memory_findings(path: Path, now: datetime, stale_days: int) -> list[Finding]:
    """Staleness findings for one memory topic file."""
    doc = load_memory_doc(path)
    updated = _coerce_date(doc.meta.get(UPDATED_META_KEY))
    if updated is None:
        return []  # missing/unparseable `updated` is `validate`'s finding
    age_days = (now - updated).days
    if age_days <= stale_days:
        return []
    out = [
        Finding(
            code=CODE_MEMORY,
            severity=SEVERITY_WARN,
            message=f"memory not updated in {age_days} days (threshold {stale_days})",
            path=path,
            data={"age_days": age_days},
        )
    ]
    is_semantic = doc.meta.get(TYPE_META_KEY) == TYPE_SEMANTIC
    if is_semantic and doc.meta.get(VERIFY_META_KEY) == VERIFY_MANUAL:
        out.append(
            Finding(
                code=CODE_UNVERIFIABLE,
                severity=SEVERITY_WARN,
                message=(
                    f"manually-verified semantic memory is {age_days} days old; "
                    "needs human review"
                ),
                path=path,
                data={"age_days": age_days},
            )
        )
    return out


def _doc_findings(docs_root: Path, now: datetime, stale_days: int) -> list[Finding]:
    """``stale.doc`` warnings for markdown docs under one docs dir (recursive)."""
    if not docs_root.is_dir():
        return []
    out: list[Finding] = []
    for path in sorted(docs_root.rglob("*.md")):
        git_date = _shared.git_last_commit_date(path)
        mtime = _shared.mtime_dt(path)
        # The OLDER signal wins: an initial import commit must not
        # launder a stale mtime into freshness (recall-first — false
        # positives get verified by the weekly pass; misses rot silently).
        if git_date is not None and git_date <= mtime:
            freshness, source = git_date, SOURCE_GIT
        else:
            freshness, source = mtime, SOURCE_MTIME
        age_days = (now - freshness).days
        if age_days <= stale_days:
            continue
        out.append(
            Finding(
                code=CODE_DOC,
                severity=SEVERITY_WARN,
                message=(
                    f"doc last touched {age_days} days ago per {source} "
                    f"(threshold {stale_days})"
                ),
                path=path,
                data={"age_days": age_days, "source": source},
            )
        )
    return out


def _coerce_date(value: object) -> datetime | None:
    """``value`` as an aware UTC datetime, or None when not coercible.

    YAML gives ``datetime.date`` for unquoted ISO dates and ``str`` for
    quoted ones; both are accepted (dates resolve to midnight UTC).
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.strptime(value, DATE_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _summarize(findings: list[Finding]) -> str:
    """Count plus the ``OLDEST_SAMPLE_SIZE`` oldest stale paths."""
    if not findings:
        return "staleness: 0 stale item(s)"
    ages: dict[Path, int] = {}
    for finding in findings:
        age = finding.data.get("age_days")
        if finding.path is not None and isinstance(age, int):
            ages[finding.path] = max(ages.get(finding.path, 0), age)
    oldest = sorted(ages.items(), key=lambda item: (-item[1], str(item[0])))
    sample = ", ".join(f"{path} ({age}d)" for path, age in oldest[:OLDEST_SAMPLE_SIZE])
    return f"staleness: {len(findings)} stale finding(s); oldest: {sample}"
