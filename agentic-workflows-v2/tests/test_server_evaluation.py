"""Tests for server-side evaluation helpers.

# ADR-008 cleanup: removed 7 duplicate tests (see
docs/adr/ADR-008-testing-approach-overhaul.md)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from agentic_v2.contracts import StepResult, StepStatus, WorkflowResult
from agentic_v2.langchain import load_workflow_config
from agentic_v2.langchain.config import InputConfig, OutputConfig, WorkflowConfig
from agentic_v2.scoring.judge import LLMJudge
from agentic_v2.server import execution as execution_mod
from agentic_v2.server import result_normalization
from agentic_v2.server.evaluation import (
    adapt_sample_to_workflow_inputs,
    list_local_datasets,
    load_local_dataset_sample,
    match_workflow_dataset,
    score_workflow_result,
    validate_evaluation_payload_schema,
)
from agentic_v2.server.models import WorkflowEvaluationRequest, WorkflowRunRequest
from agentic_v2.server.routes import workflows as workflow_routes
from agentic_v2.workflows.loader import (
    WorkflowCriterion,
    WorkflowDefinition,
    WorkflowEvaluation,
    WorkflowInput,
    WorkflowLoader,
)
from tests._server_test_helpers import FAKE_TENANT, make_configured_app


def _build_result(status: StepStatus = StepStatus.SUCCESS) -> WorkflowResult:
    now = datetime.now(UTC)
    step = StepResult(
        step_name="analyze",
        status=status,
        input_data={"code": "def f(): pass"},
        output_data={"review": "Looks fine"},
        start_time=now,
        end_time=now + timedelta(milliseconds=420),
    )
    result = WorkflowResult(
        workflow_id="wf-test",
        workflow_name="code_review",
        overall_status=status,
        start_time=now,
        end_time=now + timedelta(milliseconds=550),
        final_output={"review": "Looks fine", "summary": "No critical issues."},
    )
    result.add_step(step)
    return result


def _build_workflow_definition() -> WorkflowConfig:
    return WorkflowConfig(
        name="code_review",
        inputs={
            "code_file": InputConfig(name="code_file", type="string", required=True),
            "review_depth": InputConfig(
                name="review_depth", type="string", required=False
            ),
        },
        outputs={
            "review": OutputConfig(
                name="review",
                from_expr="${steps.analyze.outputs.review}",
                optional=False,
            )
        },
    )


def _build_http_request() -> Request:
    app = make_configured_app()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/run",
        "headers": [],
        "app": app,
    }
    return Request(scope)


def test_list_local_datasets_includes_fixture_files():
    datasets = list_local_datasets()
    ids = {d["id"] for d in datasets}
    assert any(
        dataset_id.endswith(
            "agentic-workflows-v2/tests/fixtures/datasets/code_review_instruct.json"
        )
        for dataset_id in ids
    )


def test_load_local_dataset_sample_reads_fixture():
    sample, meta = load_local_dataset_sample(
        "agentic-workflows-v2/tests/fixtures/datasets/code_review_instruct.json",
        sample_index=0,
    )
    assert isinstance(sample, dict)
    assert meta["source"] == "local"
    assert "dataset_path" in meta


_GOLDEN_SMOKE_DATASET = (
    "agentic-workflows-v2/tests/fixtures/datasets/golden_cases_smoke.json"
)


def test_load_local_dataset_sample_resolves_golden_output_path():
    sample, meta = load_local_dataset_sample(_GOLDEN_SMOKE_DATASET, sample_index=0)
    assert "golden_output_error" not in meta
    golden_text = sample["golden_output_text"]
    # Reduced to the golden's final_output subtree, not the run envelope.
    assert "boundary contract" in golden_text
    assert "failed_steps" not in golden_text


def test_load_local_dataset_sample_missing_golden_records_error():
    sample, meta = load_local_dataset_sample(_GOLDEN_SMOKE_DATASET, sample_index=1)
    assert "golden_output_text" not in sample
    assert "unreadable" in meta["golden_output_error"]


def test_load_local_dataset_sample_golden_escape_rejected():
    sample, meta = load_local_dataset_sample(_GOLDEN_SMOKE_DATASET, sample_index=2)
    assert "golden_output_text" not in sample
    assert "escapes dataset roots" in meta["golden_output_error"]


def test_degenerate_golden_records_error():
    """A golden captured from a failed run (final_output: null) must not
    silently become the literal expected text "null"."""
    sample, meta = load_local_dataset_sample(_GOLDEN_SMOKE_DATASET, sample_index=3)
    assert "golden_output_text" not in sample
    assert "empty golden content" in meta["golden_output_error"]


def test_hollow_golden_records_error():
    """A golden whose final_output null-strips to {} (e.g. {"review": null})
    must not be inlined as tokenless expected text with
    expected_text_present=true."""
    sample, meta = load_local_dataset_sample(_GOLDEN_SMOKE_DATASET, sample_index=6)
    assert "golden_output_text" not in sample
    assert "empty golden content" in meta["golden_output_error"]


def test_nested_hollow_golden_records_error():
    """Structural keys must not count as golden content: {"review": {"body":
    null}} null-strips to {"review": {}} whose serialized keys tokenize."""
    sample, meta = load_local_dataset_sample(_GOLDEN_SMOKE_DATASET, sample_index=7)
    assert "golden_output_text" not in sample
    assert "empty golden content" in meta["golden_output_error"]


def test_tokenless_golden_records_error(tmp_path, monkeypatch):
    """A golden with content leaves but zero scoring tokens (e.g. all short
    numerics) cannot participate in overlap scoring — reject it loudly."""
    from agentic_v2.server import datasets as datasets_mod

    monkeypatch.setattr(
        datasets_mod, "_local_dataset_roots", lambda _tid=None: [tmp_path]
    )
    (tmp_path / "numeric_golden.json").write_text(
        '{"final_output": {"n": 42}}', encoding="utf-8"
    )
    sample = {"golden_output_path": "numeric_golden.json"}
    resolved, error = datasets_mod._resolve_golden_output_text(
        sample, tmp_path / "ds.json"
    )
    assert resolved == sample
    assert "empty golden content" in error


def test_blank_golden_path_records_error():
    sample, meta = load_local_dataset_sample(_GOLDEN_SMOKE_DATASET, sample_index=4)
    assert "golden_output_text" not in sample
    assert "not a usable path" in meta["golden_output_error"]


def test_inline_expected_output_short_circuits_golden_read():
    sample, meta = load_local_dataset_sample(_GOLDEN_SMOKE_DATASET, sample_index=5)
    assert "golden_output_text" not in sample
    assert "golden_output_error" not in meta
    assert sample["expected_output"] == "inline expected text wins precedence"


def test_non_utf8_golden_records_error_not_crash(tmp_path, monkeypatch):
    """Regression: UnicodeDecodeError is a ValueError, not an OSError — a
    UTF-16 golden must degrade loudly, not crash the whole dataset load."""
    from agentic_v2.server import datasets as datasets_mod

    monkeypatch.setattr(
        datasets_mod, "_local_dataset_roots", lambda _tid=None: [tmp_path]
    )
    (tmp_path / "bad_golden.json").write_bytes(
        '{"final_output": {"review": "text"}}'.encode("utf-16")
    )
    sample = {"golden_output_path": "bad_golden.json"}
    resolved, error = datasets_mod._resolve_golden_output_text(
        sample, tmp_path / "ds.json"
    )
    assert resolved == sample
    assert "UnicodeDecodeError" in error


def test_rehydrate_unparseable_index_bails_loudly():
    from agentic_v2.server.evaluation import rehydrate_dataset_sample

    meta = {
        "source": "local",
        "dataset_id": _GOLDEN_SMOKE_DATASET,
        "sample_index": "n/a",
        "task_id": "golden_smoke_ok",
    }
    sample, error = rehydrate_dataset_sample(meta)
    assert sample is None
    assert "unusable" in error


def test_rehydrate_task_id_mismatch_bails_loudly():
    """A dataset that shrank/reordered since the run must not silently swap
    in a different task's golden."""
    from agentic_v2.server.evaluation import rehydrate_dataset_sample

    meta = {
        "source": "local",
        "dataset_id": _GOLDEN_SMOKE_DATASET,
        "sample_index": 0,
        "task_id": "some_other_task",
    }
    sample, error = rehydrate_dataset_sample(meta)
    assert sample is None
    assert "task_id mismatch" in error


