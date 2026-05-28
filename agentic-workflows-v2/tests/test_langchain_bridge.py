"""Tests for LangChain → contract bridge functions (CP-1 remediation).

Verifies ``_steps_dict_to_list`` and ``_build_workflow_result`` correctly
translate LangGraph runner state into canonical contract types.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from agentic_v2.contracts import StepResult, StepStatus, WorkflowResult
from agentic_v2.langchain.runner import _build_workflow_result, _steps_dict_to_list

# ── _steps_dict_to_list ─────────────────────────────────────────────


class TestStepsDictToList:
    """Verify step-dict → StepResult list conversion."""

    def test_success_status_mapping(self):
        steps = {"step_a": {"status": "success", "outputs": {"x": 1}}}
        result = _steps_dict_to_list(steps)
        assert len(result) == 1
        assert result[0].status == StepStatus.SUCCESS
        assert result[0].step_name == "step_a"
        assert result[0].output_data == {"x": 1}

    def test_failed_status_mapping(self):
        steps = {"step_b": {"status": "failed", "error": "boom"}}
        result = _steps_dict_to_list(steps)
        assert result[0].status == StepStatus.FAILED
        assert result[0].error == "boom"

    def test_error_status_maps_to_failed(self):
        steps = {"step_c": {"status": "error"}}
        result = _steps_dict_to_list(steps)
        assert result[0].status == StepStatus.FAILED

    def test_skipped_status_mapping(self):
        steps = {"step_d": {"status": "skipped"}}
        result = _steps_dict_to_list(steps)
        assert result[0].status == StepStatus.SKIPPED

    def test_unknown_status_defaults_to_failed(self):
        steps = {"step_e": {"status": "banana"}}
        result = _steps_dict_to_list(steps)
        assert result[0].status == StepStatus.FAILED

    def test_missing_status_defaults_to_success(self):
        """When no status key present, LangGraph convention = success."""
        steps = {"step_f": {"outputs": {"y": 2}}}
        result = _steps_dict_to_list(steps)
        assert result[0].status == StepStatus.SUCCESS

    def test_non_dict_step_data_skipped(self):
        steps = {"step_ok": {"status": "success"}, "step_bad": "not-a-dict"}
        result = _steps_dict_to_list(steps)
        assert len(result) == 1
        assert result[0].step_name == "step_ok"

    def test_empty_dict_returns_empty_list(self):
        assert _steps_dict_to_list({}) == []

    def test_token_counts_populated(self):
        steps = {"step_a": {"status": "success"}}
        tokens = {"step_a": {"input": 100, "output": 50}}
        result = _steps_dict_to_list(steps, token_counts=tokens)
        assert result[0].metadata["input_tokens"] == 100
        assert result[0].metadata["output_tokens"] == 50

    def test_models_used_populated(self):
        steps = {"step_a": {"status": "success"}}
        models = {"step_a": "gpt-4o"}
        result = _steps_dict_to_list(steps, models_used=models)
        assert result[0].model_used == "gpt-4o"

    def test_agent_role_extracted(self):
        steps = {"step_a": {"status": "success", "agent": "tier2_reviewer"}}
        result = _steps_dict_to_list(steps)
        assert result[0].agent_role == "tier2_reviewer"

    def test_multiple_steps_ordering(self):
        steps = {
            "a": {"status": "success"},
            "b": {"status": "failed"},
            "c": {"status": "skipped"},
        }
        result = _steps_dict_to_list(steps)
        assert [r.step_name for r in result] == ["a", "b", "c"]
        assert [r.status for r in result] == [
            StepStatus.SUCCESS,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
        ]


# ── _build_workflow_result ───────────────────────────────────────────


class TestBuildWorkflowResult:
    """Verify WorkflowResult construction from LangGraph state."""

    @pytest.fixture()
    def base_kwargs(self):
        return {
            "workflow_name": "test_workflow",
            "run_id": "run-123",
            "started_at": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "elapsed_seconds": 5.0,
        }

    def test_success_result(self, base_kwargs):
        result = _build_workflow_result(**base_kwargs, outputs={"answer": "42"})
        assert isinstance(result, WorkflowResult)
        assert result.overall_status == StepStatus.SUCCESS
        assert result.workflow_name == "test_workflow"
        assert result.workflow_id == "run-123"
        assert result.final_output == {"answer": "42"}

    def test_failed_flag(self, base_kwargs):
        result = _build_workflow_result(**base_kwargs, failed=True)
        assert result.overall_status == StepStatus.FAILED

    def test_errors_list_implies_failure(self, base_kwargs):
        result = _build_workflow_result(**base_kwargs, errors=["something broke"])
        assert result.overall_status == StepStatus.FAILED
        assert result.metadata["errors"] == ["something broke"]

    def test_empty_errors_means_success(self, base_kwargs):
        result = _build_workflow_result(**base_kwargs, errors=[])
        assert result.overall_status == StepStatus.SUCCESS

    def test_elapsed_stored_in_metadata(self, base_kwargs):
        result = _build_workflow_result(**base_kwargs)
        assert result.metadata["elapsed_seconds"] == 5.0

    def test_end_time_computed(self, base_kwargs):
        result = _build_workflow_result(**base_kwargs)
        assert result.end_time == datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

    def test_token_counts_in_metadata(self, base_kwargs):
        tc = {"step_a": {"input": 100, "output": 50}}
        result = _build_workflow_result(**base_kwargs, token_counts=tc)
        assert result.metadata["token_counts"] == tc

    def test_models_used_in_metadata(self, base_kwargs):
        mu = {"step_a": "gpt-4o"}
        result = _build_workflow_result(**base_kwargs, models_used=mu)
        assert result.metadata["models_used"] == mu

    def test_final_state_in_metadata(self, base_kwargs):
        fs = {"steps": {"a": {"status": "success"}}}
        result = _build_workflow_result(**base_kwargs, final_state=fs)
        assert result.metadata["final_state"] == fs

    def test_steps_forwarded(self, base_kwargs):
        step = StepResult(step_name="a", status=StepStatus.SUCCESS)
        result = _build_workflow_result(**base_kwargs, steps=[step])
        assert len(result.steps) == 1
        assert result.steps[0].step_name == "a"

    def test_defaults_produce_empty_collections(self, base_kwargs):
        result = _build_workflow_result(**base_kwargs)
        assert result.steps == []
        assert result.final_output == {}
        assert "errors" not in result.metadata
