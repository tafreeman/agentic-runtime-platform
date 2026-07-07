"""Criterion-level scoring, grading, and hybrid score composition.

Contains the individual criterion scoring functions, text analysis utilities,
grade mapping, LLM Judge criteria building, advisory heuristic scores, and
the hybrid score composition logic used by the main scoring pipeline in
:mod:`~agentic_v2.scoring.evaluation_scoring`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..contracts import StepStatus, WorkflowResult
from ..evaluation.normalization import normalize_score
from ..workflows.loader import WorkflowCriterion
from .judge import JudgeCriterionDefinition

# =============================================================================
# TEXT ANALYSIS UTILITIES
# =============================================================================


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to the closed interval ``[lo, hi]``.

    Args:
        value: The number to clamp.
        lo: Lower bound (default 0.0).
        hi: Upper bound (default 100.0).

    Returns:
        The clamped value.
    """
    return max(lo, min(hi, value))


def _tokenize(text: str) -> set[str]:
    """Split text into a set of lowercase alphanumeric tokens (length > 2).

    Args:
        text: Input text to tokenize.

    Returns:
        Set of unique lowercase token strings.
    """
    return {token for token in re.findall(r"\w+", text.lower()) if len(token) > 2}


def _extract_expected_text(sample: dict[str, Any]) -> str:
    """Extract the expected/golden output text from a dataset sample.

    Searches the sample dict for keys ``expected_output``,
    ``golden_output_text`` (inlined by the dataset loader from a sample's
    ``golden_output_path`` file reference), ``golden_patch``,
    ``answer.body``, and ``solution`` in priority order.

    Args:
        sample: A single dataset sample dict.

    Returns:
        The expected text string, or ``""`` if none found.
    """
    if not isinstance(sample, dict):
        return ""
    if isinstance(sample.get("expected_output"), str):
        return sample["expected_output"]
    if isinstance(sample.get("golden_output_text"), str):
        return sample["golden_output_text"]
    if isinstance(sample.get("golden_patch"), str):
        return sample["golden_patch"]
    answer = sample.get("answer")
    if isinstance(answer, dict) and isinstance(answer.get("body"), str):
        return answer["body"]
    if isinstance(sample.get("solution"), str):
        return sample["solution"]
    return ""


def _has_code_content(final_output: Any) -> bool:
    """Return True if final_output contains at least one non-trivial string leaf.

    Recursively walks dicts/lists looking for a string value with meaningful
    length (>= 20 chars).  Used to distinguish real code output from placeholder
    "I cannot fulfill this" responses where all leaves are null.
    """
    if isinstance(final_output, str):
        return len(final_output.strip()) >= 20
    if isinstance(final_output, dict):
        return any(_has_code_content(v) for v in final_output.values())
    if isinstance(final_output, list):
        return any(_has_code_content(item) for item in final_output)
    return False


def _strip_null_leaves(obj: Any) -> Any:
    """Recursively drop null/empty leaves from dicts and lists."""
    if isinstance(obj, dict):
        return {
            k: _strip_null_leaves(v)
            for k, v in obj.items()
            if v not in (None, "", {}, [])
        }
    if isinstance(obj, list):
        return [
            _strip_null_leaves(item) for item in obj if item not in (None, "", {}, [])
        ]
    return obj


def serialize_output_text(value: Any) -> str:
    """Serialize an output-shaped value to a JSON string for overlap scoring.

    Null/empty leaf values are omitted so they don't inflate richness or
    overlap scores.  Used for both generated workflow outputs and loaded
    golden outputs so the two sides tokenize symmetrically.

    Args:
        value: Any JSON-serializable output value (dict, list, or scalar).

    Returns:
        JSON-serialized string, or ``str()`` fallback on error.
    """
    try:
        return json.dumps(_strip_null_leaves(value), default=str)
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _output_text(result: WorkflowResult) -> str:
    """Serialize the workflow's final output to a JSON string for scoring.

    Args:
        result: The completed workflow result.

    Returns:
        JSON-serialized output string, or ``str()`` fallback on error.
    """
    final = getattr(result, "final_output", None) or getattr(result, "outputs", {})
    return serialize_output_text(final)