def test_rehydrate_numeric_task_id_still_verified():
    """Integer task ids (common in numeric benchmarks) must not silently
    bypass the mismatch verification."""
    from agentic_v2.server.evaluation import rehydrate_dataset_sample

    meta = {
        "source": "local",
        "dataset_id": _GOLDEN_SMOKE_DATASET,
        "sample_index": 0,
        "task_id": 5,
    }
    sample, error = rehydrate_dataset_sample(meta)
    assert sample is None
    assert "task_id mismatch" in error


def test_rehydrate_propagates_golden_error():
    from agentic_v2.server.evaluation import rehydrate_dataset_sample

    meta = {
        "source": "local",
        "dataset_id": _GOLDEN_SMOKE_DATASET,
        "sample_index": 1,
        "task_id": "golden_smoke_missing",
    }
    sample, error = rehydrate_dataset_sample(meta)
    assert sample is not None
    assert "unreadable" in error


def _build_generated_result(content: str, duration_s: float) -> WorkflowResult:
    start = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
    result = WorkflowResult(
        workflow_id=f"wf-diff-{duration_s}",
        workflow_name="code_review",
        overall_status=StepStatus.SUCCESS,
        start_time=start,
        end_time=start + timedelta(seconds=duration_s),
        final_output={"review": content, "summary": content},
    )
    result.add_step(
        StepResult(
            step_name="analyze",
            status=StepStatus.SUCCESS,
            input_data={},
            output_data={"review": content},
            start_time=start,
            end_time=start + timedelta(seconds=duration_s),
        )
    )
    return result


