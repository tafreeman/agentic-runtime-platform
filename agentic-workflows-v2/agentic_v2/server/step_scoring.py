"""Per-agent step scoring listener for the workflow executor.

Registers on ExecutorEvent.STEP_END and scores each completed step
using the rubric that matches the step's agent type.

The listener is designed to work with two integration points:

1. ``WorkflowExecutor.add_listener()`` — synchronous callback interface
   (``ExecutorEvent.STEP_END`` payload has keys ``step`` and ``status``).
2. ``DAGExecutor`` / ``_run_via_native_adapter`` ``on_update`` callbacks —
   async callback interface with richer payload (keys ``type``, ``step``,
   ``status``, ``output``, ``tier``, etc.).

The actual server execution path goes through the ``on_update`` pattern, so
:class:`StepScoringListener` exposes both ``__call__`` (sync, for
``WorkflowExecutor``) and ``handle_update`` (async, for ``on_update``).
:func:`build_step_scoring_on_update` wraps the listener as an async callback
suitable for direct injection into ``_run_via_native_adapter``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..engine.executor import ExecutorEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional agentic_v2_eval import guard
# ---------------------------------------------------------------------------

_EVAL_AVAILABLE = False
try:
    from agentic_v2_eval.rubrics import load_rubric
    from agentic_v2_eval.scorer import Scorer

    _EVAL_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Agent → rubric mapping
# ---------------------------------------------------------------------------

AGENT_RUBRIC_MAP: dict[str, str] = {
    "coder": "code",
    "architect": "agent",
    "reviewer": "agent",
    "orchestrator": "agent",
    "researcher": "agent",
}

_DEFAULT_RUBRIC = "default"

# Rubric-level pass thresholds (0.0–1.0); loaded lazily from YAML thresholds.
_RUBRIC_THRESHOLDS: dict[str, float] = {
    "code": 0.75,
    "agent": 0.70,
    "default": 0.60,
}


def _rubric_for_agent(agent_type: str) -> str:
    """Return the rubric name for a given agent type.

    Falls back to :data:`_DEFAULT_RUBRIC` for unmapped agent types.
    """
    return AGENT_RUBRIC_MAP.get(agent_type.lower(), _DEFAULT_RUBRIC)


def _pass_threshold(rubric_name: str, rubric_data: dict[str, Any]) -> float:
    """Extract the pass threshold from rubric YAML data or fall back to defaults."""
    thresholds = rubric_data.get("thresholds", {})
    if isinstance(thresholds, dict):
        raw = thresholds.get("pass")
        if raw is not None:
            try:
                return float(raw)
            except (ValueError, TypeError):
                pass
    return _RUBRIC_THRESHOLDS.get(rubric_name, 0.60)


def _infer_agent_type(step_name: str) -> str:
    """Infer agent type from step name using known prefixes/keywords.

    Returns the lowercase agent type string (e.g. ``"coder"``) or
    ``"unknown"`` when no known agent type is found in the step name.
    """
    lowered = step_name.lower()
    for agent in AGENT_RUBRIC_MAP:
        if agent in lowered:
            return agent
    return "unknown"


def _output_to_text(output: Any) -> str:
    """Convert a step output value to a plain text string for scoring."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        parts: list[str] = []
        for value in output.values():
            if isinstance(value, str):
                parts.append(value)
            elif value is not None:
                parts.append(str(value))
        return "\n".join(parts)
    return str(output)


# ---------------------------------------------------------------------------
# StepScore dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepScore:
    """Immutable scoring result for a single completed workflow step.

    Attributes:
        step_name: Name of the step as declared in the workflow YAML.
        agent_type: Inferred or declared agent type (e.g. ``"coder"``).
        rubric_name: Name of the rubric used for scoring.
        weighted_score: Aggregate weighted score in ``[0.0, 1.0]``.
        criterion_scores: Per-criterion raw scores keyed by criterion name.
        passed: ``True`` when ``weighted_score`` meets the rubric threshold.
        timestamp: ISO-8601 UTC timestamp of when scoring completed.
    """

    step_name: str
    agent_type: str
    rubric_name: str
    weighted_score: float
    criterion_scores: dict[str, float]
    passed: bool
    timestamp: str