def _text_overlap_score(expected: str, generated: str) -> float:
    """Compute token-level recall of expected text in generated text.

    Tokenizes both strings into sets of alphanumeric tokens and returns
    the fraction of expected tokens present in the generated output,
    scaled to 0--100.

    Args:
        expected: The reference/golden text.
        generated: The model-produced text.

    Returns:
        Overlap score in the 0.0--100.0 range.
    """
    expected_tokens = _tokenize(expected)
    generated_tokens = _tokenize(generated)
    if not expected_tokens:
        return 0.0
    overlap = expected_tokens & generated_tokens
    return (len(overlap) / len(expected_tokens)) * 100.0


# =============================================================================
# CRITERION SCORING
# =============================================================================


def _compute_criterion_score(
    criterion: str,
    result: WorkflowResult,
    expected_text: str,
) -> float:
    """Compute a raw 0--100 score for a single evaluation criterion.

    Dispatches on ``criterion`` name to one of four scoring formulas:

    * **correctness-family** (``correctness``, ``objective_tests``,
      ``task_completion``, ``faithfulness``, ``relevance``):
      Blends success rate (70%) with text overlap recall (30%).
    * **quality-family** (``code_quality``, ``safety_validation``,
      ``tool_selection_accuracy``):
      Penalizes for step failures and retries, with a status bonus.
    * **efficiency-family** (``efficiency``, ``performance``):
      Penalizes for execution duration and retries.
    * **documentation-family** (``documentation``, ``citation_quality``,
      ``coherence``):
      Rewards output richness (character count and dict key count).

    Unknown criteria receive a neutral baseline of 50.0 so the LLM
    Judge can fully determine the final score.

    Args:
        criterion: Evaluation criterion name.
        result: The completed workflow result.
        expected_text: Golden/expected output text for overlap scoring.

    Returns:
        Raw score clamped to the 0.0--100.0 range.
    """
    # Support both contract WorkflowResult and langchain runner WorkflowResult
    # Normalize both result shapes into the same scoring signals so the
    # formulas below stay deterministic across execution backends.
    signals = _extract_scoring_signals(result)

    if criterion in _CORRECTNESS_CRITERIA:
        return _score_correctness(signals, expected_text)
    if criterion in _QUALITY_CRITERIA:
        return _score_quality(signals)
    if criterion in _EFFICIENCY_CRITERIA:
        return _score_efficiency(signals)
    if criterion in _DOCUMENTATION_CRITERIA:
        return _score_documentation(signals, result)

    # For unknown criteria, start at a baseline of 50.0 (neutral)
    # so that the LLM Judge (which scores 1-5) can truly dictate the output score.
    baseline = 50.0
    if signals.is_failed:
        baseline -= 20.0
    return _clamp(baseline)


_CORRECTNESS_CRITERIA = (
    "correctness",
    "objective_tests",
    "task_completion",
    "correctness_rubric",
    "faithfulness",
    "relevance",
)
_QUALITY_CRITERIA = (
    "code_quality",
    "safety_validation",
    "validation",
    "safety",
    "tool_selection_accuracy",
)
_EFFICIENCY_CRITERIA = ("efficiency", "performance")
_DOCUMENTATION_CRITERIA = ("documentation", "citation_quality", "coherence")

# Execution SLO band shared by the efficiency criterion and the advisory
# efficiency layer: durations at/below the good bound score 1.0, at/above the
# bad bound score 0.0, linear in between (same for retries).
_EFFICIENCY_SLO_GOOD_SECONDS = 2.0
_EFFICIENCY_SLO_BAD_SECONDS = 60.0
_RETRY_SLO_GOOD = 0.0
_RETRY_SLO_BAD = 8.0
_EFFICIENCY_DURATION_WEIGHT = 0.7
_EFFICIENCY_RETRY_WEIGHT = 0.3


@dataclass(frozen=True)
class _ScoringSignals:
    """Normalized execution signals shared by all criterion-family scorers."""

    success_rate: float
    total_steps: int
    failed_steps: int
    retries: int
    duration_ms: float
    output_text: str
    is_failed: bool
    is_success: bool
    has_code: bool