def test_issue_172_distinct_runs_score_distinctly_with_loaded_golden():
    """Regression for issue #172: three synthetic runs with different content
    and durations all scored an identical 83.97/B because the golden never
    loaded, the judge silently skipped, and the duration penalty saturated.
    With the golden resolved by the loader, differing runs must diverge."""
    sample, _meta = load_local_dataset_sample(_GOLDEN_SMOKE_DATASET, sample_index=0)
    on_golden = _build_generated_result(
        "The clamp function raises TypeError when lower exceeds upper instead "
        "of honoring the boundary contract; violation detected in clamp "
        "implementation",
        duration_s=45.0,
    )
    off_golden = _build_generated_result(
        "totally unrelated artifact text mentioning nothing relevant",
        duration_s=300.0,
    )
    eval_on = score_workflow_result(on_golden, dataset_meta=None, dataset_sample=sample)
    eval_off = score_workflow_result(
        off_golden, dataset_meta=None, dataset_sample=sample
    )
    assert eval_on["weighted_score"] > eval_off["weighted_score"]
    # Key-free run: the judge layer is absent and the skip must be loud.
    assert eval_on["judge_skipped"] is True
    assert eval_on["judge_skip_reason"] == "no judge configured"
    assert eval_on["expected_text_present"] is True

    # Content-only divergence: same duration, different content must still
    # separate by a real margin (not just a float-noise inequality) — the
    # duration term cannot mask a dead overlap term.
    same_duration_off = _build_generated_result(
        "totally unrelated artifact text mentioning nothing relevant",
        duration_s=45.0,
    )
    eval_same_duration = score_workflow_result(
        same_duration_off, dataset_meta=None, dataset_sample=sample
    )
    assert eval_on["weighted_score"] - eval_same_duration["weighted_score"] >= 1.0


def test_adapt_sample_to_workflow_inputs_materializes_file(tmp_path: Path):
    schema = {
        "code_file": WorkflowInput(name="code_file", type="string", required=True),
        "review_depth": WorkflowInput(
            name="review_depth", type="string", required=False
        ),
    }
    sample = {
        "prompt": "Review this code",
        "code": "def add(a, b):\n    return a + b\n",
    }
    adapted = adapt_sample_to_workflow_inputs(
        schema,
        sample,
        run_id="wf-adapt",
        artifacts_dir=tmp_path,
    )
    assert "code_file" in adapted
    path = Path(adapted["code_file"])
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("def add")


def test_score_workflow_result_includes_all_criteria():
    result = _build_result(StepStatus.SUCCESS)
    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"expected_output": "No critical issues"},
        rubric="workflow_default",
    )
    assert evaluation["enabled"] is True
    assert "criteria" in evaluation
    assert len(evaluation["criteria"]) >= 4
    assert 0 <= evaluation["weighted_score"] <= 100
    assert evaluation["grade"] in {"A", "B", "C", "D", "F"}
    assert "hard_gates" in evaluation
    assert "hard_gate_failures" in evaluation
    assert "floor_violations" in evaluation


def test_criterion_result_stores_both_scores():
    evaluation = score_workflow_result(
        _build_result(StepStatus.SUCCESS),
        dataset_meta={"source": "local"},
        dataset_sample={"expected_output": "No critical issues"},
    )
    first = evaluation["criteria"][0]
    assert "raw_score" in first
    assert "normalized_score" in first


