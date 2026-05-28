"""Artifact extractor — writes FILE blocks from step outputs to disk.

After a workflow completes, each step output value is scanned for
``FILE: path`` / ``ENDFILE`` sentinel blocks (the same format used by
the coder/generator agents).  Every block is written out to:

    artifacts/<run_id>/<file_path>

Only the *final* version of each path is kept — if multiple steps emit
the same file (e.g. after a rework round) the last one wins, matching
the ``coalesce`` logic used in workflow outputs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path, PurePosixPath
from typing import Any

from ..contracts import WorkflowResult

logger = logging.getLogger(__name__)

_DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parents[3] / "artifacts"

# Matches:  FILE: some/path/file.ext\n<content>\nENDFILE
_FILE_BLOCK_RE = re.compile(
    r"^FILE:\s*(?P<path>[^\r\n]+)\r?\n(?P<content>.*?)^ENDFILE\s*$",
    re.MULTILINE | re.DOTALL,
)


def _collect_strings(value: Any) -> list[str]:
    """Recursively collect all string leaf values from a nested structure."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for v in value.values():
            out.extend(_collect_strings(v))
        return out
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(_collect_strings(v))
        return out
    return []


def _safe_rel_path(raw: str) -> Path | None:
    """Convert a raw FILE: path to a safe relative Path, blocking traversal."""
    # Normalise to posix then resolve relative parts
    clean = raw.strip().replace("\\", "/").lstrip("/")
    try:
        parts = PurePosixPath(clean).parts
    except Exception:
        return None
    # Drop any .. components
    safe_parts = [p for p in parts if p != ".."]
    if not safe_parts:
        return None
    return Path(*safe_parts)


def _scan_output_for_files(output: Any) -> dict[Path, str]:
    """Return {relative_path: content} for every FILE block found in output."""
    files: dict[Path, str] = {}
    for blob in _collect_strings(output):
        for match in _FILE_BLOCK_RE.finditer(blob):
            rel = _safe_rel_path(match.group("path"))
            if rel is None:
                logger.debug("Skipping unsafe path: %s", match.group("path"))
                continue
            files[rel] = match.group("content")
    return files


def _write_files(run_dir: Path, files: dict[Path, str]) -> None:
    """Write extracted files to the run output directory."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        dest = run_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def extract_from_record(
    record: dict[str, Any],
    artifacts_dir: Path | None = None,
) -> Path | None:
    """Extract FILE blocks from a raw run-log dict (as loaded from JSON).

    This is the low-level entry point used by scripts and the backfill path.
    ``extract_artifacts`` delegates to this after converting WorkflowResult.
    """
    run_id = record.get("run_id", "unknown")
    run_dir = (artifacts_dir or _DEFAULT_ARTIFACTS_DIR) / run_id
    files: dict[Path, str] = {}

    for step in record.get("steps", []):
        if step.get("status") not in ("success", "skipped"):
            continue
        files.update(_scan_output_for_files(step.get("output") or {}))

    if not files:
        logger.debug("No FILE blocks found in run %s", run_id)
        return None

    _write_files(run_dir, files)
    logger.info("Extracted %d file(s) to %s", len(files), run_dir)
    return run_dir


def extract_artifacts(
    result: WorkflowResult,
    artifacts_dir: Path | None = None,
) -> Path | None:
    """Extract FILE blocks from a completed WorkflowResult to disk.

    Converts the result to a plain dict and delegates to
    ``extract_from_record`` so the extraction logic lives in one place.
    """
    if not result.steps:
        return None

    record: dict[str, Any] = {
        "run_id": result.workflow_id,
        "steps": [
            {
                "status": (
                    s.status.value if hasattr(s.status, "value") else str(s.status)
                ),
                "output": s.output_data or {},
            }
            for s in result.steps
        ],
    }
    return extract_from_record(record, artifacts_dir=artifacts_dir)
