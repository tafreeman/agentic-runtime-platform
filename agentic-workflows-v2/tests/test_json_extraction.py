"""Edge-case coverage for `agentic_v2.agents.json_extraction`.

Targets the error paths and fence-detection branches that the agent-level
tests don't exercise: generic ``` ``` fences containing JSON, escape-sequence
and string-literal handling inside balanced-brace extraction, unbalanced-brace
failure, and Pydantic validation failure.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agentic_v2.agents.json_extraction import (
    _extract_balanced_json,
    _find_json_string,
    extract_json,
)


class _Schema(BaseModel):
    name: str
    count: int


def test_find_json_string_generic_fence() -> None:
    """Strategy 2: generic ``` ``` fence (no `json` tag) wrapping a JSON object."""
    text = "Here you go:\n```\n{\"name\": \"x\", \"count\": 1}\n```\n"
    assert _find_json_string(text) == '{"name": "x", "count": 1}'


def test_extract_balanced_json_handles_escape_in_string() -> None:
    """Backslash escapes inside string literals must not break brace counting."""
    text = 'prefix {"path": "C:\\\\Users\\\\x", "n": 1} suffix'
    extracted = _extract_balanced_json(text)
    assert extracted == '{"path": "C:\\\\Users\\\\x", "n": 1}'


def test_extract_balanced_json_ignores_braces_inside_strings() -> None:
    """A `}` inside a quoted string must not close the outer object."""
    text = 'noise {"label": "} not a close", "ok": true} trailing'
    extracted = _extract_balanced_json(text)
    assert extracted == '{"label": "} not a close", "ok": true}'


def test_extract_balanced_json_raises_on_no_brace() -> None:
    with pytest.raises(ValueError, match="No JSON object"):
        _extract_balanced_json("just prose, no braces here")


def test_extract_balanced_json_raises_on_unbalanced() -> None:
    with pytest.raises(ValueError, match="Unbalanced braces"):
        _extract_balanced_json('{"name": "x"')


def test_extract_json_validation_failure_logs_and_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pydantic validation failures re-raise with a warning log line."""
    text = '```json\n{"name": "x", "count": "not-an-int"}\n```'
    with caplog.at_level("WARNING"), pytest.raises(ValidationError):
        extract_json(text, _Schema)
    assert any(
        "JSON schema validation failed" in record.message
        for record in caplog.records
    )


def test_extract_json_returns_dict_without_schema() -> None:
    """Untyped extraction returns a plain dict via `json.loads`."""
    text = "noise ```json\n{\"name\": \"x\", \"count\": 2}\n``` more noise"
    result = extract_json(text)
    assert result == {"name": "x", "count": 2}
