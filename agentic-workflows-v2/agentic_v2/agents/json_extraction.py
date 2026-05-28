"""Shared JSON extraction and validation for agent response parsing.

Replaces fragile regex-based JSON extraction (greedy ``\\{.*\\}`` pattern)
with a robust two-stage approach:

1. **Extract** — locate JSON within fenced code blocks or raw text.
2. **Validate** — parse via Pydantic ``model_validate_json()`` when a schema
   is provided, or ``json.loads()`` for untyped extraction.

Used by :class:`OrchestratorAgent`, :class:`ReviewerAgent`, and
:class:`ArchitectAgent`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar, overload

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Pattern: ```json ... ``` (non-greedy, captures content inside fences)
_FENCED_JSON_RE = re.compile(r"```json\s*(.*?)```", re.DOTALL)

# Pattern: ``` ... ``` (non-greedy, captures content inside any code fence)
_FENCED_ANY_RE = re.compile(r"```\s*\n?(\{.*?\})\s*\n?```", re.DOTALL)


def _find_json_string(text: str) -> str:
    """Extract the most likely JSON string from LLM response text.

    Strategy (in order of preference):
    1. Content inside ``\\`\\`\\`json ... \\`\\`\\``` fenced blocks.
    2. Content inside generic ``\\`\\`\\` ... \\`\\`\\``` fenced blocks that
       looks like JSON (starts with ``{``).
    3. Balanced brace extraction from raw text — finds the first ``{`` and
       its matching ``}`` using brace counting, avoiding the greedy regex
       ``\\{.*\\}`` problem.

    Args:
        text: Raw LLM response that may contain JSON.

    Returns:
        The extracted JSON string.

    Raises:
        ValueError: If no JSON-like content is found.
    """
    # Strategy 1: ```json ... ```
    match = _FENCED_JSON_RE.search(text)
    if match:
        return match.group(1).strip()

    # Strategy 2: ``` ... ``` with JSON inside
    match = _FENCED_ANY_RE.search(text)
    if match:
        return match.group(1).strip()

    # Strategy 3: Balanced brace extraction (replaces greedy regex)
    return _extract_balanced_json(text)


def _extract_balanced_json(text: str) -> str:
    """Extract JSON by finding balanced braces from the first ``{``.

    Unlike the greedy regex ``\\{.*\\}`` (which captures to the LAST ``}``
    in the entire text), this counts brace nesting to find the correct
    closing brace for the first top-level object.

    Args:
        text: Raw text containing embedded JSON.

    Returns:
        The balanced JSON substring.

    Raises:
        ValueError: If no ``{`` is found or braces are unbalanced.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise ValueError("Unbalanced braces in JSON response")


@overload
def extract_json(text: str) -> dict[str, Any]: ...


@overload
def extract_json(text: str, model: type[T]) -> T: ...


def extract_json(text: str, model: type[T] | None = None) -> dict[str, Any] | T:
    """Extract and optionally validate JSON from an LLM response.

    Args:
        text: Raw LLM response text.
        model: Optional Pydantic model class for schema validation.
            When provided, returns a validated model instance.
            When ``None``, returns a plain ``dict``.

    Returns:
        Validated Pydantic model instance if ``model`` is provided,
        otherwise a plain dict.

    Raises:
        ValueError: If no JSON is found or JSON is malformed.
        ValidationError: If JSON doesn't match the Pydantic schema.
    """
    json_str = _find_json_string(text)

    if model is not None:
        try:
            return model.model_validate_json(json_str)
        except ValidationError:
            # Log and re-raise — caller decides fallback behavior
            logger.warning("JSON schema validation failed for %s", model.__name__)
            raise

    return json.loads(json_str)
