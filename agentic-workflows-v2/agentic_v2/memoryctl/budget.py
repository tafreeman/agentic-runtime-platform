"""``memoryctl budget`` — line/byte cap enforcement (read-only, TIER_0).

Detects budget violations per design doc §6 (``budget`` row) and §9:

- Topic file over ``cfg.topic_line_cap`` lines -> warn ``budget.topic-over``.
- Index over ``cfg.index_soft_cap`` lines -> warn ``budget.index-soft``.
- Index over the Claude Code load cap — 200 lines or 25KB (design §3) ->
  error ``budget.index-hard``. The hard error supersedes the soft warning
  for the same index, so each index yields at most one finding.

Detection only: splitting or compressing oversized files is the weekly
LLM pass's job (design §5.4).
"""

from __future__ import annotations

from pathlib import Path

from agentic_v2.memoryctl._shared import (
    SEVERITY_ERROR,
    SEVERITY_WARN,
    CommandResult,
    Finding,
    MemoryctlConfig,
    discover_memory_files,
)

COMMAND_NAME = "budget"

CODE_TOPIC_OVER = "budget.topic-over"
CODE_INDEX_SOFT = "budget.index-soft"
CODE_INDEX_HARD = "budget.index-hard"

# Claude Code loads only the first 200 lines / 25KB of MEMORY.md
# (design doc §3, tier 1). Anything past that cap is silently invisible.
INDEX_HARD_LINE_CAP = 200
INDEX_HARD_BYTE_CAP = 25_600


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Report topic files and indexes that exceed their budgets.

    Read-only: ``dry_run`` is accepted for contract uniformity but has no
    effect because this command never mutates files.
    """
    del dry_run  # read-only command; accepted for the shared contract only
    findings: list[Finding] = []
    files_checked = 0
    for root in cfg.memory_dirs:
        for path in discover_memory_files(root, cfg.index_name):
            files_checked += 1
            findings.extend(_topic_findings(path, cfg.topic_line_cap))
        index_path = root / cfg.index_name
        if index_path.is_file():
            files_checked += 1
            findings.extend(_index_findings(index_path, cfg.index_soft_cap))
    summary = (
        f"budget: checked {files_checked} file(s); "
        f"{len(findings)} over-budget finding(s)"
    )
    return CommandResult(
        name=COMMAND_NAME, findings=tuple(findings), changed=(), summary=summary
    )


def _count_lines(path: Path) -> int:
    """Number of lines in ``path`` (UTF-8)."""
    return len(path.read_text(encoding="utf-8").splitlines())


def _topic_findings(path: Path, line_cap: int) -> list[Finding]:
    """``budget.topic-over`` warning when a topic file exceeds the line cap."""
    lines = _count_lines(path)
    if lines <= line_cap:
        return []
    return [
        Finding(
            code=CODE_TOPIC_OVER,
            severity=SEVERITY_WARN,
            message=f"topic file has {lines} lines (cap {line_cap})",
            path=path,
            data={"lines": lines},
        )
    ]


def _index_findings(path: Path, soft_cap: int) -> list[Finding]:
    """Hard-cap error or soft-cap warning for one index file.

    The hard finding (Claude Code load cap: >200 lines or >25KB)
    supersedes the soft one — at most one finding per index.
    """
    lines = _count_lines(path)
    size_bytes = path.stat().st_size
    if lines > INDEX_HARD_LINE_CAP or size_bytes > INDEX_HARD_BYTE_CAP:
        return [
            Finding(
                code=CODE_INDEX_HARD,
                severity=SEVERITY_ERROR,
                message=(
                    f"index exceeds the Claude Code load cap: {lines} lines, "
                    f"{size_bytes} bytes (caps {INDEX_HARD_LINE_CAP} lines / "
                    f"{INDEX_HARD_BYTE_CAP} bytes)"
                ),
                path=path,
                data={"lines": lines, "bytes": size_bytes},
            )
        ]
    if lines > soft_cap:
        return [
            Finding(
                code=CODE_INDEX_SOFT,
                severity=SEVERITY_WARN,
                message=f"index has {lines} lines (soft cap {soft_cap})",
                path=path,
                data={"lines": lines},
            )
        ]
    return []
