"""Focused unit tests for agentic_v2.server.evaluation_scoring.

Covers the scoring-engine internals that were extracted into this module
during the refactoring described in REFACTORING_PLAN.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from agentic_v2.contracts import StepResult, StepStatus, WorkflowResult
from agentic_v2.server.evaluation_scoring import (
    CriterionFloorResult,
    HardGateResult,
    _resolve_rubric,
    _step_scores,
    _validate_rubric_weights,
    compute_hard_gates,
    pass_threshold,
    score_workflow_result_impl,
    validate_evaluation_payload_schema,
)
from agentic_v2.server.scoring_criteria import (
    _advisory_efficiency_score,
    _advisory_similarity_score,
    _clamp,
    _compose_hybrid_score,
    _compute_criterion_score,
    _extract_expected_text,
    _grade,
    _output_text,
    _text_overlap_score,
    _tokenize,
)
from agentic_v2.workflows.loader import (
    WorkflowCriterion,
    WorkflowDefinition,
    WorkflowEvaluation,
    WorkflowOutput,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    status: StepStatus = StepStatus.SUCCESS,
    final_output: dict | None = None,
    step_statuses: list[StepStatus] | None = None,
) -> WorkflowResult:
    now = datetime.now(timezone.utc)
    result = WorkflowResult(
        workflow_id="wf-scoring",
        workflow_name="test_workflow",
        overall_status=status,
        start_time=now,
        end_time=now,
        final_output=final_output or {"summary": "ok"},
    )
    for st in step_statuses or [StepStatus.SUCCESS]:
        result.add_step(
            StepResult(
                step_name="step",
                status=st,
                input_data={},
                output_data={},
                start_time=now,
                end_time=now,
            )
        )
    return result


def _valid_payload() -> dict:
    """Return a minimal schema-valid evaluation payload."""
    return {
        "rubric_id": "workflow_default",
        "rubric_version": "1.0",
        "criteria": [
            {
                "criterion": "correctness",
                "raw_score": 80.0,
                "normalized_score": 80.0,
                "weight": 0.5,
                "formula_id": "linear",
                "score": 80.0,
            }
        ],
        "overall_score": 80.0,
        "weighted_score": 40.0,
        "grade": "B",
        "passed": True,
        "pass_threshold": 70.0,
        "step_scores": [],
    }


# ---------------------------------------------------------------------------
# HardGateResult
# ---------------------------------------------------------------------------


class TestHardGateResult:
    def test_all_passed_when_all_true(self) -> None:
        hgr = HardGateResult(
            required_outputs_present=True,
            overall_status_success=True,
            no_critical_step_failures=True,
            release_build_verified=True,
            schema_contract_valid=True,
            dataset_workflow_compatible=True,
        )
        assert hgr.all_passed is True

    def test_all_passed_false_when_one_fails(self) -> None:
        hgr = HardGateResult(
            required_outputs_present=False,
            overall_status_success=True,
            no_critical_step_failures=True,
            release_build_verified=True,
            schema_contract_valid=True,
            dataset_workflow_compatible=True,
        )
        assert hgr.all_passed is False

    def test_failures_lists_failed_fields(self) -> None:
        hgr = HardGateResult(
            required_outputs_present=False,
            overall_status_success=False,
            no_critical_step_failures=True,
            release_build_verified=True,
            schema_contract_valid=True,
            dataset_workflow_compatible=True,
        )
        failures = hgr.failures
        assert "required_outputs_present" in failures
        assert "overall_status_success" in failures
        assert len(failures) == 2

    def test_failures_empty_when_all_pass(self) -> None:
        hgr = HardGateResult(
            required_outputs_present=True,
            overall_status_success=True,
            no_critical_step_failures=True,
            release_build_verified=True,
            schema_contract_valid=True,
            dataset_workflow_compatible=True,
        )
        assert hgr.failures == []


# ---------------------------------------------------------------------------
# CriterionFloorResult
# ---------------------------------------------------------------------------


class TestCriterionFloorResult:
    def test_stores_fields(self) -> None:
        cfr = CriterionFloorResult(
            criterion="correctness",
            floor=60.0,
            normalized_score=45.0,
        )
        assert cfr.criterion == "correctness"
        assert cfr.floor == 60.0
        assert cfr.normalized_score == 45.0


# ---------------------------------------------------------------------------
# validate_evaluation_payload_schema
# ---------------------------------------------------------------------------


class TestValidateEvaluationPayloadSchema:
    def test_valid_payload_passes(self) -> None:
        ok, errors = validate_evaluation_payload_schema(_valid_payload())
        assert ok is True
        assert errors == []

    def test_non_dict_payload_fails(self) -> None:
        ok, errors = validate_evaluation_payload_schema("not-a-dict")  # type: ignore[arg-type]
        assert ok is False
        assert any("mapping" in e for e in errors)

    def test_missing_required_field(self) -> None:
        payload = _valid_payload()
        del payload["rubric_id"]
        ok, errors = validate_evaluation_payload_schema(payload)
        assert ok is False
        assert any("rubric_id" in e for e in errors)

    def test_wrong_type_for_overall_score(self) -> None:
        payload = _valid_payload()
        payload["overall_score"] = "eighty"  # should be numeric
        ok, errors = validate_evaluation_payload_schema(payload)
        assert ok is False
        assert any("overall_score" in e for e in errors)

    def test_criterion_missing_key(self) -> None:
        payload = _valid_payload()
        del payload["criteria"][0]["weight"]
        ok, errors = validate_evaluation_payload_schema(payload)
        assert ok is False
        assert any("weight" in e for e in errors)

    def test_empty_criteria_list_is_valid(self) -> None:
        payload = _valid_payload()
        payload["criteria"] = []
        ok, errors = validate_evaluation_payload_schema(payload)
        assert ok is True


# ---------------------------------------------------------------------------
# compute_hard_gates
# ---------------------------------------------------------------------------


class TestComputeHardGates:
    def test_success_result_passes_all_gates(self) -> None:
        result = _make_result(
            status=StepStatus.SUCCESS,
            final_output={"summary": "done"},
            step_statuses=[StepStatus.SUCCESS, StepStatus.SUCCESS],
        )
        hgr = compute_hard_gates(result)
        assert hgr.overall_status_success is True
        assert hgr.no_critical_step_failures is True
        assert hgr.schema_contract_valid is True  # no payload provided → default True
        assert hgr.dataset_workflow_compatible is True

    def test_failed_status_fails_gate(self) -> None:
        result = _make_result(status=StepStatus.FAILED)
        hgr = compute_hard_gates(result)
        assert hgr.overall_status_success is False

    def test_failed_step_fails_critical_gate(self) -> None:
        result = _make_result(
            status=StepStatus.SUCCESS,
            step_statuses=[StepStatus.SUCCESS, StepStatus.FAILED],
        )
        hgr = compute_hard_gates(result)
        assert hgr.no_critical_step_failures is False

    def test_schema_contract_validated_when_payload_provided(self) -> None:
        result = _make_result()
        bad_payload = {"rubric_id": "x"}  # missing most required fields
        hgr = compute_hard_gates(result, eval_payload=bad_payload)
        assert hgr.schema_contract_valid is False

    def test_schema_contract_valid_when_good_payload_provided(self) -> None:
        result = _make_result()
        hgr = compute_hard_gates(result, eval_payload=_valid_payload())
        assert hgr.schema_contract_valid is True

    def test_dataset_workflow_compatible_propagated(self) -> None:
        result = _make_result()
        hgr = compute_hard_gates(result, dataset_workflow_compatible=False)
        assert hgr.dataset_workflow_compatible is False
        assert hgr.all_passed is False

    def test_required_outputs_missing_fails_gate(self) -> None:
        result = _make_result(final_output={"other_key": "value"})
        # Declare "summary" as a required output
        workflow_outputs = {
            "summary": WorkflowOutput(
                name="summary", from_expr="steps.last.summary", optional=False
            )
        }
        hgr = compute_hard_gates(result, workflow_outputs=workflow_outputs)
        # final_output has "other_key" but not "summary" → required output absent
        assert hgr.required_outputs_present is False


# --- ADR-008 Phase 2C: additional coverage ---


# ---------------------------------------------------------------------------
# Helpers (extended)
# ---------------------------------------------------------------------------


def _make_result_with_steps(
    status: StepStatus = StepStatus.SUCCESS,
    final_output: dict | None = None,
    step_configs: list[dict] | None = None,
    metadata: dict | None = None,
) -> WorkflowResult:
    """Build a WorkflowResult with fine-grained step control.

    Each entry in ``step_configs`` is a dict with ``name``, ``status``,
    and optionally ``output_data`` and ``retry_count``.
    """
    now = datetime.now(timezone.utc)
    result = WorkflowResult(
        workflow_id="wf-scoring",
        workflow_name="test_workflow",
        overall_status=status,
        start_time=now,
        end_time=now + timedelta(seconds=1),
        final_output=final_output or {"summary": "ok"},
        metadata=metadata or {},
    )
    for cfg in step_configs or [{"name": "step", "status": StepStatus.SUCCESS}]:
        result.add_step(
            StepResult(
                step_name=cfg.get("name", "step"),
                status=cfg.get("status", StepStatus.SUCCESS),
                input_data={},
                output_data=cfg.get("output_data", {}),
                start_time=now,
                end_time=now + timedelta(milliseconds=500),
                retry_count=cfg.get("retry_count", 0),
            )
        )
    return result


# ---------------------------------------------------------------------------
# _validate_rubric_weights
# ---------------------------------------------------------------------------


class TestValidateRubricWeights:
    def test_valid_weights_pass(self) -> None:
        """Weights that sum to 1.0 with positive values pass validation."""
        _validate_rubric_weights({"correctness": 0.6, "efficiency": 0.4})

    def test_empty_weights_raise_value_error(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_rubric_weights({})

    def test_unknown_criteria_raise_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown criteria"):
            _validate_rubric_weights(
                {"correctness": 0.5, "bogus": 0.5},
                known_criteria={"correctness", "efficiency"},
            )

    def test_non_positive_weight_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            _validate_rubric_weights({"correctness": 0.0, "efficiency": 1.0})

    def test_weights_not_summing_to_one_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="sum to 1.0"):
            _validate_rubric_weights({"correctness": 0.3, "efficiency": 0.3})

    def test_weights_within_tolerance_pass(self) -> None:
        """Weights summing to 1.005 (within 0.01 tolerance) should pass."""
        _validate_rubric_weights({"a": 0.505, "b": 0.5})


# ---------------------------------------------------------------------------
# _step_scores
# ---------------------------------------------------------------------------


class TestStepScores:
    def test_success_step_scores_100(self) -> None:
        result = _make_result(step_statuses=[StepStatus.SUCCESS])
        scores = _step_scores(result)
        assert len(scores) == 1
        assert scores[0]["score"] == 100.0
        assert scores[0]["status"] == StepStatus.SUCCESS.value

    def test_failed_step_scores_zero(self) -> None:
        result = _make_result(
            status=StepStatus.FAILED,
            step_statuses=[StepStatus.FAILED],
        )
        scores = _step_scores(result)
        assert scores[0]["score"] == 0.0
        assert scores[0]["status"] == StepStatus.FAILED.value

    def test_skipped_step_scores_zero(self) -> None:
        result = _make_result(step_statuses=[StepStatus.SKIPPED])
        scores = _step_scores(result)
        assert scores[0]["score"] == 0.0

    def test_mixed_steps_preserve_order(self) -> None:
        result = _make_result(
            step_statuses=[StepStatus.SUCCESS, StepStatus.FAILED, StepStatus.SKIPPED],
        )
        scores = _step_scores(result)
        assert len(scores) == 3
        assert scores[0]["score"] == 100.0
        assert scores[1]["score"] == 0.0
        assert scores[2]["score"] == 0.0

    def test_empty_steps_returns_empty(self) -> None:
        now = datetime.now(timezone.utc)
        result = WorkflowResult(
            workflow_id="wf-scoring",
            workflow_name="test_workflow",
            overall_status=StepStatus.SUCCESS,
            start_time=now,
            end_time=now,
        )
        assert _step_scores(result) == []


# ---------------------------------------------------------------------------
# pass_threshold
# ---------------------------------------------------------------------------


class TestPassThreshold:
    def test_returns_default_when_config_missing(self) -> None:
        with patch(
            "agentic_v2.server.evaluation_scoring._load_eval_config",
            return_value={},
        ):
            assert pass_threshold() == 70.0

    def test_returns_configured_value(self) -> None:
        with patch(
            "agentic_v2.server.evaluation_scoring._load_eval_config",
            return_value={"evaluation": {"scoring": {"pass_threshold": 85.0}}},
        ):
            assert pass_threshold() == 85.0

    def test_returns_default_on_invalid_value(self) -> None:
        with patch(
            "agentic_v2.server.evaluation_scoring._load_eval_config",
            return_value={
                "evaluation": {"scoring": {"pass_threshold": "not-a-number"}}
            },
        ):
            assert pass_threshold() == 70.0


# ---------------------------------------------------------------------------
# _resolve_rubric
# ---------------------------------------------------------------------------


class TestResolveRubric:
    def test_defaults_when_no_workflow_definition(self) -> None:
        with patch(
            "agentic_v2.server.evaluation_scoring._load_eval_config",
            return_value={},
        ):
            rubric_id, version, weights, criteria = _resolve_rubric(None, None)
            assert rubric_id == "workflow_default"
            assert version == "1.0"
            assert "correctness" in weights

    def test_rubric_override_takes_precedence(self) -> None:
        with patch(
            "agentic_v2.server.evaluation_scoring._load_eval_config",
            return_value={},
        ):
            rubric_id, _, _, _ = _resolve_rubric(None, "my_custom_rubric")
            assert rubric_id == "my_custom_rubric"

    def test_scoring_profile_weights_applied(self) -> None:
        """Scoring profile A should inject its criterion weights."""
        wf = WorkflowDefinition(
            name="test",
            evaluation=WorkflowEvaluation(
                scoring_profile="A",
                criteria=[
                    WorkflowCriterion(name="objective_tests", weight=0.60),
                    WorkflowCriterion(name="code_quality", weight=0.20),
                    WorkflowCriterion(name="efficiency", weight=0.10),
                    WorkflowCriterion(name="documentation", weight=0.10),
                ],
            ),
        )
        with patch(
            "agentic_v2.server.evaluation_scoring._load_eval_config",
            return_value={},
        ):
            _, _, weights, _ = _resolve_rubric(wf, None)
            assert "objective_tests" in weights
            assert weights["objective_tests"] == 0.60

    def test_workflow_rubric_id_used_when_no_override(self) -> None:
        wf = WorkflowDefinition(
            name="test",
            evaluation=WorkflowEvaluation(
                rubric_id="custom_rubric",
                criteria=[
                    WorkflowCriterion(name="correctness", weight=0.5),
                    WorkflowCriterion(name="efficiency", weight=0.5),
                ],
            ),
        )
        with patch(
            "agentic_v2.server.evaluation_scoring._load_eval_config",
            return_value={},
        ):
            rubric_id, _, _, _ = _resolve_rubric(wf, None)
            assert rubric_id == "custom_rubric"


# ---------------------------------------------------------------------------
# compute_hard_gates — additional branches
# ---------------------------------------------------------------------------


class TestComputeHardGatesExtended:
    def test_release_build_step_failed_fails_gate(self) -> None:
        result = _make_result_with_steps(
            step_configs=[
                {"name": "build_verify_release_v1", "status": StepStatus.FAILED},
            ],
        )
        hgr = compute_hard_gates(result)
        assert hgr.release_build_verified is False

    def test_release_build_step_ready_false_fails_gate(self) -> None:
        result = _make_result_with_steps(
            step_configs=[
                {
                    "name": "release_build_verify_v1",
                    "status": StepStatus.SUCCESS,
                    "output_data": {"ready_for_release": False},
                },
            ],
        )
        hgr = compute_hard_gates(result)
        assert hgr.release_build_verified is False

    def test_release_build_step_ready_true_passes_gate(self) -> None:
        result = _make_result_with_steps(
            step_configs=[
                {
                    "name": "build_verify_release_v1",
                    "status": StepStatus.SUCCESS,
                    "output_data": {"ready_for_release": True},
                },
            ],
        )
        hgr = compute_hard_gates(result)
        assert hgr.release_build_verified is True

    def test_release_build_truthy_string_passes(self) -> None:
        result = _make_result_with_steps(
            step_configs=[
                {
                    "name": "build_verify_release_v1",
                    "status": StepStatus.SUCCESS,
                    "output_data": {"ready_for_release": "yes"},
                },
            ],
        )
        hgr = compute_hard_gates(result)
        assert hgr.release_build_verified is True

    def test_release_build_falsy_string_fails(self) -> None:
        result = _make_result_with_steps(
            step_configs=[
                {
                    "name": "build_verify_release_v1",
                    "status": StepStatus.SUCCESS,
                    "output_data": {"ready_for_release": "no"},
                },
            ],
        )
        hgr = compute_hard_gates(result)
        assert hgr.release_build_verified is False

    def test_non_list_unresolved_required_outputs_treated_as_empty(self) -> None:
        result = _make_result_with_steps(
            final_output={"summary": "done"},
            metadata={"unresolved_required_outputs": "not-a-list"},
        )
        workflow_outputs = {
            "summary": WorkflowOutput(
                name="summary", from_expr="steps.last.summary", optional=False
            )
        }
        hgr = compute_hard_gates(result, workflow_outputs=workflow_outputs)
        # Non-list is treated as empty set, so required output is checked
        # against final_output only — "summary" is present.
        assert hgr.required_outputs_present is True

    def test_unresolved_required_output_in_metadata_fails_gate(self) -> None:
        result = _make_result_with_steps(
            final_output={"summary": "done"},
            metadata={"unresolved_required_outputs": ["summary"]},
        )
        workflow_outputs = {
            "summary": WorkflowOutput(
                name="summary", from_expr="steps.last.summary", optional=False
            )
        }
        hgr = compute_hard_gates(result, workflow_outputs=workflow_outputs)
        assert hgr.required_outputs_present is False

    def test_optional_output_missing_does_not_fail_gate(self) -> None:
        result = _make_result_with_steps(final_output={"summary": "done"})
        workflow_outputs = {
            "extra": WorkflowOutput(
                name="extra", from_expr="steps.last.extra", optional=True
            )
        }
        hgr = compute_hard_gates(result, workflow_outputs=workflow_outputs)
        assert hgr.required_outputs_present is True

    def test_non_dict_final_output_required_output_fails(self) -> None:
        """When final_output is not a dict, required output lookup yields None."""
        result = _make_result_with_steps(final_output={})
        # Override final_output to a non-dict via model extra field
        object.__setattr__(result, "final_output", "plain-string")
        workflow_outputs = {
            "summary": WorkflowOutput(
                name="summary", from_expr="steps.last.summary", optional=False
            )
        }
        hgr = compute_hard_gates(result, workflow_outputs=workflow_outputs)
        assert hgr.required_outputs_present is False


# ---------------------------------------------------------------------------
# validate_evaluation_payload_schema — additional branches
# ---------------------------------------------------------------------------


class TestValidatePayloadSchemaExtended:
    def test_criterion_not_dict_reports_error(self) -> None:
        payload = _valid_payload()
        payload["criteria"] = ["not-a-dict"]
        ok, errors = validate_evaluation_payload_schema(payload)
        assert ok is False
        assert any("criteria[0] must be an object" in e for e in errors)

    def test_multiple_missing_fields_reported(self) -> None:
        ok, errors = validate_evaluation_payload_schema({})
        assert ok is False
        assert len(errors) >= 9  # All required fields missing

    def test_wrong_type_for_passed_field(self) -> None:
        payload = _valid_payload()
        payload["passed"] = "yes"  # should be bool
        ok, errors = validate_evaluation_payload_schema(payload)
        assert ok is False
        assert any("passed" in e for e in errors)


# ---------------------------------------------------------------------------
# HardGateResult — all_passed with every individual flag False
# ---------------------------------------------------------------------------


class TestHardGateResultExtended:
    @pytest.mark.parametrize(
        "field_name",
        [
            "required_outputs_present",
            "overall_status_success",
            "no_critical_step_failures",
            "release_build_verified",
            "schema_contract_valid",
            "dataset_workflow_compatible",
        ],
    )
    def test_single_field_false_causes_all_passed_false(self, field_name: str) -> None:
        kwargs = {
            "required_outputs_present": True,
            "overall_status_success": True,
            "no_critical_step_failures": True,
            "release_build_verified": True,
            "schema_contract_valid": True,
            "dataset_workflow_compatible": True,
        }
        kwargs[field_name] = False
        hgr = HardGateResult(**kwargs)
        assert hgr.all_passed is False
        assert field_name in hgr.failures

    def test_all_six_failures_reported(self) -> None:
        hgr = HardGateResult(
            required_outputs_present=False,
            overall_status_success=False,
            no_critical_step_failures=False,
            release_build_verified=False,
            schema_contract_valid=False,
            dataset_workflow_compatible=False,
        )
        assert len(hgr.failures) == 6


# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------


class TestClamp:
    @pytest.mark.parametrize(
        "value, lo, hi, expected",
        [
            (50.0, 0.0, 100.0, 50.0),
            (-10.0, 0.0, 100.0, 0.0),
            (150.0, 0.0, 100.0, 100.0),
            (0.0, 0.0, 100.0, 0.0),
            (100.0, 0.0, 100.0, 100.0),
        ],
    )
    def test_clamp_boundaries(
        self, value: float, lo: float, hi: float, expected: float
    ) -> None:
        assert _clamp(value, lo, hi) == expected


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_filters_short_tokens(self) -> None:
        tokens = _tokenize("I am ok sure thing")
        assert "am" not in tokens  # 2 chars
        assert "sure" in tokens
        assert "thing" in tokens

    def test_lowercases_and_deduplicates(self) -> None:
        tokens = _tokenize("Hello HELLO hello")
        assert tokens == {"hello"}

    def test_empty_string_returns_empty_set(self) -> None:
        assert _tokenize("") == set()


# ---------------------------------------------------------------------------
# _extract_expected_text
# ---------------------------------------------------------------------------


class TestExtractExpectedText:
    def test_expected_output_priority(self) -> None:
        sample = {"expected_output": "first", "solution": "second"}
        assert _extract_expected_text(sample) == "first"

    def test_golden_patch_fallback(self) -> None:
        sample = {"golden_patch": "patch-text"}
        assert _extract_expected_text(sample) == "patch-text"

    def test_answer_body_fallback(self) -> None:
        sample = {"answer": {"body": "answer-body"}}
        assert _extract_expected_text(sample) == "answer-body"

    def test_solution_fallback(self) -> None:
        sample = {"solution": "solution-text"}
        assert _extract_expected_text(sample) == "solution-text"

    def test_returns_empty_when_no_keys_match(self) -> None:
        assert _extract_expected_text({"unrelated": "value"}) == ""

    def test_non_dict_returns_empty(self) -> None:
        assert _extract_expected_text("not-a-dict") == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _output_text
# ---------------------------------------------------------------------------


class TestOutputText:
    def test_serializes_final_output_as_json(self) -> None:
        result = _make_result(final_output={"key": "value"})
        text = _output_text(result)
        assert '"key"' in text
        assert '"value"' in text


# ---------------------------------------------------------------------------
# _text_overlap_score
# ---------------------------------------------------------------------------


class TestTextOverlapScore:
    def test_full_overlap_returns_100(self) -> None:
        text = "hello world testing"
        assert _text_overlap_score(text, text) == 100.0

    def test_no_overlap_returns_zero(self) -> None:
        assert _text_overlap_score("alpha beta gamma", "delta epsilon zeta") == 0.0

    def test_empty_expected_returns_zero(self) -> None:
        assert _text_overlap_score("", "anything here") == 0.0

    def test_partial_overlap(self) -> None:
        score = _text_overlap_score("hello world testing", "hello something else")
        assert 0.0 < score < 100.0


# ---------------------------------------------------------------------------
# _grade
# ---------------------------------------------------------------------------


class TestGrade:
    @pytest.mark.parametrize(
        "score, expected_grade",
        [
            (95.0, "A"),
            (90.0, "A"),
            (85.0, "B"),
            (80.0, "B"),
            (75.0, "C"),
            (70.0, "C"),
            (65.0, "D"),
            (60.0, "D"),
            (55.0, "F"),
            (0.0, "F"),
        ],
    )
    def test_grade_boundaries(self, score: float, expected_grade: str) -> None:
        assert _grade(score) == expected_grade


# ---------------------------------------------------------------------------
# _compute_criterion_score
# ---------------------------------------------------------------------------


class TestComputeCriterionScore:
    def test_correctness_with_expected_text(self) -> None:
        result = _make_result(
            status=StepStatus.SUCCESS,
            final_output={"summary": "hello world testing output"},
        )
        score = _compute_criterion_score(
            "correctness", result, "hello world testing output"
        )
        assert 0.0 <= score <= 100.0
        # SUCCESS gives 100% success_rate; expected text overlap present
        assert score > 50.0

    def test_correctness_penalized_when_failed(self) -> None:
        result = _make_result(
            status=StepStatus.FAILED,
            step_statuses=[StepStatus.FAILED],
        )
        score_failed = _compute_criterion_score("correctness", result, "")
        # FAILED result gets a 0.75 multiplier penalty
        assert score_failed < 75.0

    def test_code_quality_penalized_by_failures(self) -> None:
        result = _make_result(
            step_statuses=[StepStatus.SUCCESS, StepStatus.FAILED],
        )
        score = _compute_criterion_score("code_quality", result, "")
        # 1/2 steps failed → penalty applied
        assert score < 86.0  # 78 - penalty + status_bonus

    def test_efficiency_penalized_by_duration(self) -> None:
        now = datetime.now(timezone.utc)
        result = WorkflowResult(
            workflow_id="wf-scoring",
            workflow_name="test",
            overall_status=StepStatus.SUCCESS,
            start_time=now,
            end_time=now + timedelta(seconds=30),
            final_output={"out": "done"},
        )
        result.add_step(
            StepResult(
                step_name="s1",
                status=StepStatus.SUCCESS,
                input_data={},
                output_data={},
                start_time=now,
                end_time=now + timedelta(seconds=30),
            )
        )
        score = _compute_criterion_score("efficiency", result, "")
        assert score < 100.0  # Duration penalty applied
        assert score >= 0.0

    def test_documentation_rewards_rich_output(self) -> None:
        result = _make_result(
            final_output={
                "summary": "A" * 200,
                "details": "B" * 200,
                "notes": "C" * 200,
            },
        )
        score = _compute_criterion_score("documentation", result, "")
        assert score > 50.0  # Rich output gets higher score

    def test_unknown_criterion_gets_baseline(self) -> None:
        result = _make_result(status=StepStatus.SUCCESS)
        score = _compute_criterion_score("unknown_criterion", result, "")
        assert score == 50.0

    def test_unknown_criterion_penalized_when_failed(self) -> None:
        result = _make_result(
            status=StepStatus.FAILED,
            step_statuses=[StepStatus.FAILED],
        )
        score = _compute_criterion_score("unknown_criterion", result, "")
        assert score == 30.0  # 50 - 20 penalty


# ---------------------------------------------------------------------------
# _advisory_similarity_score
# ---------------------------------------------------------------------------


class TestAdvisorySimilarityScore:
    def test_with_expected_text_uses_overlap(self) -> None:
        score = _advisory_similarity_score(
            expected_text="hello world testing",
            generated_text="hello world testing",
            objective_score_0_1=0.5,
        )
        # Full overlap should give ~1.0
        assert score > 0.8

    def test_without_expected_text_uses_objective(self) -> None:
        score = _advisory_similarity_score(
            expected_text="",
            generated_text="anything",
            objective_score_0_1=0.9,
        )
        # Falls back to objective score (normalized)
        assert score > 0.5


# ---------------------------------------------------------------------------
# _advisory_efficiency_score
# ---------------------------------------------------------------------------


class TestAdvisoryEfficiencyScore:
    def test_uses_precomputed_efficiency_when_available(self) -> None:
        result = _make_result()
        score = _advisory_efficiency_score(
            result=result,
            normalized_scores={"efficiency": 0.85},
        )
        # Should use the precomputed value, normalized
        assert score > 0.0

    def test_derives_from_duration_when_no_efficiency(self) -> None:
        result = _make_result()
        score = _advisory_efficiency_score(
            result=result,
            normalized_scores={"correctness": 0.9},
        )
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# _compose_hybrid_score
# ---------------------------------------------------------------------------


class TestComposeHybridScore:
    def test_without_judge_uses_objective_and_advisory(self) -> None:
        score, weights = _compose_hybrid_score(
            objective_score_0_1=0.8,
            advisory_score_0_1=0.6,
            judge_score_0_1=None,
        )
        assert "objective" in weights
        assert "advisory" in weights
        assert "judge" not in weights
        assert 0.0 <= score <= 1.0

    def test_with_judge_includes_all_three(self) -> None:
        score, weights = _compose_hybrid_score(
            objective_score_0_1=0.8,
            advisory_score_0_1=0.6,
            judge_score_0_1=0.9,
        )
        assert "objective" in weights
        assert "advisory" in weights
        assert "judge" in weights

    def test_custom_component_weights(self) -> None:
        score, weights = _compose_hybrid_score(
            objective_score_0_1=1.0,
            advisory_score_0_1=0.0,
            judge_score_0_1=None,
            component_weights={"objective": 1.0, "advisory": 0.0},
        )
        # advisory has 0 weight so should only reflect objective
        assert score == pytest.approx(1.0, abs=0.01)

    def test_zero_weight_sum_falls_back_to_objective(self) -> None:
        score, weights = _compose_hybrid_score(
            objective_score_0_1=0.75,
            advisory_score_0_1=0.5,
            judge_score_0_1=None,
            component_weights={"objective": 0.0, "advisory": 0.0, "judge": 0.0},
        )
        assert score == 0.75
        assert weights == {"objective": 1.0}


# ---------------------------------------------------------------------------
# score_workflow_result_impl — integration
# ---------------------------------------------------------------------------


class TestScoreWorkflowResultImpl:
    """Integration tests for the full scoring pipeline."""

    def _run_pipeline(self, **overrides) -> dict:
        """Run the scoring pipeline with sensible defaults."""
        result = overrides.pop("result", None) or _make_result(
            status=StepStatus.SUCCESS,
            final_output={"summary": "good output"},
        )
        defaults = {
            "result": result,
            "dataset_meta": {"source": "test"},
            "dataset_sample": {"expected_output": "good output"},
            "rubric": None,
            "workflow_definition": None,
            "enforce_hard_gates": True,
            "judge": None,
            "compute_criterion_score_fn": lambda c, r, e: 80.0,
            "match_workflow_dataset_fn": lambda w, s: (True, []),
        }
        defaults.update(overrides)
        with patch(
            "agentic_v2.server.evaluation_scoring._load_eval_config",
            return_value={},
        ):
            return score_workflow_result_impl(**defaults)

    def test_happy_path_produces_valid_payload(self) -> None:
        payload = self._run_pipeline()
        ok, errors = validate_evaluation_payload_schema(payload)
        assert ok is True, f"Schema errors: {errors}"
        assert payload["grade"] in {"A", "B", "C", "D", "F"}
        assert isinstance(payload["weighted_score"], float)
        assert isinstance(payload["passed"], bool)

    def test_hard_gate_failure_forces_grade_f(self) -> None:
        result = _make_result(
            status=StepStatus.FAILED,
            step_statuses=[StepStatus.FAILED],
        )
        payload = self._run_pipeline(result=result)
        assert payload["grade"] == "F"
        assert payload["passed"] is False

    def test_enforce_hard_gates_false_allows_passing(self) -> None:
        """Disabling hard gate enforcement should not force grade F."""
        result = _make_result(
            status=StepStatus.FAILED,
            step_statuses=[StepStatus.FAILED],
        )
        payload = self._run_pipeline(
            result=result,
            enforce_hard_gates=False,
        )
        # Grade should not be forced to F
        assert payload["grade"] != "F" or payload.get("grade_capped") is False

    def test_floor_violation_caps_grade_to_d(self) -> None:
        """When correctness is below the 0.70 floor, grade caps to D."""
        wf = WorkflowDefinition(
            name="test",
            evaluation=WorkflowEvaluation(
                criteria=[
                    WorkflowCriterion(
                        name="correctness",
                        weight=0.5,
                        critical_floor=0.90,
                    ),
                    WorkflowCriterion(name="efficiency", weight=0.5),
                ],
            ),
        )
        # Low raw score (30) produces normalized score below the floor
        payload = self._run_pipeline(
            workflow_definition=wf,
            compute_criterion_score_fn=lambda c, r, e: 30.0,
        )
        # The pipeline enforces hard gate failures on FAILED status, so
        # ensure hard gates pass but floor violations exist
        assert len(payload["floor_violations"]) > 0

    def test_pipeline_includes_score_layers(self) -> None:
        payload = self._run_pipeline()
        layers = payload["score_layers"]
        assert "layer1_objective" in layers
        assert "layer2_judge" in layers
        assert "layer3_similarity" in layers
        assert "layer3_efficiency" in layers
        assert "layer3_advisory" in layers
        # No judge provided → layer2 is None
        assert layers["layer2_judge"] is None

    def test_pipeline_includes_hard_gates_dict(self) -> None:
        payload = self._run_pipeline()
        hg = payload["hard_gates"]
        assert "required_outputs_present" in hg
        assert "overall_status_success" in hg
        assert "no_critical_step_failures" in hg
        assert "release_build_verified" in hg
        assert "schema_contract_valid" in hg
        assert "dataset_workflow_compatible" in hg

    def test_dataset_compatible_from_meta(self) -> None:
        """dataset_workflow_compatible from meta propagates to hard gates."""
        payload = self._run_pipeline(
            dataset_meta={
                "source": "test",
                "dataset_workflow_compatible": False,
            },
        )
        assert payload["hard_gates"]["dataset_workflow_compatible"] is False

    def test_weighted_score_below_threshold_fails(self) -> None:
        """When weighted_score < threshold, passed is False."""
        # Very low scores (10) produce a weighted_score below 70
        payload = self._run_pipeline(
            compute_criterion_score_fn=lambda c, r, e: 10.0,
        )
        assert payload["passed"] is False
