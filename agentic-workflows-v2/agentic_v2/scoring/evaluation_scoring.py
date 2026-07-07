"""Scoring engine for workflow evaluation results.

Implements a three-stage scoring pipeline:

1. **Hard gates** (:func:`compute_hard_gates`) -- binary pass/fail checks
   that must all succeed before a run can receive a passing grade:
   required outputs present, overall status ``SUCCESS``, no critical step
   failures, release-build verification, schema contract validity, and
   dataset/workflow compatibility.

2. **Criterion evaluation** (:func:`_compute_criterion_score`) -- per-criterion
   raw scores (0--100) computed from workflow execution signals (success rate,
   text overlap, step failures, duration, output richness).  Each criterion
   is then normalized via :mod:`~agentic_v2.server.normalization` and
   optionally adjusted for sample size.

3. **Aggregation and grading** (:func:`score_workflow_result_impl`) --
   weighted combination of objective criterion scores, advisory heuristic
   scores (similarity + efficiency), and optional LLM-as-Judge scores
   into a hybrid 0--100 composite.  The composite is mapped to a letter
   grade (A/B/C/D/F) subject to criterion floor violations and hard-gate
   enforcement.

Rubric resolution (:func:`_resolve_rubric`) merges defaults from the
evaluation YAML config, workflow-level scoring profiles (A--E), per-criterion
weight overrides, and an optional rubric ID override.

Criterion-level scoring, text analysis, grading, judge criteria building,
and hybrid score composition live in :mod:`~agentic_v2.scoring.scoring_criteria`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from ..contracts import StepStatus, WorkflowResult
from ..evaluation.normalization import adjust_for_sample_size, normalize_score
from ..workflows.loader import (
    WorkflowCriterion,
    WorkflowDefinition,
    WorkflowOutput,
)
from .dataset_matching import match_workflow_dataset
from .eval_config import _load_eval_config
from .judge import JudgeEvaluationResult, LLMJudge

# Re-export everything from scoring_criteria so callers that import from
# this module continue to work unchanged.
from .scoring_criteria import (
    _advisory_efficiency_score,
    _advisory_similarity_score,
    _build_judge_criteria,
    _clamp,
    _compose_hybrid_score,
    _compute_criterion_score,
    _extract_expected_text,
    _grade,
    _output_text,
    _text_overlap_score,
    _tokenize,
)
from .scoring_profiles import get_profile

logger = logging.getLogger(__name__)


class JudgeRequiredError(RuntimeError):
    """The judge is mandatory (``evaluation.scoring.judge_required``) but unavailable.

    A distinct type so callers can map the *policy* failure (persist the run
    with an evaluation error, return a structured HTTP 422) without also
    catching the ordinary judge failures it escalates.
    """


_DEFAULT_WEIGHTS: dict[str, float] = {
    "correctness": 0.50,
    "code_quality": 0.25,
    "efficiency": 0.15,
    "documentation": 0.10,
}
_DEFAULT_PASS_THRESHOLD = 70.0
_DEFAULT_RUBRIC = "workflow_default"
_DEFAULT_RUBRIC_VERSION = "1.0"


@dataclass
class HardGateResult:
    """Result of hard-gate (binary pass/fail) checks for a workflow run.

    Each flag is ``True`` if the gate passed, ``False`` if violated.
    """

    required_outputs_present: bool
    overall_status_success: bool
    no_critical_step_failures: bool
    release_build_verified: bool
    schema_contract_valid: bool
    dataset_workflow_compatible: bool

    @property
    def all_passed(self) -> bool:
        """Return ``True`` only if every hard gate passed."""
        return (
            self.required_outputs_present
            and self.overall_status_success
            and self.no_critical_step_failures
            and self.release_build_verified
            and self.schema_contract_valid
            and self.dataset_workflow_compatible
        )

    @property
    def failures(self) -> list[str]:
        """List of human-readable gate names that failed."""
        failed: list[str] = []
        if not self.required_outputs_present:
            failed.append("required_outputs_present")
        if not self.overall_status_success:
            failed.append("overall_status_success")
        if not self.no_critical_step_failures:
            failed.append("no_critical_step_failures")
        if not self.release_build_verified:
            failed.append("release_build_verified")
        if not self.schema_contract_valid:
            failed.append("schema_contract_valid")
        if not self.dataset_workflow_compatible:
            failed.append("dataset_workflow_compatible")
        return failed


@dataclass
class CriterionFloorResult:
    """Records a single criterion floor violation.

    A floor violation occurs when a criterion's normalized score falls
    below the minimum ``critical_floor`` defined in the workflow.
    """

    criterion: str
    floor: float
    normalized_score: float


def _scoring_weights() -> dict[str, float]:
    """Load criterion weights from the evaluation YAML config.

    Falls back to ``_DEFAULT_WEIGHTS`` when the config file is missing
    or the ``evaluation.scoring.weights`` section is absent/invalid.

    Returns:
        Mapping of criterion name to weight (should sum to ~1.0).
    """
    config = _load_eval_config()
    raw = ((config.get("evaluation") or {}).get("scoring") or {}).get("weights", {})
    if not isinstance(raw, dict):
        return dict(_DEFAULT_WEIGHTS)

    weights: dict[str, float] = {}
    for key, value in raw.items():
        try:
            weights[str(key)] = float(value)
        except (ValueError, TypeError):
            continue
    if not weights:
        return dict(_DEFAULT_WEIGHTS)
    return weights


def pass_threshold() -> float:
    """Return the minimum weighted score required to pass evaluation.

    Reads ``evaluation.scoring.pass_threshold`` from the evaluation YAML
    config.  Defaults to 70.0 if unconfigured or unparseable.

    Returns:
        Pass threshold as a float in the 0--100 scale.
    """
    config = _load_eval_config()
    raw = ((config.get("evaluation") or {}).get("scoring") or {}).get(
        "pass_threshold", _DEFAULT_PASS_THRESHOLD
    )
    try:
        return float(raw)
    except (ValueError, TypeError):
        return _DEFAULT_PASS_THRESHOLD


def judge_required() -> bool:
    """Return whether a working LLM judge is mandatory for evaluation.

    Reads ``evaluation.scoring.judge_required`` from the evaluation YAML
    config.  When ``True``, a judge that is unconfigured or fails to run
    raises instead of silently degrading to objective+advisory scoring.
    Defaults to ``False`` so key-free environments (``AGENTIC_NO_LLM=1``)
    keep working -- but the skip is always recorded loudly in the payload
    via ``judge_skipped`` / ``judge_skip_reason`` either way.

    Returns:
        True if the judge is required, False otherwise.
    """
    config = _load_eval_config()
    scoring = (config.get("evaluation") or {}).get("scoring") or {}
    # _is_true_like, not bool(): a quoted "false"/"no"/"0" from a config
    # overlay must not silently enable hard-fail mode.
    return _is_true_like(scoring.get("judge_required", False))


def _resolve_rubric(
    workflow_definition: WorkflowDefinition | None,
    rubric_override: str | None,
) -> tuple[str, str, dict[str, float], dict[str, WorkflowCriterion]]:
    """Resolve rubric identity and scoring weights from all sources.

    Merges weights in priority order (lowest to highest):
    1. Global defaults from ``evaluation.yaml`` (or ``_DEFAULT_WEIGHTS``).
    2. Scoring profile weights (``A``--``E``) if the workflow declares one.
    3. Per-criterion ``weight`` fields from the workflow's evaluation criteria.
    4. Explicit ``weights`` dict from the workflow evaluation section.

    Args:
        workflow_definition: The loaded workflow definition, or None.
        rubric_override: Optional rubric ID that takes precedence over the
            workflow's ``evaluation.rubric_id``.

    Returns:
        A 4-tuple of ``(rubric_id, rubric_version, weights, criteria_by_name)``.

    Raises:
        ValueError: If the resolved weights are empty, contain unknown
            criteria, include non-positive values, or do not sum to ~1.0.
    """
    weights = dict(_scoring_weights())
    criteria_by_name: dict[str, WorkflowCriterion] = {}

    workflow_rubric_id: str | None = None
    workflow_weights: dict[str, float] | None = None
    workflow_scoring_profile: str | None = None
    if workflow_definition is not None and workflow_definition.evaluation is not None:
        workflow_rubric_id = workflow_definition.evaluation.rubric_id
        workflow_weights = workflow_definition.evaluation.weights
        workflow_scoring_profile = workflow_definition.evaluation.scoring_profile
        criteria_by_name = {
            criterion.name: criterion
            for criterion in workflow_definition.evaluation.criteria
        }

    weights = _merge_rubric_weights(
        weights,
        criteria_by_name=criteria_by_name,
        workflow_weights=workflow_weights,
        workflow_scoring_profile=workflow_scoring_profile,
    )

    _validate_rubric_weights(
        weights,
        known_criteria=set(criteria_by_name.keys()) if criteria_by_name else None,
    )

    rubric_id = rubric_override or workflow_rubric_id or _DEFAULT_RUBRIC
    version = str(_load_eval_config().get("version") or _DEFAULT_RUBRIC_VERSION)
    return rubric_id, version, weights, criteria_by_name


def _merge_rubric_weights(
    weights: dict[str, float],
    *,
    criteria_by_name: dict[str, WorkflowCriterion],
    workflow_weights: dict[str, float] | None,
    workflow_scoring_profile: str | None,
) -> dict[str, float]:
    """Merge scoring weights from profile, criteria, and explicit overrides.

    Applies, in order: scoring-profile weights, criterion scoping (drop
    inherited weights for undeclared criteria), per-criterion ``weight``
    overrides, then explicit workflow ``weights``.
    """
    if workflow_scoring_profile:
        weights = dict(get_profile(workflow_scoring_profile).weights)

    if criteria_by_name:
        # Once a workflow declares explicit criteria, ignore inherited weights
        # for undeclared criteria to avoid silently scoring the wrong rubric.
        weights = {
            criterion_name: weights[criterion_name]
            for criterion_name in criteria_by_name
            if criterion_name in weights
        }

    for criterion_name, criterion in criteria_by_name.items():
        if criterion.weight is not None:
            weights[criterion_name] = criterion.weight

    if workflow_weights:
        _validate_rubric_weights(workflow_weights)
        weights.update(workflow_weights)

    return weights


def _validate_rubric_weights(
    weights: dict[str, float],
    *,
    known_criteria: set[str] | None = None,
) -> None:
    """Validate that rubric weights are non-empty, positive, sum to ~1.0, and reference
    only known criteria.

    Args:
        weights: Mapping of criterion name to weight.
        known_criteria: If provided, the set of valid criterion names.
            Any weight key not in this set raises ``ValueError``.

    Raises:
        ValueError: On empty weights, unknown criteria, non-positive
            values, or sum deviating from 1.0 by more than 0.01.
    """
    if not weights:
        raise ValueError("Rubric weights cannot be empty.")

    if known_criteria:
        unknown = sorted(set(weights.keys()) - known_criteria)
    else:
        unknown = []
    if unknown:
        raise ValueError(
            f"Rubric references unknown criteria: {', '.join(unknown)}. "
            f"Known criteria: {', '.join(sorted(known_criteria))}."
        )

    total = sum(weights.values())
    if any(value <= 0 for value in weights.values()):
        raise ValueError("Rubric weights must all be positive.")
    if abs(total - 1.0) > 0.01:
        raise ValueError(f"Rubric weights must sum to 1.0 (+/-0.01), got {total:.4f}.")


def _step_scores(result: WorkflowResult) -> list[dict[str, Any]]:
    """Produce lightweight per-step score summaries for event and log payloads.

    Args:
        result: The completed workflow result.

    Returns:
        List of dicts, each with ``step_name``, ``status``, and ``score``
        (100.0 for success, 0.0 otherwise).
    """
    scores: list[dict[str, Any]] = []
    for step in result.steps:
        if step.status == StepStatus.SUCCESS:
            score = 100.0
        elif step.status == StepStatus.SKIPPED:
            score = 0.0
        else:
            score = 0.0
        scores.append(
            {
                "step_name": step.step_name,
                "status": step.status.value,
                "score": score,
            }
        )
    return scores


def validate_evaluation_payload_schema(
    payload: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate that an evaluation payload conforms to the expected schema.

    Checks for required top-level fields (``rubric_id``, ``criteria``,
    ``overall_score``, ``weighted_score``, ``grade``, ``passed``,
    ``pass_threshold``, ``step_scores``) and validates the structure of
    each criterion entry.

    Args:
        payload: The evaluation result dict to validate.

    Returns:
        A 2-tuple of ``(is_valid, error_messages)``.
    """
    if not isinstance(payload, dict):
        return False, ["payload must be a mapping"]

    errors: list[str] = []
    errors.extend(_validate_required_payload_fields(payload))
    errors.extend(_validate_payload_criteria(payload.get("criteria")))
    return len(errors) == 0, errors


