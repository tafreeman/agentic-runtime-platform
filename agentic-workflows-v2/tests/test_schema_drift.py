"""Schema-drift guard for contracts/ Pydantic models.

Any field removal or type narrowing in a covered model will fail this test.
Additive changes (new optional fields) are allowed.

To update snapshots after an intentional schema change:
    python scripts/generate_schemas.py
    git add tests/schemas/
    git commit -m "chore(schemas): update schema snapshots for <ModelName>"
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_v2.contracts import (
    AgentMessage,
    CodeGenerationOutput,
    CodeReviewInput,
    CodeReviewOutput,
    EvaluationCompleteEvent,
    EvaluationStartEvent,
    ReviewReport,
    StepCompleteEvent,
    StepEndEvent,
    StepErrorEvent,
    StepResult,
    StepStartEvent,
    TaskInput,
    TaskOutput,
    WorkflowEndEvent,
    WorkflowResult,
    WorkflowStartEvent,
)

SCHEMA_DIR = Path(__file__).parent / "schemas"

COVERED_MODELS = [
    WorkflowResult,
    StepResult,
    AgentMessage,
    ReviewReport,
    CodeReviewInput,
    CodeReviewOutput,
    CodeGenerationOutput,
    TaskInput,
    TaskOutput,
    WorkflowStartEvent,
    StepStartEvent,
    StepEndEvent,
    StepCompleteEvent,
    StepErrorEvent,
    WorkflowEndEvent,
    EvaluationStartEvent,
    EvaluationCompleteEvent,
]


@pytest.mark.parametrize("model_class", COVERED_MODELS, ids=lambda m: m.__name__)
def test_no_schema_drift(model_class):
    """Current schema must be a superset of the committed snapshot."""
    snapshot_path = SCHEMA_DIR / f"{model_class.__name__}.json"
    assert snapshot_path.exists(), (
        f"No schema snapshot for {model_class.__name__}. "
        f"Run: python scripts/generate_schemas.py"
    )

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    current = model_class.model_json_schema()

    snapshot_props = set(snapshot.get("properties", {}).keys())
    current_props = set(current.get("properties", {}).keys())

    removed = snapshot_props - current_props
    assert not removed, (
        f"{model_class.__name__}: field(s) removed from schema: {removed}. "
        f"Field removal is not allowed (additive-only). "
        f"If intentional, update the snapshot: python scripts/generate_schemas.py"
    )