def test_hard_gate_all_pass_with_score(monkeypatch):
    # Provide a guaranteed-passing criterion score so the test can verify that
    # when all hard gates pass AND weighted_score >= pass_threshold, passed=True.
    # The real criterion scorer produces ~35 for a synthetic test double (short
    # output, no expected text), which is below the 70.0 threshold — that is
    # correct behaviour for the scorer but not the point of this test.
    monkeypatch.setattr(
        "agentic_v2.server.evaluation._compute_criterion_score",
        lambda *_args, **_kwargs: 85.0,
    )
    result = _build_result(StepStatus.SUCCESS)
    workflow_def = _build_workflow_definition()

    monkeypatch.setattr(
        "agentic_v2.server.evaluation._compute_criterion_score",
        lambda *_args, **_kwargs: 95.0,
    )

    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=workflow_def,
    )
    assert evaluation["hard_gate_failures"] == []
    assert evaluation["weighted_score"] >= evaluation["pass_threshold"]
    assert evaluation["passed"] is True


def test_hard_gate_all_pass_low_score(monkeypatch):
    result = _build_result(StepStatus.SUCCESS)

    def _low_score(*_args, **_kwargs):
        return 20.0

    monkeypatch.setattr(
        "agentic_v2.server.evaluation._compute_criterion_score", _low_score
    )
    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=_build_workflow_definition(),
    )
    assert evaluation["hard_gate_failures"] == []
    assert evaluation["weighted_score"] < evaluation["pass_threshold"]
    assert evaluation["passed"] is False


def test_criterion_floor_correctness_caps_grade(monkeypatch):
    result = _build_result(StepStatus.SUCCESS)

    def _scores(criterion: str, *_args):
        if criterion in {"correctness", "correctness_rubric"}:
            # Below 0.70 floor after normalization, but high enough aggregate
            # score to prove floor-based grade capping.
            return 69.0
        return 95.0

    monkeypatch.setattr(
        "agentic_v2.server.evaluation._compute_criterion_score", _scores
    )
    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=WorkflowDefinition(
            name="floor_test",
            outputs=_build_workflow_definition().outputs,
            evaluation=WorkflowEvaluation(
                criteria=[
                    WorkflowCriterion(
                        name="correctness_rubric",
                        scale={"1": "bad", "5": "good"},
                        weight=0.8,
                        formula_id="zero_one",
                    ),
                    WorkflowCriterion(
                        name="code_quality",
                        scale={"1": "bad", "5": "good"},
                        weight=0.2,
                        formula_id="zero_one",
                    ),
                ]
            ),
        ),
    )
    assert evaluation["weighted_score"] >= 70
    assert evaluation["grade"] == "D"
    assert evaluation["grade_capped"] is True
    assert evaluation["passed"] is False


def test_criterion_floor_all_pass():
    result = _build_result(StepStatus.SUCCESS)
    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=_build_workflow_definition(),
    )
    assert evaluation["grade_capped"] is False


def test_match_workflow_dataset_compatible():
    workflow_def = _build_workflow_definition()
    compatible, reasons = match_workflow_dataset(
        workflow_def,
        {"code_file": "x.py"},
    )
    assert compatible is True
    assert reasons == []


def test_match_workflow_dataset_missing_field():
    workflow_def = _build_workflow_definition()
    compatible, reasons = match_workflow_dataset(
        workflow_def,
        {"prompt": ""},
    )
    assert compatible is False
    assert "missing: code_file" in reasons


def test_match_workflow_dataset_chat_messages_uses_defaults_for_fullstack():
    loader = WorkflowLoader()
    workflow_def = loader.load("fullstack_generation")
    sample, _meta = load_local_dataset_sample(
        "agentic-workflows-v2/tests/fixtures/datasets/react_code_instructions.json",
        sample_index=4,
    )
    compatible, reasons = match_workflow_dataset(workflow_def, sample)
    assert compatible is True
    assert reasons == []