_REQUIRED_PAYLOAD_FIELDS: dict[str, tuple[type, ...]] = {
    "rubric_id": (str,),
    "rubric_version": (str,),
    "criteria": (list,),
    "overall_score": (int, float),
    "weighted_score": (int, float),
    "grade": (str,),
    "passed": (bool,),
    "pass_threshold": (int, float),
    "step_scores": (list,),
}
_REQUIRED_CRITERION_KEYS = (
    "criterion",
    "raw_score",
    "normalized_score",
    "weight",
    "formula_id",
    "score",
)


def _validate_required_payload_fields(payload: dict[str, Any]) -> list[str]:
    """Validate presence and type of the required top-level payload fields."""
    errors: list[str] = []
    for field, expected_types in _REQUIRED_PAYLOAD_FIELDS.items():
        value = payload.get(field)
        if value is None:
            errors.append(f"missing field: {field}")
            continue
        if not isinstance(value, expected_types):
            expected = ", ".join(t.__name__ for t in expected_types)
            errors.append(f"field '{field}' must be {expected}")
    return errors


def _validate_payload_criteria(criteria: Any) -> list[str]:
    """Validate the structure of each criterion entry in the payload."""
    if not isinstance(criteria, list):
        return []
    errors: list[str] = []
    for idx, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            errors.append(f"criteria[{idx}] must be an object")
            continue
        for key in _REQUIRED_CRITERION_KEYS:
            if key not in criterion:
                errors.append(f"criteria[{idx}] missing key: {key}")
    return errors


