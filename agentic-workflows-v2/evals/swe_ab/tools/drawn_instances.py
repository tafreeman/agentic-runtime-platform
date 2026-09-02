"""Instance ids the campaign has already drawn, read from evidence git tracks.

``build_swebench_cases.py`` keeps waves from overlapping by skipping any
instance that already has a case directory under ``dataset/swebench_cases/``.
That directory is gitignored, so on a fresh checkout -- or after the cache is
cleared -- it is empty, and the next wave would quietly re-draw the first
instances of every pool: instances earlier waves already graded. The tracked
wave manifests (``dataset/cases.swebench*.jsonl``) and reports
(``reports/*.json``) record the same ids durably; this module reads them so
the exclusion set survives the machine that built the case trees.

Malformed JSON is deliberately not swallowed: a manifest or report that cannot
be read is a problem to surface, not a reason to draw from a smaller
exclusion set.
"""

from __future__ import annotations

import json
from pathlib import Path


def _ids_from_manifest(path: Path) -> set[str]:
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        metadata = row.get("metadata") or {}
        for candidate in (row.get("sample_id"), metadata.get("instance_id")):
            if candidate:
                ids.add(str(candidate))
    return ids


def _ids_from_report(path: Path) -> set[str]:
    ids: set[str] = set()
    report = json.loads(path.read_text(encoding="utf-8"))
    for sample in report.get("samples") or []:
        inner = sample.get("sample") or {}
        metadata = inner.get("metadata") or {}
        execution = sample.get("execution") or {}
        for candidate in (
            inner.get("sample_id"),
            metadata.get("instance_id"),
            execution.get("sample_id"),
        ):
            if candidate:
                ids.add(str(candidate))
    return ids


def previously_drawn_instance_ids(kit_root: Path) -> set[str]:
    """Every instance id any tracked SWE-bench manifest or report has used.

    ``dataset/cases.jsonl`` and ``cases.memoryctl.jsonl`` (mutation cases) are
    not matched: their ids are not SWE-bench instances and cannot collide.
    """
    ids: set[str] = set()
    dataset = kit_root / "dataset"
    if dataset.is_dir():
        for manifest in sorted(dataset.glob("cases.swebench*.jsonl")):
            ids |= _ids_from_manifest(manifest)
    reports = kit_root / "reports"
    if reports.is_dir():
        for report in sorted(reports.glob("*.json")):
            ids |= _ids_from_report(report)
    return ids