def test_adapt_sample_to_workflow_inputs_extracts_feature_spec_from_messages(
    tmp_path: Path,
):
    schema = {
        "feature_spec": WorkflowInput(
            name="feature_spec", type="string", required=True
        ),
        "tech_stack": WorkflowInput(
            name="tech_stack",
            type="object",
            required=True,
            default={
                "frontend": "react",
                "backend": "fastapi",
                "database": "postgresql",
            },
        ),
    }
    sample = {
        "messages": [
            {"role": "system", "content": "Build modern apps."},
            {"role": "user", "content": "create a tetris game"},
        ]
    }

    adapted = adapt_sample_to_workflow_inputs(
        schema,
        sample,
        run_id="wf-messages",
        artifacts_dir=tmp_path,
    )
    assert adapted["feature_spec"] == "create a tetris game"
    assert isinstance(adapted["tech_stack"], dict)
    assert adapted["tech_stack"]["backend"] == "fastapi"


def test_validate_evaluation_payload_schema_detects_missing_fields():
    ok, errors = validate_evaluation_payload_schema({"rubric_id": "x"})
    assert ok is False
    assert errors


def test_rubric_loaded_from_workflow_yaml():
    workflow_def = load_workflow_config("code_review")
    result = _build_result(StepStatus.SUCCESS)
    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=workflow_def,
    )
    assert evaluation["rubric_id"] == "code_review_v1"
    criteria = {item["criterion"] for item in evaluation["criteria"]}
    assert "correctness_rubric" in criteria


def test_rubric_request_override():
    workflow_def = load_workflow_config("code_review")
    result = _build_result(StepStatus.SUCCESS)
    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=workflow_def,
        rubric="override_rubric",
    )
    assert evaluation["rubric_id"] == "override_rubric"


def test_rubric_invalid_weights_rejected():
    workflow_def = WorkflowDefinition(
        name="bad_weights",
        evaluation=WorkflowEvaluation(
            weights={"correctness": 0.9, "code_quality": 0.9},
        ),
    )
    with pytest.raises(ValueError, match="sum to 1.0"):
        score_workflow_result(
            _build_result(StepStatus.SUCCESS),
            dataset_meta={"source": "local"},
            dataset_sample={"code_file": "x.py"},
            workflow_definition=workflow_def,
        )


def test_rubric_missing_uses_global_default():
    result = _build_result(StepStatus.SUCCESS)
    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
    )
    assert evaluation["rubric_id"] == "workflow_default"


def test_scoring_profile_applies_defaults():
    workflow_def = WorkflowDefinition(
        name="profile_defaults",
        outputs=_build_workflow_definition().outputs,
        evaluation=WorkflowEvaluation(scoring_profile="A"),
    )
    evaluation = score_workflow_result(
        _build_result(StepStatus.SUCCESS),
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=workflow_def,
    )
    weights = {item["criterion"]: item["weight"] for item in evaluation["criteria"]}
    assert weights["objective_tests"] == pytest.approx(0.60)


def test_scoring_profile_overridable():
    workflow_def = WorkflowDefinition(
        name="profile_override",
        outputs=_build_workflow_definition().outputs,
        evaluation=WorkflowEvaluation(
            scoring_profile="A",
            weights={
                "objective_tests": 0.40,
                "code_quality": 0.30,
                "efficiency": 0.20,
                "documentation": 0.10,
            },
        ),
    )
    evaluation = score_workflow_result(
        _build_result(StepStatus.SUCCESS),
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=workflow_def,
    )
    weights = {item["criterion"]: item["weight"] for item in evaluation["criteria"]}
    assert weights["objective_tests"] == pytest.approx(0.40)


def test_hybrid_score_without_judge():
    result = _build_result(StepStatus.SUCCESS)
    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=_build_workflow_definition(),
    )
    assert evaluation["judge"] is None
    assert evaluation["score_layers"]["layer2_judge"] is None
    assert evaluation["hybrid_weights"].keys() == {"objective", "advisory"}


def test_hybrid_score_with_mock_judge():
    def _provider(*, prompt: str, model: str, temperature: float):
        assert "Schema" in prompt
        return {
            "criteria": [
                {"name": "correctness", "score": 2, "evidence": "missed edge cases"},
                {
                    "name": "code_quality",
                    "score": 2,
                    "evidence": "style and structure issues",
                },
                {"name": "efficiency", "score": 2, "evidence": "slow with retries"},
                {"name": "documentation", "score": 2, "evidence": "thin summary"},
            ]
        }

    result = _build_result(StepStatus.SUCCESS)
    without_judge = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=_build_workflow_definition(),
    )
    with_judge = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=_build_workflow_definition(),
        judge=LLMJudge(response_provider=_provider, model_version="mock-judge-1"),
    )
    assert with_judge["weighted_score"] < without_judge["weighted_score"]
    assert with_judge["judge"] is not None
    assert with_judge["score_layers"]["layer2_judge"] is not None


