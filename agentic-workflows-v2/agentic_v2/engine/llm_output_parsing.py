"""LLM output parsing — JSON extraction, normalization, and sentinel artifact parsing.

Provides robust fallback strategies for turning raw LLM text into structured
dicts:

1. :func:`extract_json_candidates` — generate increasingly permissive JSON
   candidate strings from raw model output.
2. :func:`normalize_expected_structure` — coerce variant reviewer shapes into
   canonical ``{"review_report": {"overall_status": "<STATUS>"}}`` form.
3. :func:`parse_llm_json_output` — full JSON parse with fallback to raw-text
   salvage for review-report gating.
4. :func:`extract_files_from_artifact` — extract ``{path: content}`` maps from
   FILE/ENDFILE blocks inside sentinel artifact content.
5. :func:`parse_sentinel_output` — parse the full ``<<<ARTIFACT key>>>`` sentinel
   format produced by coder/reviewer persona prompts.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Sentinel regex constants (shared with tool_execution.py callers)
# ---------------------------------------------------------------------------

ARTIFACT_RE = re.compile(
    r"<<<ARTIFACT\s+(\w+)>>>(.*?)<<<ENDARTIFACT>>>",
    re.DOTALL,
)
FILE_BLOCK_RE = re.compile(
    r"^FILE:\s*(.+?)\n(.*?)^ENDFILE\s*$",
    re.DOTALL | re.MULTILINE,
)

# Maximum input length before applying DOTALL regexes on untrusted LLM output.
# Missing closing sentinels cause backtracking; capping input bounds the runtime.
_MAX_SENTINEL_INPUT_LEN = 262144  # 256 KB

# Backward-compatibility aliases
_ARTIFACT_RE = ARTIFACT_RE
_FILE_BLOCK_RE = FILE_BLOCK_RE


# ---------------------------------------------------------------------------
# JSON candidate generation
# ---------------------------------------------------------------------------


def _strip_outer_fence(raw: str) -> str | None:
    """Strip the outer markdown fence lines (first and last ```), if present.

    Does NOT remove embedded backtick lines inside JSON string values. Returns
    the fence-stripped text, or ``None`` when *raw* is not fenced/empty.
    """
    if not raw.startswith("```"):
        return None
    lines = raw.splitlines()
    start = 1  # skip opening ```json / ``` line
    end = len(lines)
    # Only strip trailing fence if the last non-empty line is a fence marker
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            if lines[i].strip().startswith("```"):
                end = i
            break
    fenced = "\n".join(lines[start:end]).strip()
    return fenced or None


def _bracket_span(raw: str, open_ch: str, close_ch: str) -> str | None:
    """Return the substring spanning the first open to last close bracket."""
    first = raw.find(open_ch)
    last = raw.rfind(close_ch)
    if first != -1 and last > first:
        snippet = raw[first : last + 1].strip()
        if snippet:
            return snippet
    return None


def extract_json_candidates(text: str) -> list[str]:
    """Return increasingly permissive JSON candidates from model output.

    Tries, in order: raw text, markdown-fence-stripped text (outer fence only),
    bracket-span extraction for objects (``{…}``), and bracket-span for arrays
    (``[…]``). Duplicates are removed while preserving priority order.
    """
    candidates: list[str] = []
    raw = text.strip()
    if raw:
        candidates.append(raw)

    fenced = _strip_outer_fence(raw)
    if fenced:
        candidates.append(fenced)

    # Extract first likely JSON object/array by bracket span
    obj_snippet = _bracket_span(raw, "{", "}")
    if obj_snippet:
        candidates.append(obj_snippet)

    arr_snippet = _bracket_span(raw, "[", "]")
    if arr_snippet:
        candidates.append(arr_snippet)

    # Deduplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


# Backward-compatibility alias
_extract_json_candidates = extract_json_candidates


# ---------------------------------------------------------------------------
# Structure normalization
# ---------------------------------------------------------------------------


def _recover_nested_review_report(raw_response: str) -> dict[str, Any] | None:
    """Recover a nested review_report payload from a raw_response JSON blob.

    Some model responses come wrapped as::

        {"raw_response": "```json { \"review_report\": {...} } ```"}

    Returns the recovered report dict, or ``None`` when none is found.
    """
    for candidate in extract_json_candidates(raw_response):
        try:
            nested_parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(nested_parsed, dict):
            continue
        if isinstance(nested_parsed.get("review_report"), dict):
            return nested_parsed["review_report"]
        if isinstance(nested_parsed.get("review"), dict):
            return nested_parsed["review"]
        if isinstance(nested_parsed.get("overall_status"), str):
            return {"overall_status": nested_parsed["overall_status"]}
    return None


def _review_report_from_raw_text(raw_text: str) -> dict[str, Any]:
    """Build a review_report by salvaging status from free-form raw text."""
    from ..contracts import ReviewStatus

    status_match = re.search(
        r'"?overall_status"?\s*[:=]\s*"?([A-Za-z_\-]+)"?',
        raw_text,
        flags=re.IGNORECASE,
    )
    approved_match = re.search(
        r'"?approved"?\s*[:=]\s*(true|false)',
        raw_text,
        flags=re.IGNORECASE,
    )

    if status_match:
        raw_status = status_match.group(1).strip()
    elif approved_match:
        raw_status = (
            "APPROVED"
            if approved_match.group(1).lower() == "true"
            else "NEEDS_FIXES"
        )
    else:
        raw_status = None  # normalize() defaults to NEEDS_FIXES

    return {"overall_status": ReviewStatus.normalize(raw_status).value}


def _finalize_review_report_status(
    parsed: dict[str, Any], rr: dict[str, Any]
) -> None:
    """Ensure rr has a normalized overall_status, promoting top-level if needed."""
    from ..contracts import ReviewStatus

    top_level_status = parsed.get("overall_status")
    if isinstance(top_level_status, str) and "overall_status" not in rr:
        rr["overall_status"] = top_level_status

    if "overall_status" not in rr:
        approved = rr.get("approved")
        raw_status = "APPROVED" if approved is True else None
        rr["overall_status"] = ReviewStatus.normalize(raw_status).value
    else:
        # Normalize whatever value is already present
        rr["overall_status"] = ReviewStatus.normalize(rr["overall_status"]).value


def _normalize_review_report_key(parsed: dict[str, Any]) -> None:
    """Coerce variant reviewer shapes into a canonical review_report dict."""
    rr = parsed.get("review_report")
    if not isinstance(rr, dict) and isinstance(parsed.get("review"), dict):
        rr = parsed.get("review")
        parsed["review_report"] = rr

    # Recover nested reviewer payload so when-conditions can resolve.
    if not isinstance(rr, dict) and isinstance(parsed.get("raw_response"), str):
        nested_report = _recover_nested_review_report(str(parsed.get("raw_response")))
        if nested_report is not None:
            rr = nested_report
            parsed["review_report"] = rr

    if not isinstance(rr, dict):
        rr = _review_report_from_raw_text(str(parsed.get("raw_response", "")))
        parsed["review_report"] = rr

    if isinstance(rr, dict):
        _finalize_review_report_status(parsed, rr)
        parsed["review_report"] = rr


def _promote_missing_keys_from_raw(
    parsed: dict[str, Any], expected_output_keys: list[str]
) -> None:
    """Promote expected keys nested inside raw_response to the top level.

    When the parsed dict only has ``raw_response`` (the outer parse succeeded
    but all content is inside a nested JSON blob), try to extract the expected
    keys from that nested JSON.
    """
    missing_keys = [
        k
        for k in expected_output_keys
        if k not in parsed and k != "raw_response"
    ]
    if not (missing_keys and isinstance(parsed.get("raw_response"), str)):
        return

    nested_raw = str(parsed["raw_response"])
    for candidate in extract_json_candidates(nested_raw):
        try:
            nested_parsed = json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
        if not isinstance(nested_parsed, dict):
            continue
        # Only promote keys the caller expects — don't stomp existing keys
        promoted = False
        for key in missing_keys:
            if key in nested_parsed and key not in parsed:
                parsed[key] = nested_parsed[key]
                promoted = True
        if promoted:
            break


def normalize_expected_structure(
    parsed: dict[str, Any],
    expected_output_keys: list[str] | None,
) -> dict[str, Any]:
    """Normalize parsed LLM output to match expected workflow output keys.

    Primary focus is ``review_report`` normalization: LLM reviewer outputs
    arrive in many variant shapes (``review``, ``raw_response``, nested JSON,
    ``approved`` boolean, etc.).  This function coerces all variants into a
    canonical ``{"review_report": {"overall_status": "<STATUS>"}}`` structure
    using :meth:`ReviewStatus.normalize` so that downstream ``when``-conditions
    can reliably gate on approval status.
    """
    if not expected_output_keys:
        return parsed

    # Normalize legacy/variant reviewer output into review_report.
    if "review_report" in expected_output_keys:
        _normalize_review_report_key(parsed)

    # General recovery: promote expected keys nested inside raw_response.
    _promote_missing_keys_from_raw(parsed, expected_output_keys)

    return parsed


# Backward-compatibility alias
_normalize_expected_structure = normalize_expected_structure


def _salvage_expected_keys_from_jsonish(
    response: str,
    expected_output_keys: list[str] | None,
) -> dict[str, Any]:
    """Best-effort extraction of expected top-level keys from malformed JSON.

    When the model output is nearly JSON but truncated/malformed, full
    ``json.loads`` can fail and downstream steps receive only ``raw_response``.
    This helper scans for ``"<key>":`` anchors and uses ``raw_decode`` to
    parse each individual value independently.

    Returns only keys that were successfully decoded.
    """
    if not expected_output_keys:
        return {}

    decoder = json.JSONDecoder(strict=False)
    salvaged: dict[str, Any] = {}

    for key in expected_output_keys:
        key_pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*')
        for match in key_pattern.finditer(response):
            value_start = match.end()
            while value_start < len(response) and response[value_start].isspace():
                value_start += 1
            try:
                value, _ = decoder.raw_decode(response, idx=value_start)
                salvaged[key] = value
                break
            except json.JSONDecodeError:
                continue

    return salvaged


# ---------------------------------------------------------------------------
# JSON output parsing
# ---------------------------------------------------------------------------


def parse_llm_json_output(
    response: str,
    expected_output_keys: list[str] | None,
) -> dict[str, Any]:
    """Parse model text output into a JSON dict with robust fallbacks.

    Attempts each candidate from :func:`extract_json_candidates`.  If all
    fail, returns ``{"raw_response": response}`` with a best-effort
    ``review_report`` salvaged from raw text (if expected).

    Uses ``strict=False`` so that literal control characters (including bare
    newlines) inside JSON string values — a common LLM output quirk — are
    tolerated rather than causing a parse failure.
    """
    for candidate in extract_json_candidates(response):
        try:
            parsed = json.loads(candidate, strict=False)
            if isinstance(parsed, dict):
                return normalize_expected_structure(parsed, expected_output_keys)
        except json.JSONDecodeError:
            continue

    fallback: dict[str, Any] = {"raw_response": response}

    # Try to salvage expected non-review keys (e.g., api_spec/db_schema)
    # from JSON-like responses that are malformed/truncated.
    fallback.update(_salvage_expected_keys_from_jsonish(response, expected_output_keys))

    if not (expected_output_keys and "review_report" in expected_output_keys):
        return fallback

    # This step expects review_report but the model returned malformed JSON —
    # salvage status from raw text so when-conditions still work.
    fallback["review_report"] = _salvage_review_report_from_text(response)
    return fallback


def _salvage_review_report_from_text(response: str) -> dict[str, Any]:
    """Salvage a review_report dict from malformed/truncated model text.

    Conservative default: if approval cannot be proven, force the rework path.
    """
    status_match = re.search(
        r'"?overall_status"?\s*[:=]\s*"?([A-Za-z_\-]+)"?',
        response,
        flags=re.IGNORECASE,
    )
    approved_match = re.search(
        r'"?approved"?\s*[:=]\s*(true|false)',
        response,
        flags=re.IGNORECASE,
    )

    if status_match:
        raw_status = status_match.group(1).strip()
        normalized = raw_status.upper().replace(" ", "_")
        return {"overall_status": normalized}
    if approved_match:
        is_approved = approved_match.group(1).lower() == "true"
        return {"overall_status": "APPROVED" if is_approved else "NEEDS_FIXES"}
    return {"overall_status": "NEEDS_FIXES"}


# Backward-compatibility alias
_parse_llm_json_output = parse_llm_json_output


# ---------------------------------------------------------------------------
# Sentinel artifact parsing
# ---------------------------------------------------------------------------


def extract_files_from_artifact(content: str) -> dict[str, str]:
    """Return ``{path: content}`` for every FILE/ENDFILE block in *content*.

    Supports the R4 one-file-per-path model: callers can iterate over
    individual files rather than treating the artifact as a single blob.
    Returns an empty dict when no FILE blocks are present.
    """
    # Guard against ReDoS: cap input length before applying DOTALL regexes
    # on untrusted LLM content (missing ENDFILE sentinel triggers backtracking).
    if len(content) > _MAX_SENTINEL_INPUT_LEN:
        content = content[:_MAX_SENTINEL_INPUT_LEN]
    return {
        match.group(1).strip(): match.group(2)
        for match in FILE_BLOCK_RE.finditer(content)
    }


# Backward-compatibility alias
_extract_files_from_artifact = extract_files_from_artifact


def parse_sentinel_output(
    text: str,
    expected_output_keys: list[str] | None,
) -> dict[str, Any] | None:
    """Parse the sentinel artifact format produced by coder.md prompts.

    Looks for blocks of the form::

        <<<ARTIFACT key>>>
        FILE: path/to/file.py
        content
        ENDFILE
        <<<ENDARTIFACT>>>

    JSON-shaped artifact content (starting with ``{`` or ``[``) is parsed as
    JSON; all other content is kept as a raw string.

    For code artifacts that contain FILE/ENDFILE blocks, an additional
    ``<key>_files`` entry is added to the result dict mapping each file path to
    its content — this lets downstream steps iterate individual files (R4
    pattern) without changing the primary ``<key>`` value.

    Returns ``None`` when no sentinel blocks are found so callers can fall back
    to JSON parsing.
    """
    # Guard against ReDoS: cap input length before applying DOTALL regexes
    # on untrusted LLM text (missing <<<ENDARTIFACT>>> triggers backtracking).
    if len(text) > _MAX_SENTINEL_INPUT_LEN:
        text = text[:_MAX_SENTINEL_INPUT_LEN]
    matches = ARTIFACT_RE.findall(text)
    if not matches:
        return None

    result: dict[str, Any] = {}
    for key, raw_content in matches:
        content = raw_content.strip()
        stripped = content.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                result[key] = json.loads(content)
                continue
            except json.JSONDecodeError:
                pass
        # Keep raw string for backward compatibility
        result[key] = content
        # Also expose per-file dict for R4 consumers
        files = extract_files_from_artifact(content)
        if files:
            result[f"{key}_files"] = files

    if expected_output_keys and "review_report" in expected_output_keys:
        result = normalize_expected_structure(result, expected_output_keys)
    return result


# Backward-compatibility alias
_parse_sentinel_output = parse_sentinel_output
