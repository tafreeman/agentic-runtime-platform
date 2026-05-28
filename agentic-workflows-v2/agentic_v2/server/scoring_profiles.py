"""Predefined scoring profiles (A--E) for workflow-family evaluation.

Each profile defines criterion weights and optional extra hard-gate hints
tailored to a specific workflow category:

* **Profile A** -- Code repair / SWE-style iterative workflows.
  Emphasizes ``objective_tests`` (60%) with ``fail_to_pass`` gate.
* **Profile B** (default) -- DAG generation/review workflows.
  Balanced across ``correctness_rubric``, ``code_quality``, ``efficiency``,
  ``documentation``.
* **Profile C** -- RAG (Retrieval-Augmented Generation) workflows.
  Prioritizes ``faithfulness`` and ``relevance`` with an
  ``answer_grounded`` gate.
* **Profile D** -- Agentic tool-use/routing workflows.
  Weights ``task_completion`` and ``tool_selection_accuracy`` with a
  ``tool_call_schema_valid`` gate.
* **Profile E** -- Deep research iterative pipelines (ADR-007).
  Five research dimensions with ``all_dimensions_high``,
  ``no_critical_contradictions``, and ``sources_floor`` gates.

Profiles are selected via the ``scoring_profile`` field in a workflow's
``evaluation`` section.  :func:`get_profile` resolves a profile ID to its
:class:`ScoringProfile` instance, falling back to the default (B).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class ScoringProfile:
    """Immutable scoring profile binding criterion weights to a workflow family.

    Attributes:
        profile_id: Single-letter identifier (``"A"``--``"E"``).
        description: Human-readable summary of the workflow family.
        weights: Immutable mapping of criterion name to weight (sums to 1.0).
            Converted to ``MappingProxyType`` in ``__post_init__``.
        extra_gates: Additional hard-gate names beyond the standard set
            (informational; not enforced automatically by the scorer).
    """

    profile_id: str
    description: str
    weights: Mapping[str, float]
    extra_gates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))
        object.__setattr__(self, "extra_gates", tuple(self.extra_gates))


SCORING_PROFILES: dict[str, ScoringProfile] = {
    "A": ScoringProfile(
        profile_id="A",
        description="Code repair / SWE-style iterative workflows",
        weights={
            "objective_tests": 0.60,
            "code_quality": 0.20,
            "efficiency": 0.10,
            "documentation": 0.10,
        },
        extra_gates=("fail_to_pass",),
    ),
    "B": ScoringProfile(
        profile_id="B",
        description="DAG generation/review workflows",
        weights={
            "correctness_rubric": 0.35,
            "code_quality": 0.30,
            "efficiency": 0.20,
            "documentation": 0.15,
        },
        extra_gates=("required_outputs_parseable",),
    ),
    "C": ScoringProfile(
        profile_id="C",
        description="RAG workflows",
        weights={
            "faithfulness": 0.35,
            "relevance": 0.30,
            "citation_quality": 0.20,
            "coherence": 0.15,
        },
        extra_gates=("answer_grounded",),
    ),
    "D": ScoringProfile(
        profile_id="D",
        description="Agentic tool-use/routing workflows",
        weights={
            "tool_selection_accuracy": 0.25,
            "task_completion": 0.30,
            "efficiency": 0.25,
            "coherence": 0.20,
        },
        extra_gates=("tool_call_schema_valid",),
    ),
    "E": ScoringProfile(
        profile_id="E",
        description=(
            "Deep research iterative pipeline"
            " (ADR-007 multidimensional tiebreaker weights)"
        ),
        weights={
            "coverage": 0.25,
            "source_quality": 0.20,
            "agreement": 0.20,
            "verification": 0.20,
            "recency": 0.15,
        },
        extra_gates=(
            "all_dimensions_high",
            "no_critical_contradictions",
            "sources_floor",
        ),
    ),
}

DEFAULT_PROFILE_ID = "B"


def get_profile(profile_id: str | None) -> ScoringProfile:
    """Return a scoring profile by ID, falling back to the default (B).

    Args:
        profile_id: Profile identifier (``"A"``--``"E"``), or None/empty
            to use the default.

    Returns:
        The matching :class:`ScoringProfile`, or the default profile
        if the ID is unknown or not provided.
    """
    if not profile_id:
        return SCORING_PROFILES[DEFAULT_PROFILE_ID]
    return SCORING_PROFILES.get(profile_id, SCORING_PROFILES[DEFAULT_PROFILE_ID])
