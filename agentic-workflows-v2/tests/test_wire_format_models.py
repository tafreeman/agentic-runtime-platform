"""Validation tests for new S1-1 wire-format Pydantic models.

Covers:
  DAGResponse (with WorkflowInputSchemaItem in the inputs list)
  WorkflowInputSchemaItem
  WorkflowInputSchemaResponse
  WorkflowEditorStep
  RunsSummaryResponse (with RunSummaryModel sub-type)

Mirror the test style used in ``test_run_logger.py`` and ``test_server_models.py``:
Tier 1 (branching / error paths) + Tier 2 (contract / boundary) tests.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agentic_v2.server.models import (
    DAGEdgeModel,
    DAGNodeModel,
    DAGResponse,
    RunsSummaryResponse,
    RunSummaryModel,
    WorkflowEditorStep,
    WorkflowInputSchemaItem,
    WorkflowInputSchemaResponse,
)

# ---------------------------------------------------------------------------
# WorkflowInputSchemaItem — Tier 2 contract tests
# ---------------------------------------------------------------------------


class TestWorkflowInputSchemaItem:
    """Tests for the WorkflowInputSchemaItem model."""

    def test_minimal_valid(self) -> None:
        """Only ``name`` is required; all other fields have defaults."""
        item = WorkflowInputSchemaItem(name="prompt")
        assert item.name == "prompt"
        assert item.type == "string"
        assert item.description == ""
        assert item.default is None
        assert item.required is True
        assert item.enum is None

    def test_full_valid(self) -> None:
        """All fields accepted when provided."""
        item = WorkflowInputSchemaItem(
            name="mode",
            type="string",
            description="Operation mode",
            default="fast",
            required=False,
            enum=["fast", "slow", "turbo"],
        )
        assert item.name == "mode"
        assert item.default == "fast"
        assert item.enum == ["fast", "slow", "turbo"]
        assert item.required is False

    def test_enum_none_is_valid(self) -> None:
        """``enum=None`` is explicit and valid."""
        item = WorkflowInputSchemaItem(name="x", enum=None)
        assert item.enum is None

    def test_missing_name_raises(self) -> None:
        """``name`` is required; omitting it raises ValidationError."""
        with pytest.raises(ValidationError):
            WorkflowInputSchemaItem()  # type: ignore[call-arg]

    def test_model_dump_roundtrip(self) -> None:
        """model_dump() + model_validate() round-trips cleanly."""
        original = WorkflowInputSchemaItem(name="count", type="integer", required=False)
        data = original.model_dump()
        restored = WorkflowInputSchemaItem.model_validate(data)
        assert restored.name == original.name
        assert restored.type == original.type
        assert restored.required == original.required


# ---------------------------------------------------------------------------
# WorkflowInputSchemaResponse — Tier 2 contract tests
# ---------------------------------------------------------------------------


class TestWorkflowInputSchemaResponse:
    """Tests for the WorkflowInputSchemaResponse model."""

    def _nodes(self) -> list[dict[str, Any]]:
        return [{"id": "step-a", "depends_on": []}, {"id": "step-b", "depends_on": ["step-a"]}]

    def _edges(self) -> list[dict[str, Any]]:
        return [{"source": "step-a", "target": "step-b"}]

    def test_minimal_valid(self) -> None:
        """Required fields: name, nodes, edges."""
        resp = WorkflowInputSchemaResponse(
            name="wf-test", nodes=self._nodes(), edges=self._edges()
        )
        assert resp.name == "wf-test"
        assert len(resp.nodes) == 2
        assert len(resp.edges) == 1
        assert resp.inputs == []

    def test_with_inputs(self) -> None:
        """``inputs`` list is accepted and coerced from dicts."""
        resp = WorkflowInputSchemaResponse(
            name="wf-test",
            nodes=self._nodes(),
            edges=self._edges(),
            inputs=[
                {"name": "topic", "type": "string", "required": True},
                {"name": "depth", "type": "integer", "required": False, "default": 3},
            ],
        )
        assert len(resp.inputs) == 2
        assert resp.inputs[0].name == "topic"
        assert resp.inputs[1].default == 3

    def test_description_defaults_to_empty(self) -> None:
        """``description`` defaults to empty string."""
        resp = WorkflowInputSchemaResponse(
            name="wf", nodes=self._nodes(), edges=self._edges()
        )
        assert resp.description == ""

    def test_missing_name_raises(self) -> None:
        """``name`` is required."""
        with pytest.raises(ValidationError):
            WorkflowInputSchemaResponse(nodes=self._nodes(), edges=self._edges())  # type: ignore[call-arg]

    def test_invalid_input_item_raises(self) -> None:
        """An input item missing ``name`` raises a nested ValidationError."""
        with pytest.raises(ValidationError):
            WorkflowInputSchemaResponse(
                name="wf",
                nodes=self._nodes(),
                edges=self._edges(),
                inputs=[{"type": "string"}],  # name missing
            )

    def test_model_validate_from_dag_endpoint_shape(self) -> None:
        """Accepts the raw dict produced by the GET /api/workflows/{name}/dag endpoint."""
        raw: dict[str, Any] = {
            "name": "research-pipeline",
            "description": "Research DAG",
            "nodes": [
                {"id": "gather", "depends_on": []},
                {"id": "analyze", "depends_on": ["gather"]},
            ],
            "edges": [{"source": "gather", "target": "analyze"}],
            "inputs": [
                {
                    "name": "query",
                    "type": "string",
                    "description": "Search query",
                    "default": None,
                    "required": True,
                    "enum": None,
                }
            ],
        }
        resp = WorkflowInputSchemaResponse.model_validate(raw)
        assert resp.name == "research-pipeline"
        assert resp.inputs[0].name == "query"


# ---------------------------------------------------------------------------
# DAGResponse — updated with ``inputs`` field
# ---------------------------------------------------------------------------


class TestDAGResponseWithInputs:
    """Tests that DAGResponse now accepts the ``inputs`` field."""

    def test_dag_response_accepts_inputs(self) -> None:
        """DAGResponse.inputs defaults to empty list."""
        dag = DAGResponse(
            name="wf",
            nodes=[DAGNodeModel(id="a", depends_on=[])],
            edges=[DAGEdgeModel(source="a", target="a")],
        )
        assert dag.inputs == []

    def test_dag_response_with_inputs(self) -> None:
        """DAGResponse accepts WorkflowInputSchemaItem objects in inputs."""
        dag = DAGResponse(
            name="wf",
            nodes=[DAGNodeModel(id="a", depends_on=[])],
            edges=[],
            inputs=[WorkflowInputSchemaItem(name="topic", type="string")],
        )
        assert len(dag.inputs) == 1
        assert dag.inputs[0].name == "topic"

    def test_dag_response_inputs_coerced_from_dicts(self) -> None:
        """Input dicts are coerced to WorkflowInputSchemaItem automatically."""
        dag = DAGResponse(
            name="wf",
            nodes=[DAGNodeModel(id="a", depends_on=[])],
            edges=[],
            inputs=[{"name": "depth", "type": "integer", "default": 3}],
        )
        assert isinstance(dag.inputs[0], WorkflowInputSchemaItem)
        assert dag.inputs[0].default == 3


# ---------------------------------------------------------------------------
# WorkflowEditorStep — Tier 1 + Tier 2 tests
# ---------------------------------------------------------------------------


class TestWorkflowEditorStep:
    """Tests for the WorkflowEditorStep model."""

    def test_minimal_valid(self) -> None:
        """``name`` and ``depends_on`` are required; all other fields have defaults."""
        step = WorkflowEditorStep(name="gather", depends_on=[])
        assert step.name == "gather"
        assert step.agent is None
        assert step.description is None
        assert step.tier is None
        assert step.depends_on == []
        assert step.when is None
        assert step.loop_until is None
        assert step.loop_max is None
        assert step.tools == []
        assert step.prompt_file is None
        assert step.metadata is None

    def test_full_valid(self) -> None:
        """All fields accepted when provided."""
        step = WorkflowEditorStep(
            name="analyze",
            agent="tier2_analyst",
            description="Analyze the results",
            tier="2",
            depends_on=["gather"],
            when="output.count > 0",
            loop_until="done == true",
            loop_max=5,
            tools=["read_file", "search"],
            prompt_file="prompts/analyze.md",
            metadata={"priority": "high"},
        )
        assert step.name == "analyze"
        assert step.agent == "tier2_analyst"
        assert step.depends_on == ["gather"]
        assert step.loop_max == 5
        assert step.tools == ["read_file", "search"]
        assert step.metadata == {"priority": "high"}

    def test_missing_name_raises(self) -> None:
        """``name`` is required."""
        with pytest.raises(ValidationError):
            WorkflowEditorStep()  # type: ignore[call-arg]

    def test_loop_max_none(self) -> None:
        """``loop_max=None`` is valid (no loop constraint)."""
        step = WorkflowEditorStep(name="x", depends_on=[], loop_max=None)
        assert step.loop_max is None

    def test_loop_max_invalid_type_raises(self) -> None:
        """Non-integer ``loop_max`` raises ValidationError."""
        with pytest.raises(ValidationError):
            WorkflowEditorStep(name="x", depends_on=[], loop_max="five")  # type: ignore[arg-type]

    def test_model_dump_roundtrip(self) -> None:
        """model_dump() + model_validate() round-trips cleanly."""
        original = WorkflowEditorStep(
            name="code",
            agent="tier2_coder",
            depends_on=["plan"],
            tools=["write_file"],
        )
        data = original.model_dump()
        restored = WorkflowEditorStep.model_validate(data)
        assert restored.name == original.name
        assert restored.agent == original.agent
        assert restored.depends_on == original.depends_on
        assert restored.tools == original.tools

    def test_validation_error_on_invalid_dict_value(self) -> None:
        """A malformed depends_on value (non-list) raises ValidationError."""
        with pytest.raises(ValidationError):
            WorkflowEditorStep(name="x", depends_on="not-a-list")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RunsSummaryResponse — Tier 2 contract tests
# ---------------------------------------------------------------------------


class TestRunsSummaryResponseContract:
    """Tests for the RunsSummaryResponse model (schema coverage)."""

    def test_all_defaults(self) -> None:
        """All fields have defaults so empty construction succeeds."""
        resp = RunsSummaryResponse()
        assert resp.total_runs == 0
        assert resp.success == 0
        assert resp.failed == 0
        assert resp.avg_duration_ms is None
        assert resp.workflows == []
        assert resp.tokens_30d is None

    def test_full_valid(self) -> None:
        """All fields accepted when provided."""
        resp = RunsSummaryResponse(
            total_runs=10,
            success=8,
            failed=2,
            avg_duration_ms=1234.5,
            workflows=["wf-a", "wf-b"],
            tokens_30d=50000,
        )
        assert resp.total_runs == 10
        assert resp.avg_duration_ms == pytest.approx(1234.5)
        assert resp.workflows == ["wf-a", "wf-b"]
        assert resp.tokens_30d == 50000

    def test_model_dump_roundtrip(self) -> None:
        """model_dump() + model_validate() round-trips cleanly."""
        original = RunsSummaryResponse(total_runs=3, success=3, workflows=["wf-x"])
        data = original.model_dump()
        restored = RunsSummaryResponse.model_validate(data)
        assert restored.total_runs == original.total_runs
        assert restored.workflows == original.workflows

    def test_avg_duration_none(self) -> None:
        """``avg_duration_ms=None`` is valid (no runs with duration)."""
        resp = RunsSummaryResponse(avg_duration_ms=None)
        assert resp.avg_duration_ms is None

    def test_invalid_total_runs_type_raises(self) -> None:
        """Non-integer ``total_runs`` raises ValidationError."""
        with pytest.raises(ValidationError):
            RunsSummaryResponse(total_runs="ten")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RunSummaryModel — Tier 2 contract tests
# ---------------------------------------------------------------------------


class TestRunSummaryModelContract:
    """Tests for the RunSummaryModel (individual run summary) model."""

    def test_minimal_valid(self) -> None:
        """Only ``filename`` is required."""
        summary = RunSummaryModel(filename="run_001.json")
        assert summary.filename == "run_001.json"
        assert summary.run_id is None
        assert summary.workflow_name is None
        assert summary.status is None
        assert summary.success_rate is None
        assert summary.total_duration_ms is None
        assert summary.step_count is None
        assert summary.failed_step_count is None
        assert summary.evaluation_score is None
        assert summary.evaluation_grade is None

    def test_full_valid(self) -> None:
        """All optional fields accepted when provided."""
        summary = RunSummaryModel(
            filename="20260501T120000Z_research_pipeline_success.json",
            run_id="research-pipeline-abc123",
            workflow_name="research-pipeline",
            status="success",
            success_rate=1.0,
            total_duration_ms=4200.0,
            step_count=3,
            failed_step_count=0,
            start_time="2026-05-01T12:00:00Z",
            end_time="2026-05-01T12:00:04.2Z",
            evaluation_score=92.5,
            evaluation_grade="A",
        )
        assert summary.run_id == "research-pipeline-abc123"
        assert summary.success_rate == pytest.approx(1.0)
        assert summary.evaluation_grade == "A"

    def test_model_dump_roundtrip(self) -> None:
        """model_dump() + model_validate() round-trips cleanly."""
        original = RunSummaryModel(
            filename="run.json",
            run_id="run-1",
            status="failed",
            step_count=2,
            failed_step_count=1,
        )
        data = original.model_dump()
        restored = RunSummaryModel.model_validate(data)
        assert restored.filename == original.filename
        assert restored.status == original.status
        assert restored.failed_step_count == original.failed_step_count

    def test_missing_filename_raises(self) -> None:
        """``filename`` is required."""
        with pytest.raises(ValidationError):
            RunSummaryModel()  # type: ignore[call-arg]