def _extract_scoring_signals(result: WorkflowResult) -> _ScoringSignals:
    """Normalize contract and langchain result shapes into common scoring signals."""
    if hasattr(result, "success_rate"):
        success_rate = float(result.success_rate)
        total_steps = max(len(result.steps), 1)
        failed_steps = len(result.failed_steps)
        retries = result.total_retries
        duration_ms = result.total_duration_ms or 0.0
    else:
        status = getattr(result, "status", "unknown")
        success_rate = 100.0 if status == "success" else 0.0
        steps = getattr(result, "steps", {})
        total_steps = max(len(steps), 1)
        errors = getattr(result, "errors", [])
        failed_steps = len(errors)
        retries = 0
        elapsed = getattr(result, "elapsed_seconds", 0.0)
        duration_ms = elapsed * 1000.0

    _overall = getattr(result, "overall_status", None)
    # Prefer the enum-based overall status when present; string statuses are a
    # legacy fallback and can be less precise than the contract result.
    if _overall is None:
        _status_str = getattr(result, "status", "unknown")
        is_failed = _status_str != "success"
        is_success = _status_str == "success"
    else:
        is_failed = _overall == StepStatus.FAILED
        is_success = _overall == StepStatus.SUCCESS

    final_out = getattr(result, "final_output", None) or getattr(result, "outputs", {})
    return _ScoringSignals(
        success_rate=success_rate,
        total_steps=total_steps,
        failed_steps=failed_steps,
        retries=retries,
        duration_ms=duration_ms,
        output_text=_output_text(result),
        is_failed=is_failed,
        is_success=is_success,
        has_code=_has_code_content(final_out),
    )


def _score_correctness(signals: _ScoringSignals, expected_text: str) -> float:
    """Score correctness-family criteria: success rate blended with text overlap."""
    if expected_text:
        overlap = _text_overlap_score(expected_text, signals.output_text)
    elif signals.has_code:
        # No expected text but real output present — treat as pass at success_rate
        overlap = signals.success_rate
    else:
        # No expected text AND no real output — hollow run scores 0 on overlap
        overlap = 0.0
    blended = (signals.success_rate * 0.7) + (overlap * 0.3)
    if signals.is_failed:
        blended *= 0.75
    if not signals.has_code:
        # Steps completed but produced nothing — cap at 30 regardless of success_rate
        blended = min(blended, 30.0)
    return _clamp(blended)


def _score_quality(signals: _ScoringSignals) -> float:
    """Score quality-family criteria: penalize failures/retries with a status bonus."""
    failure_penalty = (signals.failed_steps / signals.total_steps) * 45.0
    retry_penalty = min(signals.retries * 4.0, 20.0)
    status_bonus = 8.0 if signals.is_success else -12.0
    score = 78.0 - failure_penalty - retry_penalty + status_bonus
    if not signals.has_code:
        # No real code/content produced — quality cannot be above minimal
        score = min(score, 5.0)
    return _clamp(score)


def _score_efficiency(signals: _ScoringSignals) -> float:
    """Score efficiency-family criteria via SLO-bounded normalization.

    Duration is normalized against the shared execution SLO band
    (``_EFFICIENCY_SLO_GOOD_SECONDS`` good .. ``_EFFICIENCY_SLO_BAD_SECONDS``
    bad) and retries against the retry band, then blended 70/30 — the same
    formula as :func:`_advisory_efficiency_score`.  The previous
    ``min(seconds * 1.5, 55)`` penalty saturated at ~37s, making every
    longer run score identically regardless of how much longer it ran.
    """
    seconds = signals.duration_ms / 1000.0
    duration_norm = normalize_score(
        seconds,
        "lower_is_better",
        slo_good=_EFFICIENCY_SLO_GOOD_SECONDS,
        slo_bad=_EFFICIENCY_SLO_BAD_SECONDS,
    )
    retry_norm = normalize_score(
        signals.retries,
        "lower_is_better",
        slo_good=_RETRY_SLO_GOOD,
        slo_bad=_RETRY_SLO_BAD,
    )
    blended = (duration_norm * _EFFICIENCY_DURATION_WEIGHT) + (
        retry_norm * _EFFICIENCY_RETRY_WEIGHT
    )
    return _clamp(blended * 100.0)


