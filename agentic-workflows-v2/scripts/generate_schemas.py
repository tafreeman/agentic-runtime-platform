#!/usr/bin/env python
"""Generate JSON Schema snapshots for covered contracts/ models.

Run this script when making intentional schema changes:
    python scripts/generate_schemas.py

Then commit the updated snapshots alongside the model change.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentic_v2.contracts import (
    AgentMessage,
    ChatDoneEvent,
    ChatErrorEvent,
    ChatMediaEvent,
    ChatMessage,
    ChatRequest,
    ChatRouteEvent,
    ChatTokenEvent,
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
    ChatMessage,
    ChatRequest,
    ChatRouteEvent,
    ChatTokenEvent,
    ChatMediaEvent,
    ChatDoneEvent,
    ChatErrorEvent,
]

SCHEMA_DIR = Path(__file__).parent.parent / "tests" / "schemas"


def main() -> None:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for model_class in COVERED_MODELS:
        schema = model_class.model_json_schema()
        path = SCHEMA_DIR / f"{model_class.__name__}.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
        print(f"  wrote {path.relative_to(Path.cwd())}")
    print(f"\n{len(COVERED_MODELS)} snapshots written to {SCHEMA_DIR}")


if __name__ == "__main__":
    main()