def compute_hard_gates(
    result: WorkflowResult,
    workflow_outputs: dict[str, WorkflowOutput] | None = None,
    eval_payload: dict[str, Any] | None = None,
    dataset_workflow_compatible: bool = True,
) -> HardGateResult:
    """Compute hard-gate pass/fail flags for a workflow run.

    Args:
        result: The completed workflow result to evaluate.
        workflow_outputs: Output definitions from the workflow YAML, used
            to identify which outputs are required (non-optional).
        eval_payload: If provided, validated against the evaluation schema
            to set the ``schema_contract_valid`` gate.
        dataset_workflow_compatible: Pre-computed flag indicating whether
            the dataset sample satisfied the workflow's required inputs.

    Returns:
        A :class:`HardGateResult` with all gate flags populated.
    """
    required_outputs_present = _required_outputs_present(result, workflow_outputs)
    overall_status_success = result.overall_status == StepStatus.SUCCESS
    no_critical_step_failures = all(
        step.status != StepStatus.FAILED for step in result.steps
    )
    release_build_verified = _release_build_verified(result)

    schema_contract_valid = True
    if eval_payload is not None:
        schema_contract_valid, _ = validate_evaluation_payload_schema(eval_payload)

    return HardGateResult(
        required_outputs_present=required_outputs_present,
        overall_status_success=overall_status_success,
        no_critical_step_failures=no_critical_step_failures,
        release_build_verified=release_build_verified,
        schema_contract_valid=schema_contract_valid,
        dataset_workflow_compatible=dataset_workflow_compatible,
    )


