"""Every broadcast event must validate against a Pydantic model.

Failure modes this catches:
- A new code path emits a dict shape not in the union
- A field is renamed server-side but the client still expects the old name
- A required field is dropped
"""
from __future__ import annotations

import pytest

from agentic_v2.contracts.events import validate_event


def test_workflow_start_valid() -> None:
    payload = {
        "type": "workflow_start",
        "run_id": "r-1",
        "workflow_name": "code_review",
        "timestamp": "2026-04-21T00:00:00Z",
    }
    event = validate_event(payload)
    assert event.type == "workflow_start"


def test_step_end_valid() -> None:
    payload = {
        "type": "step_end",
        "run_id": "r-1",
        "step": "parse_code",
        "status": "success",
        "duration_ms": 42,
        "timestamp": "2026-04-21T00:00:00Z",
    }
    event = validate_event(payload)
    assert event.type == "step_end"


def test_error_event_valid() -> None:
    payload = {
        "type": "error",
        "run_id": "r-1",
        "error": "workflow failed",
        "timestamp": "2026-04-21T00:00:00Z",
    }
    event = validate_event(payload)
    assert event.type == "error"


def test_unknown_type_rejected() -> None:
    with pytest.raises(ValueError, match="tag"):
        validate_event({"type": "bogus", "run_id": "r-1", "timestamp": "..."})


def test_missing_required_field_rejected() -> None:
    with pytest.raises(ValueError):
        validate_event({"type": "step_start", "run_id": "r-1"})  # no `step`