def _score_documentation(signals: _ScoringSignals, result: WorkflowResult) -> float:
    """Score documentation-family criteria: reward output richness."""
    if not signals.output_text:
        return 20.0
    chars = len(signals.output_text)
    final_out = getattr(result, "final_output", None) or getattr(result, "outputs", {})
    key_count = len(final_out.keys()) if isinstance(final_out, dict) else 1
    # Documentation-style criteria use output richness as a heuristic proxy,
    # not as a guarantee of correctness.
    richness = min(chars / 120.0, 45.0) + min(key_count * 6.0, 30.0)
    base = 30.0 + richness
    if signals.is_failed:
        base -= 15.0
    return _clamp(base)


# =============================================================================
# GRADING
# =============================================================================


def _grade(score: float) -> str:
    """Map a 0--100 weighted score to a letter grade.

    Args:
        score: Weighted composite score.

    Returns:
        One of ``"A"`` (>=90), ``"B"`` (>=80), ``"C"`` (>=70),
        ``"D"`` (>=60), or ``"F"`` (<60).
    """
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


# =============================================================================
# JUDGE CRITERIA BUILDING
# =============================================================================


def _default_judge_scale() -> dict[str, str]:
    """Return the default 1--5 anchored scale labels for LLM Judge criteria.

    Returns:
        Mapping of score (as string) to human-readable anchor description.
    """
    return {
        "1": "Major requirement failures",
        "2": "Multiple significant errors",
        "3": "Minimum acceptable quality",
        "4": "Strong quality with minor gaps",
        "5": "Excellent quality and completeness",
    }


def _resolve_judge_scale(criterion: Any) -> dict[str, str]:
    """Normalize the two supported workflow scale schema variants onto one map."""
    scale_anchors = getattr(criterion, "scale_anchors", None)
    if isinstance(scale_anchors, dict) and scale_anchors:
        return {str(key): str(value) for key, value in scale_anchors.items()}

    scale = getattr(criterion, "scale", None)
    if isinstance(scale, dict) and scale:
        return {str(key): str(value) for key, value in scale.items()}

    return _default_judge_scale()


def _generic_judge_criterion(criterion_name: str) -> JudgeCriterionDefinition:
    """Build a generic judge criterion when no rich metadata is available."""
    return JudgeCriterionDefinition(
        name=criterion_name,
        definition=f"Quality of the '{criterion_name}' aspect.",
        scale=_default_judge_scale(),
    )


def _build_judge_criteria(
    *,
    weights: dict[str, float],
    criteria_by_name: dict[str, WorkflowCriterion],
) -> list[JudgeCriterionDefinition]:
    """Build LLM Judge criterion definitions from workflow criteria and weights.

    If the workflow defines criteria with definitions and scale anchors,
    those are used.  Otherwise, generic definitions are generated from
    the weight keys.

    Args:
        weights: Active criterion-to-weight mapping.
        criteria_by_name: Workflow-defined criteria keyed by name.

    Returns:
        List of :class:`JudgeCriterionDefinition` instances for the judge prompt.
    """
    if not criteria_by_name:
        # Older workflows may define weights without rich criterion metadata;
        # keep the judge usable by synthesizing a generic definition.
        return [_generic_judge_criterion(criterion_name) for criterion_name in weights]

    criteria: list[JudgeCriterionDefinition] = []
    for criterion_name in weights:
        criterion = criteria_by_name.get(criterion_name)
        if criterion is None:
            criteria.append(_generic_judge_criterion(criterion_name))
            continue
        criteria.append(
            JudgeCriterionDefinition(
                name=criterion_name,
                definition=(
                    criterion.definition or f"Quality of '{criterion_name}' aspect."
                ),
                scale=_resolve_judge_scale(criterion),
            )
        )
    return criteria


