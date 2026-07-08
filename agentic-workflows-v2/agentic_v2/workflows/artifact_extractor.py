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
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ..contracts import WorkflowResult

logger = logging.getLogger(__name__)

_DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parents[3] / "artifacts"

# Matches:  FILE: some/path/file.ext\n<content>\nENDFILE
_FILE_BLOCK_RE = re.compile(
    r"^FILE:\s*(?P<path>[^\r\n]+)\r?\n(?P<content>.*?)^ENDFILE\s*$",
    re.MULTILINE | re.DOTALL,
)

# Maximum blob length before applying DOTALL regex on untrusted LLM strings.
# A missing ENDFILE sentinel causes catastrophic backtracking without this guard.
_MAX_BLOB_LEN = 262144  # 256 KB


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
    """Convert a raw FILE: path to a safe relative Path, blocking traversal.

    Rejects any path that is absolute under *either* POSIX or Windows rules — a
    drive (``C:``) or UNC anchor (``//server/share``) as well as a POSIX root
    (leading ``/``). Joining an absolute path onto ``run_dir`` silently discards
    ``run_dir`` (``Path("/run") / "/etc/passwd" == Path("/etc/passwd")``, and a
    Windows drive letter escapes the sandbox the same way), so such payloads must
    never survive. Only genuinely relative paths pass; ``..`` segments are then
    dropped so relative traversal stays contained under ``run_dir``.
    """
    # Normalise separators first, but do NOT strip a leading slash yet — the
    # absoluteness checks below must see the anchor before it is removed.
    normalized = raw.strip().replace("\\", "/")
    if not normalized:
        return None
    # A Windows drive/UNC anchor (``C:``, ``//server/share``) escapes run_dir.
    windows_view = PureWindowsPath(normalized)
    if windows_view.drive or windows_view.root:
        return None
    # A POSIX-absolute path (leading ``/``, including UNC ``//``) does too.
    if normalized.startswith("/"):
        return None
    try:
        parts = PurePosixPath(normalized).parts
    except Exception:
        return None
    # Drop any .. components (relative traversal stays contained under run_dir).
    safe_parts = [p for p in parts if p != ".."]
    if not safe_parts:
        return None
    for part in safe_parts:
        # A colon in a component can only be a Windows drive anchor (``D:``) or
        # an NTFS alternate-data-stream (``name:stream``). On Windows,
        # ``Path("foo", "D:", "x")`` re-derives ``D:`` as the drive and silently
        # drops ``foo``, re-absolutising a path that looked relative. Colons
        # never appear in a legitimate source path, so reject the whole payload
        # — this also catches ``..:ads``, which the exact-``..`` filter misses.
        if ":" in part:
            return None
        # Dot-only names (``...``) and control/NUL bytes are OS-invalid and would
        # otherwise raise mid-write; reject them here so extraction stays on the
        # skip-and-log path instead of aborting the batch.
        if set(part) <= {"."} or any(ord(ch) < 32 for ch in part):
            return None
    rel = Path(*safe_parts)
    # Belt-and-suspenders: the rebuilt path must carry no drive/UNC/root anchor
    # (a Windows drive can re-materialise from a mid-path segment) and must not
    # be absolute under either convention.
    if PureWindowsPath(rel).drive or PureWindowsPath(rel).root or rel.is_absolute():
        return None
    return rel


def _scan_output_for_files(output: Any) -> dict[Path, str]:
    """Return {relative_path: content} for every FILE block found in output."""
    files: dict[Path, str] = {}
    for blob in _collect_strings(output):
        # Guard against ReDoS on untrusted LLM blobs that lack a closing ENDFILE.
        if len(blob) > _MAX_BLOB_LEN:
            blob = blob[:_MAX_BLOB_LEN]
        for match in _FILE_BLOCK_RE.finditer(blob):
            rel = _safe_rel_path(match.group("path"))
            if rel is None:
                logger.debug("Skipping unsafe path: %s", match.group("path"))
                continue
            files[rel] = match.group("content")
    return files


def _write_files(run_dir: Path, files: dict[Path, str]) -> None:
    """Write extracted files to the run output directory.

    Defense-in-depth: every destination is re-verified to resolve *inside*
    ``run_dir`` before writing, so any path that slips past
    :func:`_safe_rel_path` still cannot escape the sandbox — it is skipped and
    logged instead of written.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    run_dir_resolved = run_dir.resolve()
    for rel, content in files.items():
        dest = run_dir / rel
        try:
            # ``dest.resolve()`` can raise OSError on an OS-invalid name (NUL
            # byte, reserved device, malformed stream). Treat that as a rejected
            # path, not a fatal error, so one bad block cannot abort the whole
            # batch and suppress every other artifact in the run.
            resolved = dest.resolve()
            if not resolved.is_relative_to(run_dir_resolved):
                logger.warning("Skipping path escaping run dir: %s", rel)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping unwritable artifact path %s: %s", rel, exc)
            continue


def extract_from_record(
    record: dict[str, Any],
    artifacts_dir: Path | None = None,
) -> Path | None:
    """Extract FILE blocks from a raw run-log dict (as loaded from JSON).

    This is the low-level entry point used by scripts and the backfill path.
    ``extract_artifacts`` delegates to this after converting WorkflowResult.

    ``run_id`` is validated against the artifacts root: ``_safe_rel_path`` only
    guards each FILE path *under* ``run_dir``, so a ``..``-bearing ``run_id``
    would relocate ``run_dir`` itself outside the sandbox (the per-file
    containment check in :func:`_write_files` resolves against ``run_dir`` and
    is blind to that). Such a record is refused.
    """
    artifacts_root = artifacts_dir or _DEFAULT_ARTIFACTS_DIR
    run_id = str(record.get("run_id") or "unknown")
    run_dir = artifacts_root / run_id
    if not run_dir.resolve().is_relative_to(artifacts_root.resolve()):
        logger.error("Refusing extraction: run_id %r escapes artifacts root", run_id)
        return None
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