def _is_hollow_dict(value: Any) -> bool:
    """Return True if *value* is a non-empty dict whose leaves are all empty."""
    return (
        isinstance(value, dict)
        and bool(value)
        and all(v in (None, "", {}, []) for v in value.values())
    )


def _required_outputs_present(
    result: WorkflowResult,
    workflow_outputs: dict[str, WorkflowOutput] | None,
) -> bool:
    """Return True if every required workflow output resolved to real content.

    A required output is missing when it is unresolved, ``None``, or a hollow
    dict (all leaf values null/empty).
    """
    required_outputs = [
        output_name
        for output_name, output_def in (workflow_outputs or {}).items()
        if not output_def.optional
    ]

    unresolved_required = result.metadata.get("unresolved_required_outputs", [])
    unresolved_set = (
        set(unresolved_required) if isinstance(unresolved_required, list) else set()
    )
    required_output_values = (
        result.final_output if isinstance(result.final_output, dict) else {}
    )

    for output_name in required_outputs:
        if output_name in unresolved_set:
            return False
        value = required_output_values.get(output_name)
        if value is None:
            return False
        # Hollow dict: all leaf values are null/empty — treat as missing output
        if _is_hollow_dict(value):
            return False
    return True


def _is_true_like(value: Any) -> bool:
    """Return True for boolean-true-ish values across bool/str/number types."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if isinstance(value, (int, float)):
        return value != 0
    return False


def _release_build_verified(result: WorkflowResult) -> bool:
    """Return True if all release-build steps succeeded and signaled readiness."""
    release_step_prefixes = ("build_verify_release", "release_build_verify")
    release_steps = [
        step
        for step in result.steps
        if any(step.step_name.startswith(prefix) for prefix in release_step_prefixes)
    ]
    for step in release_steps:
        if step.status == StepStatus.FAILED:
            return False
        ready_flag = (
            step.output_data.get("ready_for_release")
            if isinstance(step.output_data, dict)
            else None
        )
        if ready_flag is not None and not _is_true_like(ready_flag):
            return False
    return True


def _compute_criteria_scores(
    weights: dict[str, float],
    *,
    result: WorkflowResult,
    expected_text: str,
    criteria_by_name: dict[str, WorkflowCriterion],
    compute_criterion_score_fn: Callable[[str, WorkflowResult, str], float],
) -> tuple[list[dict[str, Any]], dict[str, float], float, float]:
    """Compute per-criterion score payloads and running aggregate sums.

    Returns ``(criteria_payloads, normalized_scores, weighted_sum, raw_sum)``.
    """
    criteria: list[dict[str, Any]] = []
    normalized_scores: dict[str, float] = {}
    weighted_sum = 0.0
    raw_sum = 0.0
    for criterion, weight in weights.items():
        raw_score = compute_criterion_score_fn(criterion, result, expected_text)
        config = criteria_by_name.get(criterion)
        formula_id = config.formula_id if config else "zero_one"
        normalized_score = normalize_score(raw_score / 100.0, formula_id)
        adjusted_score = adjust_for_sample_size(
            normalized_score, n=max(len(result.steps), 1)
        )
        critical_floor = config.critical_floor if config else None
        floor_passed = (
            True if critical_floor is None else normalized_score >= critical_floor
        )

        criteria.append(
            {
                "criterion": criterion,
                "raw_score": round(raw_score, 4),
                "normalized_score": round(normalized_score, 4),
                "adjusted_normalized_score": round(adjusted_score, 4),
                "score": round(normalized_score * 100.0, 2),
                "weight": float(weight),
                "formula_id": formula_id,
                "critical_floor": critical_floor,
                "floor_passed": floor_passed,
                "max_score": 100.0,
            }
        )
        normalized_scores[criterion] = normalized_score
        weighted_sum += normalized_score * float(weight)
        raw_sum += raw_score

    return criteria, normalized_scores, weighted_sum, raw_sum


def _apply_judge_scores(
    judge: LLMJudge | None,
    *,
    criteria: list[dict[str, Any]],
    weights: dict[str, float],
    criteria_by_name: dict[str, WorkflowCriterion],
    generated_text: str,
    expected_text: str,
) -> tuple[JudgeEvaluationResult | None, float | None, str | None, str | None]:
    """Run the LLM judge (if provided) and annotate criterion payloads in place.

    Returns ``(judge_result, judge_score_0_1, skip_reason, skip_code)``.  The
    first two are ``None`` -- and ``skip_reason``/``skip_code`` say why --
    when no judge is configured or the judge invocation failed.  A skipped
    judge is never silent: the reason is logged, propagated into the
    evaluation payload (``judge_skipped`` / ``judge_skip_reason`` /
    ``judge_skip_code``), and, when :func:`judge_required` is enabled,
    escalated to a hard failure.

    Raises:
        JudgeRequiredError: The judge is unavailable and
            ``evaluation.scoring.judge_required`` is ``True``.
    """
    if judge is None:
        reason, code = _handle_judge_skip("no judge configured", code="not_configured")
        return None, None, reason, code

    try:
        judge_criteria = _build_judge_criteria(
            weights=weights,
            criteria_by_name=criteria_by_name,
        )
        judge_result = judge.evaluate(
            candidate_output=generated_text,
            expected_output=expected_text,
            criteria=judge_criteria,
        )

        judge_by_name = {item.name: item for item in judge_result.criteria}
        for criterion_payload in criteria:
            judge_item = judge_by_name.get(str(criterion_payload["criterion"]))
            if judge_item is None:
                continue
            criterion_payload["judge_raw_score"] = round(judge_item.raw_score, 4)
            criterion_payload["judge_normalized_score"] = round(
                judge_item.normalized_score, 4
            )
            criterion_payload["judge_evidence"] = judge_item.evidence
        return judge_result, judge_result.normalized_score, None, None
    except Exception as exc:
        # Broad by design: the skip machinery IS the safety net. Provider
        # errors arrive as arbitrary Exception subclasses (executionkit
        # RateLimitError/PermanentError are plain Exceptions), and any escape
        # here destroys the whole evaluation instead of recording a loud
        # skip. JudgeRequiredError is raised by _handle_judge_skip below,
        # outside this try, so the policy escalation is never swallowed.
        for criterion_payload in criteria:
            # A mid-loop failure must not leave contradictory partial judge
            # annotations next to judge_skipped=true.
            criterion_payload.pop("judge_raw_score", None)
            criterion_payload.pop("judge_normalized_score", None)
            criterion_payload.pop("judge_evidence", None)
        reason, code = _handle_judge_skip(
            f"{type(exc).__name__}: {exc}", code="judge_error"
        )
        return None, None, reason, code


def _handle_judge_skip(reason: str, *, code: str) -> tuple[str, str]:
    """Log a judge skip and enforce the ``judge_required`` policy.

    Returns ``(reason, code)`` so callers can thread both into the payload.
    ``code`` is machine-readable: ``"not_configured"`` (expected in key-free
    environments) or ``"judge_error"`` (a configured judge failed — worth
    paging on).

    Raises:
        JudgeRequiredError: ``evaluation.scoring.judge_required`` is ``True``.
    """
    if judge_required():
        raise JudgeRequiredError(
            "LLM judge is required (evaluation.scoring.judge_required=true) "
            f"but unavailable: {reason}"
        )
    logger.warning("Judge evaluation skipped [%s]: %s", code, reason)
    return reason, code


def _collect_floor_violations(
    criteria: list[dict[str, Any]],
    normalized_scores: dict[str, float],
) -> list[CriterionFloorResult]:
    """Collect criterion floor violations from explicit floors and backstops."""
    floor_violations: list[CriterionFloorResult] = []

    def _record_floor_failure(name: str, floor: float, value: float) -> None:
        existing = {violation.criterion for violation in floor_violations}
        if name in existing:
            return
        if value < floor:
            floor_violations.append(
                CriterionFloorResult(
                    criterion=name,
                    floor=floor,
                    normalized_score=value,
                )
            )

    for criterion_payload in criteria:
        critical_floor = criterion_payload.get("critical_floor")
        if critical_floor is not None:
            _record_floor_failure(
                str(criterion_payload["criterion"]),
                float(critical_floor),
                float(criterion_payload["normalized_score"]),
            )

    for correctness_key in ("correctness", "correctness_rubric"):
        if correctness_key in normalized_scores:
            # Legacy workflows may omit explicit floors, so keep a conservative
            # correctness minimum to prevent a high aggregate from masking misses.
            _record_floor_failure(
                correctness_key, 0.70, normalized_scores[correctness_key]
            )
            break

    for validation_key in ("safety_validation", "validation", "safety", "code_quality"):
        if validation_key in normalized_scores:
            # Apply the same backstop to safety/validation-style criteria even
            # when the workflow YAML does not declare a critical floor.
            _record_floor_failure(
                validation_key, 0.80, normalized_scores[validation_key]
            )
            break

    return floor_violations


def _resolve_dataset_compatible(
    dataset_meta: dict[str, Any] | None,
    *,
    dataset_sample: dict[str, Any] | None,
    workflow_definition: WorkflowDefinition | None,
    match_workflow_dataset_fn: Callable[
        [WorkflowDefinition, dict[str, Any]], tuple[bool, list[str]]
    ],
) -> bool:
    """Determine dataset/workflow compatibility from metadata or by matching.

    Prefers a pre-computed ``dataset_workflow_compatible`` flag in
    ``dataset_meta``; otherwise re-derives it via ``match_workflow_dataset_fn``.
    """
    if isinstance(dataset_meta, dict) and "dataset_workflow_compatible" in dataset_meta:
        return bool(dataset_meta["dataset_workflow_compatible"])
    if workflow_definition is not None and isinstance(dataset_sample, dict):
        compatible, _ = match_workflow_dataset_fn(workflow_definition, dataset_sample)
        return compatible
    return True


def _finalize_grade_and_pass(
    grade: str,
    *,
    weighted_score: float,
    threshold: float,
    floor_violations: list[CriterionFloorResult],
    hard_gates: HardGateResult,
    enforce_hard_gates: bool,
) -> tuple[str, bool, bool]:
    """Apply floor-cap and hard-gate rules to the grade and compute pass/fail.

    Returns ``(grade, grade_capped, passed)``.
    """
    no_floor_violations = len(floor_violations) == 0
    grade_capped = False
    if no_floor_violations is False and grade in {"A", "B", "C"}:
        # Floor failures do not automatically fail the run, but they prevent a
        # strong aggregate score from earning a strong letter grade.
        grade = "D"
        grade_capped = True

    if hard_gates.all_passed is False and enforce_hard_gates:
        # Hard gates are absolute release blockers, so they always dominate the
        # softer weighted score and floor logic.
        grade = "F"
        grade_capped = False

    passed = (weighted_score >= threshold) and no_floor_violations
    if enforce_hard_gates:
        passed = passed and hard_gates.all_passed

    return grade, grade_capped, passed


@dataclass
class _ScoreLayers:
    """Intermediate score artifacts produced by the layered scoring pass.

    Bundles the per-criterion payloads, the objective/advisory/judge/hybrid
    score layers, and the running aggregates so the orchestrator can assemble
    the final payload without threading a dozen positional values.
    """

    criteria: list[dict[str, Any]]
    normalized_scores: dict[str, float]
    objective_score_0_1: float
    objective_weighted_score: float
    advisory_similarity_0_1: float
    advisory_efficiency_0_1: float
    advisory_score_0_1: float
    judge_result: JudgeEvaluationResult | None
    judge_score_0_1: float | None
    judge_skip_reason: str | None
    judge_skip_code: str | None
    weighted_score: float
    overall_score: float
    active_hybrid_weights: dict[str, float]


def _compute_score_layers(
    result: WorkflowResult,
    *,
    weights: dict[str, float],
    criteria_by_name: dict[str, WorkflowCriterion],
    expected_text: str,
    judge: LLMJudge | None,
    hybrid_component_weights: dict[str, float] | None,
    compute_criterion_score_fn: Callable[[str, WorkflowResult, str], float],
) -> _ScoreLayers:
    """Compute the objective, advisory, judge, and hybrid score layers.

    Runs per-criterion scoring, derives the advisory similarity/efficiency
    heuristics, applies the optional LLM judge (annotating criterion payloads
    in place), and composes the hybrid 0--100 weighted score.
    """
    total_weight = sum(weights.values()) or 1.0
    criteria, normalized_scores, weighted_sum, raw_sum = _compute_criteria_scores(
        weights,
        result=result,
        expected_text=expected_text,
        criteria_by_name=criteria_by_name,
        compute_criterion_score_fn=compute_criterion_score_fn,
    )

    objective_score_0_1 = weighted_sum / total_weight
    generated_text = _output_text(result)
    advisory_similarity_0_1 = _advisory_similarity_score(
        expected_text=expected_text,
        generated_text=generated_text,
        objective_score_0_1=objective_score_0_1,
    )
    advisory_efficiency_0_1 = _advisory_efficiency_score(
        result=result,
        normalized_scores=normalized_scores,
    )
    advisory_score_0_1 = (advisory_similarity_0_1 * 0.67) + (
        advisory_efficiency_0_1 * 0.33
    )

    judge_result, judge_score_0_1, judge_skip_reason, judge_skip_code = (
        _apply_judge_scores(
            judge,
            criteria=criteria,
            weights=weights,
            criteria_by_name=criteria_by_name,
            generated_text=generated_text,
            expected_text=expected_text,
        )
    )

    hybrid_score_0_1, active_hybrid_weights = _compose_hybrid_score(
        objective_score_0_1=objective_score_0_1,
        advisory_score_0_1=advisory_score_0_1,
        judge_score_0_1=judge_score_0_1,
        component_weights=hybrid_component_weights,
    )

    return _ScoreLayers(
        criteria=criteria,
        normalized_scores=normalized_scores,
        objective_score_0_1=objective_score_0_1,
        objective_weighted_score=objective_score_0_1 * 100.0,
        advisory_similarity_0_1=advisory_similarity_0_1,
        advisory_efficiency_0_1=advisory_efficiency_0_1,
        advisory_score_0_1=advisory_score_0_1,
        judge_result=judge_result,
        judge_score_0_1=judge_score_0_1,
        judge_skip_reason=judge_skip_reason,
        judge_skip_code=judge_skip_code,
        weighted_score=hybrid_score_0_1 * 100.0,
        overall_score=raw_sum / len(criteria) if criteria else 0.0,
        active_hybrid_weights=active_hybrid_weights,
    )


def _build_base_payload(
    layers: _ScoreLayers,
    *,
    result: WorkflowResult,
    rubric_id: str,
    rubric_version: str,
    grade: str,
    threshold: float,
    dataset_meta: dict[str, Any] | None,
    expected_text_present: bool,
) -> dict[str, Any]:
    """Assemble the pre-gate evaluation payload from the computed score layers.

    The ``passed`` flag and hard-gate/floor fields are filled in later by
    :func:`_attach_gate_results`; this builds the deterministic score body.
    """
    judge_score_0_1 = layers.judge_score_0_1
    return {
        "enabled": True,
        "rubric": rubric_id,
        "rubric_id": rubric_id,
        "rubric_version": rubric_version,
        "criteria": layers.criteria,
        "overall_score": round(layers.overall_score, 2),
        "weighted_score": round(layers.weighted_score, 2),
        "objective_weighted_score": round(layers.objective_weighted_score, 2),
        "grade": grade,
        "passed": False,
        "pass_threshold": threshold,
        "step_scores": _step_scores(result),
        "dataset": dataset_meta,
        "score_layers": {
            "layer1_objective": round(layers.objective_score_0_1 * 100.0, 2),
            "layer2_judge": (
                None if judge_score_0_1 is None else round(judge_score_0_1 * 100.0, 2)
            ),
            "layer3_similarity": round(layers.advisory_similarity_0_1 * 100.0, 2),
            "layer3_efficiency": round(layers.advisory_efficiency_0_1 * 100.0, 2),
            "layer3_advisory": round(layers.advisory_score_0_1 * 100.0, 2),
        },
        "hybrid_weights": layers.active_hybrid_weights,
        "judge": (
            layers.judge_result.to_payload()
            if layers.judge_result is not None
            else None
        ),
        "judge_skipped": judge_score_0_1 is None,
        "judge_skip_reason": layers.judge_skip_reason,
        "judge_skip_code": layers.judge_skip_code,
        # False means the overlap/similarity term never engaged (no inline
        # expected text and no resolvable golden) — the score is shape-only.
        "expected_text_present": expected_text_present,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _apply_gates_and_finalize(
    payload: dict[str, Any],
    *,
    result: WorkflowResult,
    layers: _ScoreLayers,
    grade: str,
    threshold: float,
    floor_violations: list[CriterionFloorResult],
    dataset_meta: dict[str, Any] | None,
    dataset_sample: dict[str, Any] | None,
    workflow_definition: WorkflowDefinition | None,
    enforce_hard_gates: bool,
    match_workflow_dataset_fn: Callable[
        [WorkflowDefinition, dict[str, Any]], tuple[bool, list[str]]
    ],
) -> dict[str, Any]:
    """Resolve hard gates, finalize the grade/pass verdict, and enrich payload.

    Determines dataset/workflow compatibility, runs the hard gates against the
    base payload, applies floor-cap and hard-gate rules to the grade, and
    returns a new payload with the gate-derived fields attached.
    """
    dataset_compatible = _resolve_dataset_compatible(
        dataset_meta,
        dataset_sample=dataset_sample,
        workflow_definition=workflow_definition,
        match_workflow_dataset_fn=match_workflow_dataset_fn,
    )

    hard_gates = compute_hard_gates(
        result,
        workflow_outputs=workflow_definition.outputs if workflow_definition else None,
        eval_payload=payload,
        dataset_workflow_compatible=dataset_compatible,
    )

    grade, grade_capped, passed = _finalize_grade_and_pass(
        grade,
        weighted_score=layers.weighted_score,
        threshold=threshold,
        floor_violations=floor_violations,
        hard_gates=hard_gates,
        enforce_hard_gates=enforce_hard_gates,
    )

    return _attach_gate_results(
        payload,
        hard_gates=hard_gates,
        floor_violations=floor_violations,
        grade=grade,
        grade_capped=grade_capped,
        passed=passed,
    )


def _attach_gate_results(
    payload: dict[str, Any],
    *,
    hard_gates: HardGateResult,
    floor_violations: list[CriterionFloorResult],
    grade: str,
    grade_capped: bool,
    passed: bool,
) -> dict[str, Any]:
    """Return a new payload with hard-gate, floor, and final grade fields set.

    Does not mutate ``payload`` in place; returns a shallow copy with the
    gate-derived keys added so the caller keeps an immutable update boundary.
    """
    enriched = dict(payload)
    enriched["hard_gates"] = {
        "required_outputs_present": hard_gates.required_outputs_present,
        "overall_status_success": hard_gates.overall_status_success,
        "no_critical_step_failures": hard_gates.no_critical_step_failures,
        "release_build_verified": hard_gates.release_build_verified,
        "schema_contract_valid": hard_gates.schema_contract_valid,
        "dataset_workflow_compatible": hard_gates.dataset_workflow_compatible,
    }
    enriched["hard_gate_failures"] = hard_gates.failures
    enriched["floor_violations"] = [
        {
            "criterion": violation.criterion,
            "floor": round(violation.floor, 4),
            "normalized_score": round(violation.normalized_score, 4),
        }
        for violation in floor_violations
    ]
    enriched["grade_capped"] = grade_capped
    enriched["grade"] = grade
    enriched["passed"] = passed
    return enriched


def score_workflow_result_impl(
    result: WorkflowResult,
    *,
    dataset_meta: dict[str, Any] | None,
    dataset_sample: dict[str, Any] | None,
    rubric: str | None = None,
    workflow_definition: WorkflowDefinition | None = None,
    enforce_hard_gates: bool = True,
    judge: LLMJudge | None = None,
    hybrid_component_weights: dict[str, float] | None = None,
    compute_criterion_score_fn: Callable[
        [str, WorkflowResult, str], float
    ] = _compute_criterion_score,
    match_workflow_dataset_fn: Callable[
        [WorkflowDefinition, dict[str, Any]], tuple[bool, list[str]]
    ] = match_workflow_dataset,
) -> dict[str, Any]:
    """Produce criterion-level and aggregate scores for a workflow result.

    Orchestrates the full three-stage scoring pipeline:

    1. Resolve rubric weights and compute per-criterion raw and normalized
       scores using ``compute_criterion_score_fn``.
    2. Compute advisory heuristic scores (similarity + efficiency) and
       optionally invoke the LLM Judge for each criterion.
    3. Compose a hybrid weighted score, map to a letter grade, enforce
       criterion floor violations and hard gates, and assemble the final
       evaluation payload dict.

    Args:
        result: Completed workflow execution result.
        dataset_meta: Metadata about the dataset source and sample index.
        dataset_sample: Raw dataset sample dict (for expected-text extraction).
        rubric: Optional rubric ID override.
        workflow_definition: Loaded workflow definition for rubric and output info.
        enforce_hard_gates: If True, hard-gate failures force grade ``F``.
        judge: Optional :class:`LLMJudge` instance for hybrid scoring.
        hybrid_component_weights: Optional override for hybrid component weights.
        compute_criterion_score_fn: Criterion scoring function (injectable for tests).
        match_workflow_dataset_fn: Dataset compatibility checker (injectable for tests).

    Returns:
        Evaluation payload dict containing criteria scores, grades, hard gates,
        floor violations, score layers, judge results, and pass/fail status.
    """
    rubric_id, rubric_version, weights, criteria_by_name = _resolve_rubric(
        workflow_definition,
        rubric,
    )
    expected_text = _extract_expected_text(dataset_sample or {})

    layers = _compute_score_layers(
        result,
        weights=weights,
        criteria_by_name=criteria_by_name,
        expected_text=expected_text,
        judge=judge,
        hybrid_component_weights=hybrid_component_weights,
        compute_criterion_score_fn=compute_criterion_score_fn,
    )

    threshold = pass_threshold()
    grade = _grade(layers.weighted_score)
    floor_violations = _collect_floor_violations(
        layers.criteria, layers.normalized_scores
    )

    payload = _build_base_payload(
        layers,
        result=result,
        rubric_id=rubric_id,
        rubric_version=rubric_version,
        grade=grade,
        threshold=threshold,
        dataset_meta=dataset_meta,
        expected_text_present=bool(expected_text),
    )

    return _apply_gates_and_finalize(
        payload,
        result=result,
        layers=layers,
        grade=grade,
        threshold=threshold,
        floor_violations=floor_violations,
        dataset_meta=dataset_meta,
        dataset_sample=dataset_sample,
        workflow_definition=workflow_definition,
        enforce_hard_gates=enforce_hard_gates,
        match_workflow_dataset_fn=match_workflow_dataset_fn,
    )


__all__ = [
    "CriterionFloorResult",
    "HardGateResult",
    "JudgeRequiredError",
    "_build_judge_criteria",
    "_clamp",
    "_compose_hybrid_score",
    "_compute_criterion_score",
    "_extract_expected_text",
    "_grade",
    "_output_text",
    "_resolve_rubric",
    "_step_scores",
    "_text_overlap_score",
    "_tokenize",
    "_validate_rubric_weights",
    "compute_hard_gates",
    "judge_required",
    "pass_threshold",
    "score_workflow_result_impl",
    "validate_evaluation_payload_schema",
]