# ---------------------------------------------------------------------------
# Core scoring function
# ---------------------------------------------------------------------------


def score_step(
    step_name: str,
    agent_type: str,
    output_text: str,
) -> StepScore | None:
    """Score a completed step against its agent-appropriate rubric.

    Args:
        step_name: Name of the step (for labeling the result).
        agent_type: Agent type string used to select the rubric via
            :data:`AGENT_RUBRIC_MAP`.  Falls back to ``"default"`` rubric
            when unmapped.
        output_text: Plain-text content of the step's output, used as a
            proxy signal for criterion scoring.

    Returns:
        A frozen :class:`StepScore` on success, or ``None`` when
        ``agentic_v2_eval`` is not installed.

    Note:
        Criterion scores are derived from output text length and presence
        as a lightweight heuristic because the rubric ``Scorer`` requires
        explicit float values per criterion name.  A non-empty output
        receives a neutral 0.7 score for all criteria; an empty output
        receives 0.0.  This is intentionally simple — the primary value
        is rubric selection, not LLM-judge evaluation at step granularity.
    """
    if not _EVAL_AVAILABLE:
        return None

    rubric_name = _rubric_for_agent(agent_type)

    try:
        rubric_data = load_rubric(rubric_name)
    except FileNotFoundError:
        logger.warning(
            "Rubric %r not found for step %r; falling back to default",
            rubric_name,
            step_name,
        )
        rubric_name = _DEFAULT_RUBRIC
        try:
            rubric_data = load_rubric(rubric_name)
        except FileNotFoundError:
            logger.error("Default rubric not found; cannot score step %r", step_name)
            return None

    scorer = Scorer(rubric_data)

    # Build a minimal results dict: one entry per criterion name.
    # Use a heuristic score based on output presence.
    base_score = 0.7 if output_text.strip() else 0.0
    results: dict[str, float] = {
        criterion.name: base_score for criterion in scorer.criteria
    }

    scoring_result = scorer.score(results)
    threshold = _pass_threshold(rubric_name, rubric_data)

    return StepScore(
        step_name=step_name,
        agent_type=agent_type,
        rubric_name=rubric_name,
        weighted_score=scoring_result.weighted_score,
        criterion_scores=dict(scoring_result.criterion_scores),
        passed=scoring_result.weighted_score >= threshold,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# StepScoringListener
# ---------------------------------------------------------------------------


@dataclass
class StepScoringListener:
    """Callable listener that scores each completed step.

    Works with:

    * ``WorkflowExecutor.add_listener()`` — via synchronous ``__call__``
      which consumes ``ExecutorEvent.STEP_END`` payloads (keys: ``step``,
      ``status``).
    * ``DAGExecutor`` ``on_update`` callback — via ``handle_update`` which
      consumes the richer async payload (keys: ``type``, ``step``,
      ``status``, ``output``).

    Attributes:
        enabled: Whether scoring is active.  Set to ``False`` when
            ``agentic_v2_eval`` is not importable.
        scores: Accumulated :class:`StepScore` results in insertion order.
    """

    enabled: bool = field(default=True)
    scores: list[StepScore] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.enabled and not _EVAL_AVAILABLE:
            logger.warning(
                "agentic_v2_eval is not installed; step scoring is disabled. "
                "Install with: pip install -e './agentic-v2-eval[dev]'"
            )
            self.enabled = False

    # ------------------------------------------------------------------
    # Synchronous interface — compatible with WorkflowExecutor.add_listener()
    # ------------------------------------------------------------------

    def __call__(self, event: ExecutorEvent, payload: dict[str, Any]) -> None:
        """Synchronous listener for ``WorkflowExecutor`` events.

        Only ``ExecutorEvent.STEP_END`` events are processed; all others
        are silently ignored.  The payload is expected to contain ``step``
        (step name) and optionally ``status``.
        """
        if not self.enabled:
            return

        # Import here to avoid circular import at module load time.
        from ..engine.executor import ExecutorEvent as _ExecutorEvent

        if event != _ExecutorEvent.STEP_END:
            return

        step_name: str = str(payload.get("step", ""))
        if not step_name:
            return

        # WorkflowExecutor STEP_END payload doesn't carry output or agent_type,
        # so we infer agent_type from the step name.
        agent_type = _infer_agent_type(step_name)
        output_text = _output_to_text(payload.get("output"))

        score = score_step(step_name, agent_type, output_text)
        if score is not None:
            self.scores = [*self.scores, score]

    # ------------------------------------------------------------------
    # Async interface — compatible with DAGExecutor on_update callbacks
    # ------------------------------------------------------------------

    async def handle_update(self, event: dict[str, Any]) -> None:
        """Async callback for ``DAGExecutor``/``on_update`` style events.

        Processes ``step_end`` events from the richer DAG payload format.
        All other event types are silently ignored.
        """
        if not self.enabled:
            return

        if event.get("type") != "step_end":
            return

        step_name = str(event.get("step", ""))
        if not step_name:
            return

        # The DAG payload includes 'tier' but not 'agent_type'; infer from name.
        agent_type = _infer_agent_type(step_name)
        output_text = _output_to_text(event.get("output"))

        score = score_step(step_name, agent_type, output_text)
        if score is not None:
            self.scores = [*self.scores, score]

    # ------------------------------------------------------------------
    # Result accessors
    # ------------------------------------------------------------------

    def get_scores(self) -> list[StepScore]:
        """Return all accumulated step scores in insertion order."""
        return list(self.scores)

    def get_summary(self) -> dict[str, Any]:
        """Return aggregate statistics across all scored steps.

        Returns:
            Dict with keys:

            * ``total_steps`` — number of steps scored.
            * ``passed`` — number of steps that met their rubric threshold.
            * ``avg_score`` — mean weighted score across all steps (0.0 when
              no steps have been scored).
            * ``step_scores`` — list of per-step score dicts.
        """
        if not self.scores:
            return {
                "total_steps": 0,
                "passed": 0,
                "avg_score": 0.0,
                "step_scores": [],
            }

        total = len(self.scores)
        passed = sum(1 for s in self.scores if s.passed)
        avg = sum(s.weighted_score for s in self.scores) / total

        step_scores = [
            {
                "step_name": s.step_name,
                "agent_type": s.agent_type,
                "rubric_name": s.rubric_name,
                "weighted_score": round(s.weighted_score, 4),
                "criterion_scores": s.criterion_scores,
                "passed": s.passed,
                "timestamp": s.timestamp,
            }
            for s in self.scores
        ]

        return {
            "total_steps": total,
            "passed": passed,
            "avg_score": round(avg, 4),
            "step_scores": step_scores,
        }


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def build_step_scoring_listener() -> StepScoringListener | None:
    """Create a :class:`StepScoringListener` if ``agentic_v2_eval`` is available.

    Returns:
        A new :class:`StepScoringListener` when the evaluation package is
        installed, ``None`` otherwise.  The ``None`` return allows callers
        to skip listener registration without error handling:

        .. code-block:: python

            scoring_listener = build_step_scoring_listener()
            if scoring_listener:
                executor.add_listener(scoring_listener)
    """
    if not _EVAL_AVAILABLE:
        logger.warning(
            "agentic_v2_eval is not installed; step scoring listener not created. "
            "Install with: pip install -e './agentic-v2-eval[dev]'"
        )
        return None

    return StepScoringListener(enabled=True)
