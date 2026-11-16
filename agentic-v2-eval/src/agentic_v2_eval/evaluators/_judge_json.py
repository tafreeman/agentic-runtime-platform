"""Shared JSON extraction for LLM-judge responses."""

from __future__ import annotations

import json
import re
from typing import Any

# Guard against ReDoS on pathological untrusted input (LLM output).
_MAX_PARSE_LEN = 262144  # 256 KB — ample for any realistic LLM response
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_judge_json(text: str) -> dict[str, Any] | None:
    """Extract and parse a JSON object from judge output.

    Handles markdown code fences, then falls back to the span between the
    first ``{`` and the last ``}``. Returns ``None`` when nothing parses.
    """
    if len(text) > _MAX_PARSE_LEN:
        text = text[:_MAX_PARSE_LEN]
    match = _FENCE_RE.search(text)
    if match:
        text = match.group(1)

    try:
        parsed: dict[str, Any] = json.loads(text)
        return parsed
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                fallback: dict[str, Any] = json.loads(text[start : end + 1])
                return fallback
            except json.JSONDecodeError:
                pass
    return None
