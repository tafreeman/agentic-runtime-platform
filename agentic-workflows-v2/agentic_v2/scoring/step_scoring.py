"""Advisory step scoring: output presence never implies quality or a pass."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING, Any

from . import evalkit_bridge
from .rubrics import load_rubric

if TYPE_CHECKING:
    from ..engine.executor import ExecutorEvent

logger = logging.getLogger(__name__)
AGENT_RUBRIC_MAP = {
    "coder": "code",
    "architect": "agent",
    "reviewer": "agent",
    "orchestrator": "agent",
    "researcher": "agent",
}
_DEFAULT_RUBRIC = "default"
_RUBRIC_THRESHOLDS = {"code": 0.75, "agent": 0.70, "default": 0.60}


def _rubric_for_agent(agent_type: str) -> str:
    return AGENT_RUBRIC_MAP.get(agent_type.lower(), _DEFAULT_RUBRIC)


def _pass_threshold(rubric_name: str, rubric_data: dict[str, Any]) -> float:
    thresholds = rubric_data.get("thresholds", {})
    if isinstance(thresholds, dict) and thresholds.get("pass") is not None:
        return float(thresholds["pass"])
    return _RUBRIC_THRESHOLDS.get(rubric_name, 0.60)


def _infer_agent_type(step_name: str) -> str:
    return next(
        (agent for agent in AGENT_RUBRIC_MAP if agent in step_name.lower()), "unknown"
    )


def _output_to_text(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, dict):
        return "\n".join(str(v) for v in output.values() if v is not None)
    return str(output)


class ScoreStatus(StrEnum):
    """Missing evidence is neither task failure nor a pass."""

    SCORED = "scored"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CriterionEvidence:
    """Trusted deterministic check result, never parsed from agent output.

    Model judges require a separate calibration/authority policy before adoption.
    """

    score: float
    evidence: str

    def __post_init__(self) -> None:
        if isinstance(self.score, bool) or not isfinite(self.score):
            raise ValueError("criterion score must be finite and numeric")
        if not 0 <= self.score <= 1 or not self.evidence.strip():
            raise ValueError("criterion evidence needs a score in [0, 1] and a reason")


def exact_match_evidence(expected: str, actual: str) -> CriterionEvidence:
    """Measure exact text equality only, without claiming holistic quality."""
    matched = expected == actual
    return CriterionEvidence(
        float(matched),
        "Exact text equality: " + ("matched" if matched else "different"),
    )


StepGrader = Callable[[str, str, str], Mapping[str, CriterionEvidence]]


@dataclass(frozen=True)
class StepScore:
    """Advisory quality result; unavailable has null score and pass fields."""

    step_name: str
    agent_type: str
    rubric_name: str
    weighted_score: float | None
    criterion_scores: dict[str, float]
    passed: bool | None
    timestamp: str
    status: ScoreStatus
    reason: str | None = None
    output_present: bool = False
    evidence: dict[str, str] = field(default_factory=dict)


def score_step(
    step_name: str,
    agent_type: str,
    output_text: str,
    *,
    criterion_evidence: Mapping[str, CriterionEvidence] | None = None,
    unavailable_reason: str | None = None,
) -> StepScore:
    """Aggregate evidence via EVK only when every positive-weight criterion is measured.

    The bridge preserves legacy missing-as-zero arithmetic for existing callers;
    runtime scoring deliberately refuses to treat absent evidence as a zero.
    """
    rubric_name = _rubric_for_agent(agent_type)

    def unavailable(reason: str) -> StepScore:
        return StepScore(
            step_name,
            agent_type,
            rubric_name,
            None,
            {},
            None,
            datetime.now(UTC).isoformat(),
            ScoreStatus.UNAVAILABLE,
            reason=reason,
            output_present=bool(output_text.strip()),
        )

    if unavailable_reason:
        return unavailable(unavailable_reason)
    if not evalkit_bridge.EVALKIT_AVAILABLE:
        return unavailable("evalkit_not_installed")
    try:
        try:
            rubric_data = load_rubric(rubric_name)
        except FileNotFoundError:
            rubric_name = _DEFAULT_RUBRIC
            rubric_data = load_rubric(rubric_name)
        rubric = evalkit_bridge.rubric_from_yaml_dict(rubric_data)
        if not criterion_evidence:
            return unavailable("criterion_evidence_missing")
        required = {c.criterion_id for c in rubric.criteria if c.weight > 0}
        known = {c.criterion_id for c in rubric.criteria}
        if not required or not required.issubset(criterion_evidence):
            return unavailable("criterion_evidence_incomplete")
        if not set(criterion_evidence).issubset(known):
            return unavailable("criterion_evidence_unknown")
        scores = {}
        evidence = {}
        for name, item in criterion_evidence.items():
            if not isinstance(item, CriterionEvidence):
                return unavailable("criterion_evidence_invalid")
            scores[name] = item.score
            evidence[name] = item.evidence
        weighted = evalkit_bridge.score_criteria(rubric_data, scores)
        threshold = _pass_threshold(rubric_name, rubric_data)
        if not isfinite(weighted) or not isfinite(threshold) or not 0 <= threshold <= 1:
            return unavailable("rubric_invalid")
    except (FileNotFoundError, ValueError, TypeError, RuntimeError):
        logger.warning("Step scoring unavailable for %s", step_name, exc_info=True)
        return unavailable("rubric_unavailable")
    return StepScore(
        step_name,
        agent_type,
        rubric_name,
        weighted,
        scores,
        weighted >= threshold,
        datetime.now(UTC).isoformat(),
        ScoreStatus.SCORED,
        output_present=bool(output_text.strip()),
        evidence=evidence,
    )


@dataclass
class StepScoringListener:
    """Collect observations with a trusted grader; ignore scores in event/output data.

    Missing graders/dependencies produce unavailable diagnostics. These results
    do not authorize tools or route execution; gates must explicitly require SCORED.
    """

    enabled: bool = True
    scores: list[StepScore] = field(default_factory=list)
    grader: StepGrader | None = None

    def _score(self, step_name: str, payload: dict[str, Any]) -> StepScore:
        agent_type = _infer_agent_type(step_name)
        output_text = _output_to_text(payload.get("output"))
        status = payload.get("status")
        if status is not None and str(getattr(status, "value", status)).lower() not in {
            "success",
            "succeeded",
            "completed",
        }:
            return score_step(
                step_name,
                agent_type,
                output_text,
                unavailable_reason="execution_not_completed",
            )
        evidence = None
        if self.grader is not None:
            try:
                evidence = self.grader(step_name, agent_type, output_text)
                if not isinstance(evidence, Mapping):
                    raise TypeError("grader must return criterion evidence")
            except Exception:
                logger.warning("Step grader failed for %s", step_name, exc_info=True)
                return score_step(
                    step_name,
                    agent_type,
                    output_text,
                    unavailable_reason="grader_failed",
                )
        return score_step(
            step_name, agent_type, output_text, criterion_evidence=evidence
        )

    def __call__(self, event: ExecutorEvent, payload: dict[str, Any]) -> None:
        """Handle synchronous WorkflowExecutor STEP_END events."""
        from ..engine.executor import ExecutorEvent as _ExecutorEvent

        if not self.enabled or event != _ExecutorEvent.STEP_END:
            return
        step_name = str(payload.get("step", ""))
        if step_name:
            self.scores = [*self.scores, self._score(step_name, payload)]

    async def handle_update(self, event: dict[str, Any]) -> None:
        """Handle asynchronous DAG/server step_end events."""
        if not self.enabled or event.get("type") != "step_end":
            return
        step_name = str(event.get("step", ""))
        if step_name:
            self.scores = [*self.scores, self._score(step_name, event)]

    def get_scores(self) -> list[StepScore]:
        return list(self.scores)

    def get_summary(self) -> dict[str, Any]:
        """Exclude unavailable observations from averages and pass counts."""
        scored = [s for s in self.scores if s.status is ScoreStatus.SCORED]
        values = [s.weighted_score for s in scored if s.weighted_score is not None]
        return {
            "total_steps": len(self.scores),
            "scored_steps": len(scored),
            "unavailable": len(self.scores) - len(scored),
            "passed": sum(s.passed is True for s in scored),
            "avg_score": round(sum(values) / len(values), 4) if values else None,
            "step_scores": [
                {
                    "step_name": s.step_name,
                    "agent_type": s.agent_type,
                    "rubric_name": s.rubric_name,
                    "weighted_score": (
                        round(s.weighted_score, 4)
                        if s.weighted_score is not None
                        else None
                    ),
                    "criterion_scores": s.criterion_scores,
                    "passed": s.passed,
                    "timestamp": s.timestamp,
                    "status": s.status.value,
                    "reason": s.reason,
                    "output_present": s.output_present,
                    "evidence": s.evidence,
                }
                for s in self.scores
            ],
        }


def build_step_scoring_listener(
    *, grader: StepGrader | None = None
) -> StepScoringListener:
    """Collect diagnostics even without EVK; unavailable never grants a pass."""
    return StepScoringListener(grader=grader)