def test_hybrid_score_with_mock_judge_and_workflow_config_criteria():
    def _provider(*, prompt: str, model: str, temperature: float):
        assert "correctness_rubric" in prompt
        return {
            "criteria": [
                {
                    "name": "correctness_rubric",
                    "score": 4,
                    "evidence": "mostly correct review output",
                },
                {
                    "name": "code_quality",
                    "score": 4,
                    "evidence": "clear structure and findings",
                },
                {
                    "name": "efficiency",
                    "score": 3,
                    "evidence": "reasonable latency",
                },
                {
                    "name": "documentation",
                    "score": 4,
                    "evidence": "useful summary",
                },
            ]
        }

    workflow_def = load_workflow_config("code_review")
    evaluation = score_workflow_result(
        _build_result(StepStatus.SUCCESS),
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=workflow_def,
        judge=LLMJudge(response_provider=_provider, model_version="mock-judge-scale"),
    )

    assert evaluation["judge"] is not None
    assert evaluation["score_layers"]["layer2_judge"] is not None
    assert evaluation["weighted_score"] > 0


def test_hybrid_hard_gates_still_override():
    def _provider(*, prompt: str, model: str, temperature: float):
        return {
            "criteria": [
                {"name": "correctness", "score": 5, "evidence": "excellent"},
                {"name": "code_quality", "score": 5, "evidence": "excellent"},
                {"name": "efficiency", "score": 5, "evidence": "excellent"},
                {"name": "documentation", "score": 5, "evidence": "excellent"},
            ]
        }

    result = _build_result(StepStatus.SUCCESS)
    result.final_output = {}
    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=_build_workflow_definition(),
        judge=LLMJudge(response_provider=_provider, model_version="mock-judge-2"),
    )
    assert evaluation["score_layers"]["layer2_judge"] is not None
    assert evaluation["passed"] is False
    assert evaluation["grade"] == "F"
    assert "required_outputs_present" in evaluation["hard_gate_failures"]


def test_hard_gate_release_build_verification_overrides_pass():
    result = _build_result(StepStatus.SUCCESS)
    now = datetime.now(UTC)
    result.add_step(
        StepResult(
            step_name="build_verify_release",
            status=StepStatus.SUCCESS,
            input_data={},
            output_data={"ready_for_release": False},
            start_time=now,
            end_time=now + timedelta(milliseconds=10),
        )
    )

    evaluation = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=_build_workflow_definition(),
    )
    assert evaluation["passed"] is False
    assert evaluation["hard_gates"]["release_build_verified"] is False
    assert "release_build_verified" in evaluation["hard_gate_failures"]


def test_hybrid_score_determinism():
    def _provider(*, prompt: str, model: str, temperature: float):
        return {
            "criteria": [
                {"name": "correctness", "score": 4, "evidence": "solid"},
                {"name": "code_quality", "score": 4, "evidence": "solid"},
                {"name": "efficiency", "score": 4, "evidence": "solid"},
                {"name": "documentation", "score": 4, "evidence": "solid"},
            ]
        }

    judge = LLMJudge(
        response_provider=_provider, model_version="mock-judge-deterministic"
    )
    result = _build_result(StepStatus.SUCCESS)
    first = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=_build_workflow_definition(),
        judge=judge,
    )
    second = score_workflow_result(
        result,
        dataset_meta={"source": "local"},
        dataset_sample={"code_file": "x.py"},
        workflow_definition=_build_workflow_definition(),
        judge=judge,
    )
    assert first["weighted_score"] == pytest.approx(
        second["weighted_score"], abs=0.0001
    )