# =============================================================================
# ADVISORY HEURISTIC SCORES
# =============================================================================


def _advisory_similarity_score(
    *,
    expected_text: str,
    generated_text: str,
    objective_score_0_1: float,
) -> float:
    """Compute the advisory similarity component (0--1) for hybrid scoring.

    When expected text is available, uses token-overlap recall normalized
    to [0, 1].  Otherwise, falls back to the objective criterion score.

    Args:
        expected_text: Golden/reference output text.
        generated_text: Model-produced output text.
        objective_score_0_1: Pre-computed objective score as fallback.

    Returns:
        Normalized similarity score in [0, 1].
    """
    if expected_text:
        overlap = _text_overlap_score(expected_text, generated_text)
        return normalize_score(overlap / 100.0, "zero_one")
    return normalize_score(objective_score_0_1, "zero_one")


def _advisory_efficiency_score(
    *,
    result: WorkflowResult,
    normalized_scores: dict[str, float],
) -> float:
    """Compute the advisory efficiency component (0--1) for hybrid scoring.

    If an ``efficiency`` criterion was already scored, reuses it.
    Otherwise, derives efficiency from execution duration (SLO: 2s good,
    60s bad) and retry count (SLO: 0 good, 8 bad), blended 70/30.

    Args:
        result: The completed workflow result (for duration and retries).
        normalized_scores: Already-computed normalized criterion scores.

    Returns:
        Normalized efficiency score in [0, 1].
    """
    if "efficiency" in normalized_scores:
        return normalize_score(normalized_scores["efficiency"], "zero_one")

    duration_seconds = (result.total_duration_ms or 0.0) / 1000.0
    duration_norm = normalize_score(
        duration_seconds,
        "lower_is_better",
        slo_good=_EFFICIENCY_SLO_GOOD_SECONDS,
        slo_bad=_EFFICIENCY_SLO_BAD_SECONDS,
    )
    retry_norm = normalize_score(
        result.total_retries,
        "lower_is_better",
        slo_good=_RETRY_SLO_GOOD,
        slo_bad=_RETRY_SLO_BAD,
    )
    return (duration_norm * _EFFICIENCY_DURATION_WEIGHT) + (
        retry_norm * _EFFICIENCY_RETRY_WEIGHT
    )


# =============================================================================
# HYBRID SCORE COMPOSITION
# =============================================================================


def _compose_hybrid_score(
    *,
    objective_score_0_1: float,
    advisory_score_0_1: float,
    judge_score_0_1: float | None,
    component_weights: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """Compose a hybrid score from objective, advisory, and judge components.

    Default component weights are ``objective=0.35``, ``judge=0.50``,
    ``advisory=0.15``.  If the judge score is ``None`` (judge unavailable),
    only objective and advisory are used with re-normalized weights.

    Args:
        objective_score_0_1: Weighted criterion score in [0, 1].
        advisory_score_0_1: Heuristic advisory score in [0, 1].
        judge_score_0_1: LLM Judge normalized score in [0, 1], or None.
        component_weights: Optional override for component weight map.

    Returns:
        A 2-tuple of ``(hybrid_score_0_1, active_weights_used)``.
    """
    default_weights = {
        "objective": 0.35,
        "judge": 0.50,
        "advisory": 0.15,
    }
    weights = dict(default_weights)
    if component_weights:
        weights.update(component_weights)

    active_components: dict[str, float] = {
        "objective": objective_score_0_1,
        "advisory": advisory_score_0_1,
    }
    # Omit the judge component entirely when it is unavailable so the remaining
    # weights can be re-normalized instead of penalizing the final score.
    if judge_score_0_1 is not None:
        active_components["judge"] = judge_score_0_1

    weight_sum = 0.0
    weighted = 0.0
    active_weights: dict[str, float] = {}
    for name, value in active_components.items():
        weight = max(float(weights.get(name, 0.0)), 0.0)
        if weight <= 0:
            continue
        active_weights[name] = weight
        weighted += value * weight
        weight_sum += weight

    if weight_sum <= 0:
        return objective_score_0_1, {"objective": 1.0}
    return weighted / weight_sum, active_weights
