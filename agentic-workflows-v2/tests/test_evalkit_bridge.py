"""Tests for agentic_v2.scoring.evalkit_bridge (ADR-042, Slice B).

Skips cleanly (module-level ``importorskip``) in any environment without
``agentic-evalkit`` installed — it is an optional dependency until the
library has a public git remote, so CI for ``agentic-workflows-v2`` does not
install it. ``agentic_v2_eval`` (the legacy in-tree package) IS installed in
ARP dev/CI environments, so ``Scorer`` parity comparisons import it directly
rather than mocking it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

agentic_evalkit = pytest.importorskip("agentic_evalkit")

from agentic_evalkit.models import EvalSample, ExecutionStatus
from agentic_v2_eval.rubrics import RUBRICS_DIR, load_rubric
from agentic_v2_eval.scorer import Scorer

from agentic_v2.scoring import evalkit_bridge

# ---------------------------------------------------------------------------
# Rubric conversion
# ---------------------------------------------------------------------------


def test_rubric_from_yaml_dict_converts_real_code_rubric() -> None:
    # Arrange
    rubric_data = load_rubric("code")

    # Act
    rubric = evalkit_bridge.rubric_from_yaml_dict(rubric_data)

    # Assert
    assert rubric.rubric_id  # non-empty; code.yaml has no explicit `name` key
    criterion_ids = [criterion.criterion_id for criterion in rubric.criteria]
    assert criterion_ids == [
        "Correctness",
        "Completeness",
        "Code Quality",
        "Efficiency",
        "Security",
    ]
    correctness = rubric.criteria[0]
    assert correctness.weight == pytest.approx(0.30)
    assert correctness.scale == "bounded"
    assert correctness.scale_min == 0.0
    assert correctness.scale_max == 1.0
    assert correctness.requires_evidence is True
    assert correctness.hard_gate is False
    assert "correct output" in correctness.description.lower()


def test_rubric_from_yaml_dict_default_rubric_has_no_thresholds_or_metadata() -> None:
    # Arrange
    rubric_data = load_rubric("default")

    # Act
    rubric = evalkit_bridge.rubric_from_yaml_dict(rubric_data)

    # Assert
    assert len(rubric.criteria) == 3
    assert {c.criterion_id for c in rubric.criteria} == {
        "Accuracy",
        "Completeness",
        "Efficiency",
    }


def test_rubric_from_yaml_dict_missing_weight_defaults_to_one() -> None:
    # Arrange
    rubric_data: dict[str, Any] = {
        "criteria": [{"name": "OnlyCriterion", "description": "no weight given"}]
    }

    # Act
    rubric = evalkit_bridge.rubric_from_yaml_dict(rubric_data)

    # Assert
    assert rubric.criteria[0].weight == 1.0


def test_rubric_from_yaml_dict_raises_on_empty_criteria() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="criteria"):
        evalkit_bridge.rubric_from_yaml_dict({"criteria": []})


def test_rubric_from_yaml_dict_raises_on_missing_name_key() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="name"):
        evalkit_bridge.rubric_from_yaml_dict({"criteria": [{"weight": 1.0}]})


def test_rubric_from_yaml_dict_raises_when_evalkit_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(evalkit_bridge, "EVALKIT_AVAILABLE", False)

    # Act / Assert
    with pytest.raises(RuntimeError, match="not installed"):
        evalkit_bridge.rubric_from_yaml_dict({"criteria": [{"name": "X"}]})


# ---------------------------------------------------------------------------
# Score parity with the legacy Scorer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rubric_name", sorted({"code", "agent", "default"}))
@pytest.mark.parametrize(
    "criterion_scores",
    [
        pytest.param(None, id="all-criteria-scored"),
        pytest.param("partial", id="missing-criterion"),
        pytest.param("empty", id="all-missing"),
    ],
)
def test_score_criteria_matches_legacy_scorer(
    rubric_name: str, criterion_scores: str | None
) -> None:
    # Arrange
    rubric_data = load_rubric(rubric_name)
    all_names = [criterion["name"] for criterion in rubric_data["criteria"]]
    if criterion_scores is None:
        scores = {name: 0.6 + 0.1 * index for index, name in enumerate(all_names)}
    elif criterion_scores == "partial":
        scores = {all_names[0]: 0.5}
    else:
        scores = {}

    # Act
    legacy_result = Scorer(rubric_data).score(scores)
    bridged_score = evalkit_bridge.score_criteria(rubric_data, scores)

    # Assert
    assert bridged_score == pytest.approx(legacy_result.weighted_score)


def test_score_criteria_matches_legacy_scorer_with_zero_weight_criterion() -> None:
    # Arrange: a zero-weight criterion is an edge case the legacy Scorer
    # tolerates (it is only the *rubric-level* weight sum that Rubric's own
    # validator forbids being entirely zero).
    rubric_data: dict[str, Any] = {
        "criteria": [
            {"name": "Primary", "weight": 1.0},
            {"name": "Ignored", "weight": 0.0},
        ]
    }
    scores = {"Primary": 0.5, "Ignored": 1.0}

    # Act
    legacy_result = Scorer(rubric_data).score(scores)
    bridged_score = evalkit_bridge.score_criteria(rubric_data, scores)

    # Assert
    assert bridged_score == pytest.approx(legacy_result.weighted_score)
    assert bridged_score == pytest.approx(0.5)


def test_score_criteria_matches_legacy_scorer_with_out_of_range_values() -> None:
    # Arrange: legacy Scorer clamps to [min_value, max_value] (default [0, 1]).
    rubric_data = load_rubric("code")
    scores = {"Correctness": 1.5, "Security": -0.5}

    # Act
    legacy_result = Scorer(rubric_data).score(scores)
    bridged_score = evalkit_bridge.score_criteria(rubric_data, scores)

    # Assert
    assert bridged_score == pytest.approx(legacy_result.weighted_score)


def test_score_criteria_ignores_unknown_criterion_names() -> None:
    # Arrange
    rubric_data = load_rubric("default")
    scores = {"Accuracy": 0.9, "Not-A-Real-Criterion": 0.1}

    # Act
    legacy_result = Scorer(rubric_data).score(scores)
    bridged_score = evalkit_bridge.score_criteria(rubric_data, scores)

    # Assert
    assert bridged_score == pytest.approx(legacy_result.weighted_score)


def test_score_criteria_raises_when_evalkit_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(evalkit_bridge, "EVALKIT_AVAILABLE", False)

    # Act / Assert
    with pytest.raises(RuntimeError, match="not installed"):
        evalkit_bridge.score_criteria({"criteria": [{"name": "X"}]}, {"X": 1.0})


def test_all_rubric_files_on_disk_with_criteria_convert_and_score_identically() -> None:
    """Sweep every ARP rubric YAML that defines `criteria` (Slice B scope)."""
    # Arrange
    rubric_paths = sorted(RUBRICS_DIR.glob("*.yaml"))
    swept_any = False

    for rubric_path in rubric_paths:
        rubric_data = load_rubric(Path(rubric_path).stem)
        if not rubric_data.get("criteria"):
            continue  # judge-prompt/definitions-only rubrics: out of scope
        swept_any = True
        names = [criterion["name"] for criterion in rubric_data["criteria"]]
        scores = {name: 0.8 for name in names}

        # Act
        legacy_result = Scorer(rubric_data).score(scores)
        bridged_score = evalkit_bridge.score_criteria(rubric_data, scores)

        # Assert
        assert bridged_score == pytest.approx(legacy_result.weighted_score), rubric_path

    assert swept_any


# ---------------------------------------------------------------------------
# workflow_callable_target
# ---------------------------------------------------------------------------


def _make_sample(sample_id: str = "s1") -> EvalSample:
    return EvalSample(
        sample_id=sample_id,
        input={"question": "what is 2+2"},
        source_digest=f"sha256:{sample_id}",
        adapter="test-adapter@1",
    )


async def test_workflow_callable_target_executes_async_workflow_end_to_end() -> None:
    # Arrange
    async def run_workflow(sample_input: dict[str, Any]) -> dict[str, Any]:
        return {"answer": sample_input["question"], "status": "success"}

    target = evalkit_bridge.workflow_callable_target(
        run_workflow, name="fullstack_generation"
    )
    sample = _make_sample()

    # Act
    result = await target.execute(sample, attempt=1, timeout_seconds=5.0)

    # Assert
    assert result.status is ExecutionStatus.COMPLETED
    assert result.output == {"answer": "what is 2+2", "status": "success"}
    assert result.target_fingerprint is not None
    assert result.target_fingerprint.startswith("callable:fullstack_generation:")


async def test_workflow_callable_target_default_name_is_arp_workflow() -> None:
    # Arrange
    async def run_workflow(sample_input: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    target = evalkit_bridge.workflow_callable_target(run_workflow)

    # Act
    result = await target.execute(_make_sample(), attempt=1, timeout_seconds=5.0)

    # Assert
    assert result.target_fingerprint is not None
    assert result.target_fingerprint.startswith("callable:arp-workflow:")


async def test_workflow_callable_target_raises_on_non_mapping_result() -> None:
    # Arrange
    async def run_workflow(sample_input: dict[str, Any]) -> str:
        return "not-a-mapping"

    target = evalkit_bridge.workflow_callable_target(run_workflow, name="bad_workflow")

    # Act
    result = await target.execute(_make_sample(), attempt=1, timeout_seconds=5.0)

    # Assert: CallableTarget normalizes the exception into an ERROR result
    # rather than letting it propagate (matches its own contract for any
    # callable failure).
    assert result.status is ExecutionStatus.ERROR
    assert result.error is not None
    assert result.error["type"] == "TypeError"
    assert "bad_workflow" in str(result.error["message"])


async def test_workflow_callable_target_propagates_workflow_exception_as_error_result() -> (
    None
):
    # Arrange
    async def failing_workflow(sample_input: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("workflow blew up")

    target = evalkit_bridge.workflow_callable_target(failing_workflow, name="failing")

    # Act
    result = await target.execute(_make_sample(), attempt=1, timeout_seconds=5.0)

    # Assert
    assert result.status is ExecutionStatus.ERROR
    assert result.error is not None
    assert result.error["type"] == "RuntimeError"
    assert result.error["message"] == "workflow blew up"


def test_workflow_callable_target_raises_when_evalkit_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(evalkit_bridge, "EVALKIT_AVAILABLE", False)

    async def run_workflow(sample_input: dict[str, Any]) -> dict[str, Any]:
        return {}

    # Act / Assert
    with pytest.raises(RuntimeError, match="not installed"):
        evalkit_bridge.workflow_callable_target(run_workflow)
