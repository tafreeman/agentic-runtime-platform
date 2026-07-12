#!/usr/bin/env python
"""Dump wire-format Pydantic models to committed JSON Schemas.

This is the Python half of the Sprint B #3 wire-format drift gate. The
artifacts written here are consumed by ``ui/scripts/generate-ts-types.mjs``
to produce the TypeScript mirrors of the Python contracts.

Sources of truth:
    ``agentic_v2/contracts/events.py``       → tests/schemas/events.schema.json
    ``agentic_v2/server/models.py``          → tests/schemas/step_result.schema.json
    ``agentic_v2/server/models.py``          → tests/schemas/dag_response.schema.json
    ``agentic_v2/server/models.py``          → tests/schemas/workflow_input_schema.schema.json
    ``agentic_v2/server/models.py``          → tests/schemas/workflow_editor_step.schema.json
    ``agentic_v2/server/models.py``          → tests/schemas/runs_summary.schema.json

Run it manually when editing either contract:

    cd agentic-workflows-v2
    python -m scripts.generate_ts_types

CI regenerates these files and fails the ``wire-format-drift`` job if the
output does not match what's committed.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from agentic_v2.contracts.events import ExecutionEvent
from agentic_v2.server.models import (
    DAGResponse,
    RunsSummaryResponse,
    StepResultRecord,
    WorkflowEditorStep,
    WorkflowInputSchemaResponse,
)

_SCHEMAS_DIR = Path(__file__).parent.parent / "tests" / "schemas"

EVENTS_OUT_PATH = _SCHEMAS_DIR / "events.schema.json"
STEP_RESULT_OUT_PATH = _SCHEMAS_DIR / "step_result.schema.json"
DAG_RESPONSE_OUT_PATH = _SCHEMAS_DIR / "dag_response.schema.json"
WORKFLOW_INPUT_SCHEMA_OUT_PATH = _SCHEMAS_DIR / "workflow_input_schema.schema.json"
WORKFLOW_EDITOR_STEP_OUT_PATH = _SCHEMAS_DIR / "workflow_editor_step.schema.json"
RUNS_SUMMARY_OUT_PATH = _SCHEMAS_DIR / "runs_summary.schema.json"


def _write_schema(schema: dict, out_path: Path) -> None:
    """Write a JSON Schema dict to *out_path* deterministically."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys=True + trailing newline → deterministic output so CI diff
    # stays stable across Python + Pydantic patch versions.
    out_path.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out_path}")


def main() -> None:
    """Dump all wire-format JSON Schemas to the committed artifacts."""
    # --- ExecutionEvent (discriminated union) ---
    adapter: TypeAdapter[ExecutionEvent] = TypeAdapter(ExecutionEvent)
    _write_schema(adapter.json_schema(), EVENTS_OUT_PATH)

    # --- StepResultRecord (HTTP step detail wire shape) ---
    step_adapter: TypeAdapter[StepResultRecord] = TypeAdapter(StepResultRecord)
    _write_schema(step_adapter.json_schema(), STEP_RESULT_OUT_PATH)

    # --- DAGResponse (workflow DAG visualization + inputs) ---
    dag_adapter: TypeAdapter[DAGResponse] = TypeAdapter(DAGResponse)
    _write_schema(dag_adapter.json_schema(), DAG_RESPONSE_OUT_PATH)

    # --- WorkflowInputSchemaResponse (full DAG + typed inputs list) ---
    wis_adapter: TypeAdapter[WorkflowInputSchemaResponse] = TypeAdapter(
        WorkflowInputSchemaResponse
    )
    _write_schema(wis_adapter.json_schema(), WORKFLOW_INPUT_SCHEMA_OUT_PATH)

    # --- WorkflowEditorStep (step shape in editor documents) ---
    wes_adapter: TypeAdapter[WorkflowEditorStep] = TypeAdapter(WorkflowEditorStep)
    _write_schema(wes_adapter.json_schema(), WORKFLOW_EDITOR_STEP_OUT_PATH)

    # --- RunsSummaryResponse + RunSummaryModel (run list views) ---
    runs_adapter: TypeAdapter[RunsSummaryResponse] = TypeAdapter(RunsSummaryResponse)
    _write_schema(runs_adapter.json_schema(), RUNS_SUMMARY_OUT_PATH)


if __name__ == "__main__":
    main()
