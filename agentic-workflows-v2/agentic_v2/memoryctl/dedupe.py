"""Exact-duplicate detection over topic memory files (read-only).

Design doc §6 ``dedupe --exact``: hash the normalized bodies (lowercased,
whitespace-collapsed) of topic files *within each memory dir*; equal hashes
are exact duplicates (``warn``). Equal normalized descriptions are flagged
``info``. Semantic/near-duplicate detection is explicitly out of scope —
the weekly LLM queue handles it (§5.4). This command never mutates files.
"""

from __future__ import annotations

import hashlib
from itertools import combinations
from pathlib import Path

from agentic_v2.memoryctl._shared import (
    SEVERITY_INFO,
    SEVERITY_WARN,
    CommandResult,
    Finding,
    MemoryctlConfig,
    discover_memory_files,
    load_memory_doc,
)

COMMAND_NAME = "dedupe"
CODE_EXACT = "dedupe.exact"
CODE_DESCRIPTION = "dedupe.description"


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Report exact body duplicates and duplicate descriptions per memory dir.

    Read-only: ``dry_run`` is accepted for contract uniformity and changes
    nothing (there is no mutation to suppress).
    """
    del dry_run  # read-only command; parameter kept for the shared contract
    findings: list[Finding] = []
    for memory_dir in cfg.memory_dirs:
        findings.extend(_dedupe_dir(memory_dir, cfg.index_name))
    exact = sum(1 for f in findings if f.code == CODE_EXACT)
    desc = sum(1 for f in findings if f.code == CODE_DESCRIPTION)
    summary = (
        f"dedupe: {exact} exact duplicate pair(s), "
        f"{desc} duplicate description pair(s) "
        f"across {len(cfg.memory_dirs)} dir(s)"
    )
    return CommandResult(
        name=COMMAND_NAME, findings=tuple(findings), changed=(), summary=summary
    )


def normalize_text(text: str) -> str:
    """Lowercase ``text`` and collapse every whitespace run to one space."""
    return " ".join(text.lower().split())


def _dedupe_dir(memory_dir: Path, index_name: str) -> list[Finding]:
    """Findings for one memory dir: exact body pairs + description pairs.

    Empty normalized bodies/descriptions are skipped — an empty body is a
    ``validate`` concern, not a duplicate.
    """
    body_groups: dict[str, list[Path]] = {}
    desc_groups: dict[str, list[Path]] = {}
    for path in discover_memory_files(memory_dir, index_name):
        doc = load_memory_doc(path)
        normalized_body = normalize_text(doc.body)
        if normalized_body:
            digest = hashlib.sha256(normalized_body.encode("utf-8")).hexdigest()
            body_groups.setdefault(digest, []).append(path)
        description = doc.meta.get("description")
        if description is not None:
            normalized_desc = normalize_text(str(description))
            if normalized_desc:
                desc_groups.setdefault(normalized_desc, []).append(path)
    findings = _pair_findings(
        body_groups, code=CODE_EXACT, severity=SEVERITY_WARN, label="exact duplicate"
    )
    findings.extend(
        _pair_findings(
            desc_groups,
            code=CODE_DESCRIPTION,
            severity=SEVERITY_INFO,
            label="duplicate description",
        )
    )
    return findings


def _pair_findings(
    groups: dict[str, list[Path]], *, code: str, severity: str, label: str
) -> list[Finding]:
    """One finding per pair inside each group of >=2 paths (deterministic)."""
    findings: list[Finding] = []
    for paths in groups.values():
        for first, second in combinations(paths, 2):
            findings.append(
                Finding(
                    code=code,
                    severity=severity,
                    message=f"{label}: {first.name} == {second.name}",
                    path=first,
                    data={"a": str(first), "b": str(second)},
                )
            )
    return findings
