"""Lay reworked code artifacts over the originals, file by file.

A rework step usually returns only the files it changed. Taking the
reworked artifact wholesale would drop every untouched file from the
shipped code, so the tier-0 ``tier0_overlay`` step merges instead: original
files stay, reworked files replace them by path, and new files are added.

Both engines' ``tier0_overlay`` handlers call :func:`overlay_code_artifacts`
so the merge rule cannot drift between the native DAG executor and the
LangGraph adapter.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from .artifact_contracts import validate_code_artifact

logger = logging.getLogger(__name__)


def _as_file_map(value: Any) -> dict[str, str] | None:
    """Return *value* as a ``{path: source}`` map, or None if it is not one."""
    if isinstance(value, Mapping):
        if value and all(
            isinstance(path, str) and isinstance(source, str)
            for path, source in value.items()
        ):
            return dict(value)
        return None
    if isinstance(value, str):
        # Imported lazily: a module-level import would cycle through
        # agentic_v2.engine.__init__ -> engine.agent_resolver -> this module.
        from agentic_v2.engine.llm_output_parsing import extract_files_from_artifact

        return extract_files_from_artifact(value.strip()) or None
    return None


def overlay_code_artifact(base: Any, override: Any) -> tuple[Any, bool]:
    """Overlay one reworked artifact on its original.

    Returns ``(artifact, applied)``. ``applied`` is False, and *base* comes
    back unchanged, when *override* is absent or fails the ``code_artifact``
    contract (unsafe paths, placeholder prose, no files, or a FILE/ENDFILE
    string with commentary or a truncated block around its files) — malformed
    output is never partially shipped. When *base* is not itself a file map
    (some generators return nested descriptions), the reworked file map is
    the only code-shaped version and is returned as-is.
    """
    if override is None:
        return base, False
    # Validate the value as given, before extraction: the lenient FILE-block
    # extractor would drop commentary or a truncated trailing block and let
    # the rest through.
    diagnostics = validate_code_artifact("override", override)
    override_files = None if diagnostics else _as_file_map(override)
    if override_files is None:
        logger.warning(
            "Ignoring reworked artifact of type %s that fails the "
            "code_artifact contract: %s",
            type(override).__name__,
            [item.code for item in diagnostics],
        )
        return base, False
    base_files = _as_file_map(base)
    if base_files is None:
        return override_files, True
    return {**base_files, **override_files}, True


def overlay_code_artifacts(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Overlay every artifact slot in *override* on the same slot in *base*.

    Returns the merged slots (every slot of either mapping) and the
    names of the slots a reworked artifact was actually applied to, in
    slot order.
    """
    merged: dict[str, Any] = {}
    overridden: list[str] = []
    for slot in dict.fromkeys([*base, *override]):
        merged[slot], applied = overlay_code_artifact(
            base.get(slot), override.get(slot)
        )
        if applied:
            overridden.append(slot)
    return merged, overridden