@pytest.mark.asyncio
async def test_sse_payload_includes_hard_gates(monkeypatch):
    events: list[dict] = []

    def _mock_load_config(name, definitions_dir=None):
        from agentic_v2.langchain.config import WorkflowConfig

        return WorkflowConfig(name=name, inputs={}, outputs={}, steps=[])

    async def _fake_run(*_args, **_kwargs):
        return _build_result(StepStatus.SUCCESS)

    async def _fake_broadcast(_run_id: str, event: dict):
        events.append(event)

    monkeypatch.setattr(workflow_routes, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(execution_mod, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        result_normalization,
        "load_local_dataset_sample",
        lambda *_a, **_k: ({}, {"source": "local"}),
    )
    monkeypatch.setattr(
        result_normalization, "adapt_sample_to_workflow_inputs", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        execution_mod, "_get_lc_runner", lambda: type("R", (), {"run": _fake_run})()
    )
    monkeypatch.setattr(execution_mod.websocket.manager, "broadcast", _fake_broadcast)
    monkeypatch.setattr(
        execution_mod.run_logger, "log", lambda *_a, **_k: Path("dummy.json")
    )

    request = WorkflowRunRequest(
        workflow="dummy_workflow",
        evaluation=WorkflowEvaluationRequest(
            enabled=True,
            dataset_source="local",
            dataset_id="dummy.json",
        ),
    )
    background = BackgroundTasks()
    await workflow_routes.run_workflow(
        request, background, _build_http_request(), FAKE_TENANT
    )
    for task in background.tasks:
        await task()

    evaluation_events = [
        event for event in events if event.get("type") == "evaluation_complete"
    ]
    assert evaluation_events
    event = evaluation_events[-1]
    assert "hard_gates" in event
    assert "hard_gate_failures" in event
    # Visibility flags must ride the live frame — the live evaluation card is
    # populated only from this event (issue #172 review, round 8).
    assert event["judge_skipped"] is True
    assert "judge_skip_code" in event
    assert event["expected_text_present"] is False


@pytest.mark.asyncio
async def test_run_log_evaluation_has_gate_fields(monkeypatch):
    captured: dict = {}

    async def _fake_run(*_args, **_kwargs):
        return _build_result(StepStatus.SUCCESS)

    async def _fake_broadcast(_run_id: str, _event: dict):
        return None

    def _fake_log(*_args, **kwargs):
        captured.update(kwargs)
        return Path("dummy.json")

    def _mock_load_config(name, definitions_dir=None):
        from agentic_v2.langchain.config import WorkflowConfig

        return WorkflowConfig(name=name, inputs={}, outputs={}, steps=[])

    monkeypatch.setattr(workflow_routes, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(execution_mod, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        result_normalization,
        "load_local_dataset_sample",
        lambda *_a, **_k: ({}, {"source": "local"}),
    )
    monkeypatch.setattr(
        result_normalization, "adapt_sample_to_workflow_inputs", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        execution_mod, "_get_lc_runner", lambda: type("R", (), {"run": _fake_run})()
    )
    monkeypatch.setattr(execution_mod.websocket.manager, "broadcast", _fake_broadcast)

    # execution.py calls run_logger.for_tenant(tenant_id).log(...) — patch
    # for_tenant to return a stub whose .log captures kwargs.
    class _FakeLogger:
        def log(self, *_args, **kwargs):
            captured.update(kwargs)
            return Path("dummy.json")

    monkeypatch.setattr(
        execution_mod.run_logger, "for_tenant", lambda _tid: _FakeLogger()
    )

    request = WorkflowRunRequest(
        workflow="dummy_workflow",
        run_id="test-run-id",
        adapter="default",
        execution_profile="default",
        evaluation=WorkflowEvaluationRequest(
            enabled=True,
            dataset_source="local",
            dataset_id="dummy.json",
        ),
    )
    background = BackgroundTasks()
    await workflow_routes.run_workflow(
        request, background, _build_http_request(), FAKE_TENANT
    )
    for task in background.tasks:
        await task()

    evaluation_payload = captured["extra"]["evaluation"]
    assert "hard_gates" in evaluation_payload
    assert "hard_gate_failures" in evaluation_payload
    assert "step_scores" in evaluation_payload


@pytest.mark.asyncio
async def test_run_log_persists_when_judge_required_unmet(monkeypatch):
    """judge_required=true fails the *evaluation*, never the run record: a
    completed workflow must not vanish from run history (issue #172 review),
    and the live stream must get a terminal event or the UI sticks in
    "evaluating"."""
    captured: dict = {}
    events: list[dict] = []

    async def _fake_run(*_args, **_kwargs):
        return _build_result(StepStatus.SUCCESS)

    async def _fake_broadcast(_run_id: str, event: dict):
        events.append(event)

    def _mock_load_config(name, definitions_dir=None):
        from agentic_v2.langchain.config import WorkflowConfig

        return WorkflowConfig(name=name, inputs={}, outputs={}, steps=[])

    monkeypatch.setattr(workflow_routes, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(execution_mod, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        result_normalization,
        "load_local_dataset_sample",
        lambda *_a, **_k: ({}, {"source": "local"}),
    )
    monkeypatch.setattr(
        result_normalization, "adapt_sample_to_workflow_inputs", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        execution_mod, "_get_lc_runner", lambda: type("R", (), {"run": _fake_run})()
    )
    monkeypatch.setattr(execution_mod.websocket.manager, "broadcast", _fake_broadcast)
    # Force the judge-required policy on; the key-free judge then escalates.
    monkeypatch.setattr(
        "agentic_v2.scoring.evaluation_scoring._load_eval_config",
        lambda: {"evaluation": {"scoring": {"judge_required": True}}},
    )

    class _FakeLogger:
        def log(self, *_args, **kwargs):
            captured.update(kwargs)
            return Path("dummy.json")

    monkeypatch.setattr(
        execution_mod.run_logger, "for_tenant", lambda _tid: _FakeLogger()
    )

    request = WorkflowRunRequest(
        workflow="dummy_workflow",
        run_id="judge-required-run",
        evaluation=WorkflowEvaluationRequest(
            enabled=True,
            dataset_source="local",
            dataset_id="dummy.json",
        ),
    )
    background = BackgroundTasks()
    await workflow_routes.run_workflow(
        request, background, _build_http_request(), FAKE_TENANT
    )
    for task in background.tasks:
        await task()

    # The run log was still written, with the policy failure recorded.
    assert captured["extra"]["evaluation"] is None
    assert "judge_required" in captured["extra"]["evaluation_error"]

    # evaluation_start went out, so a terminal event must follow — otherwise
    # the live UI never leaves the "evaluating" state.
    event_types = [event.get("type") for event in events]
    assert "evaluation_start" in event_types
    assert "error" in event_types
    assert "evaluation_complete" not in event_types


@pytest.mark.asyncio
async def test_sse_payload_schema_validation(monkeypatch):
    events: list[dict] = []

    async def _fake_run(*_args, **_kwargs):
        return _build_result(StepStatus.SUCCESS)

    async def _fake_broadcast(_run_id: str, event: dict):
        events.append(event)

    def _mock_load_config(name, definitions_dir=None):
        from agentic_v2.langchain.config import WorkflowConfig

        return WorkflowConfig(name=name, inputs={}, outputs={}, steps=[])

    monkeypatch.setattr(workflow_routes, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(execution_mod, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        result_normalization,
        "load_local_dataset_sample",
        lambda *_a, **_k: ({}, {"source": "local"}),
    )
    monkeypatch.setattr(
        result_normalization, "adapt_sample_to_workflow_inputs", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        execution_mod, "_get_lc_runner", lambda: type("R", (), {"run": _fake_run})()
    )
    monkeypatch.setattr(execution_mod.websocket.manager, "broadcast", _fake_broadcast)
    monkeypatch.setattr(
        execution_mod.run_logger, "log", lambda *_a, **_k: Path("dummy.json")
    )

    request = WorkflowRunRequest(
        workflow="dummy_workflow",
        evaluation=WorkflowEvaluationRequest(
            enabled=True,
            dataset_source="local",
            dataset_id="dummy.json",
        ),
    )
    background = BackgroundTasks()
    await workflow_routes.run_workflow(
        request, background, _build_http_request(), FAKE_TENANT
    )
    for task in background.tasks:
        await task()

    evaluation_events = [
        event for event in events if event.get("type") == "evaluation_complete"
    ]
    assert evaluation_events
    payload = evaluation_events[-1]
    assert isinstance(payload["hard_gates"], dict)
    assert isinstance(payload["hard_gate_failures"], list)
    assert isinstance(payload["rubric_id"], str)
    assert isinstance(payload["rubric_version"], str)
    assert isinstance(payload["step_scores"], list)


@pytest.mark.asyncio
async def test_run_workflow_preserves_422_for_invalid_repository_dataset(monkeypatch):
    def _mock_load_config(name, definitions_dir=None):
        from agentic_v2.langchain.config import WorkflowConfig

        return WorkflowConfig(name=name, inputs={}, outputs={}, steps=[])

    monkeypatch.setattr(workflow_routes, "load_workflow_config", _mock_load_config)
    request = WorkflowRunRequest(
        workflow="dummy_workflow",
        evaluation=WorkflowEvaluationRequest(
            enabled=True,
            dataset_source="repository",
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await workflow_routes.run_workflow(
            request,
            BackgroundTasks(),
            _build_http_request(),
            FAKE_TENANT,
        )

    assert exc_info.value.status_code == 422
    assert "dataset_id is required" in str(exc_info.value.detail)
