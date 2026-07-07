"""Pydantic wire models for the catalog, settings, and eval-comparison APIs.

Split out of :mod:`agentic_v2.server.models` (which is at its size budget).
Covers:

* ``GET /api/personas`` / ``GET /api/tools`` / ``GET /api/observers`` --
  catalogs the workflow editor uses to populate per-node pickers.
* ``GET/PUT /api/settings/providers`` -- user-managed provider endpoints.
* ``GET/PUT /api/settings/tiers`` -- model tier reranking + capability tags.
* ``POST /api/eval/compare`` -- side-by-side scoring of two run logs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..ui_settings import ProviderConfig
from .models import EvaluationCriterionDetail

# ---------------------------------------------------------------------------
# Catalog models (personas / tools / observers)
# ---------------------------------------------------------------------------


class PersonaInfo(BaseModel):
    """A selectable pre-canned persona.

    Attributes:
        id: Stable persona identifier referenced by ``step.persona``.
        name: Display name (e.g. ``"Winston"``).
        role: Underlying role bucket (architect, coder, reviewer, ...).
        description: One-paragraph summary shown in pickers.
        tags: Free-form grouping tags.
        prompt_preview: First lines of the resolved system prompt.
    """

    id: str
    name: str
    role: str = ""
    description: str = ""
    tags: list[str] = []
    prompt_preview: str = ""


class ListPersonasResponse(BaseModel):
    """Response for ``GET /api/personas``."""

    personas: list[PersonaInfo] = []


class ToolInfo(BaseModel):
    """A tool that can be allowlisted on a workflow step.

    Attributes:
        name: Tool identifier used in ``step.tools``.
        description: What the tool does (from its docstring).
        tiers: Model tiers whose default toolset includes this tool.
    """

    name: str
    description: str = ""
    tiers: list[int] = []


class ListToolsResponse(BaseModel):
    """Response for ``GET /api/tools``."""

    tools: list[ToolInfo] = []


class ObserverInfo(BaseModel):
    """An observer channel a step can enable via ``step.observers``.

    Attributes:
        id: Channel identifier (``trace`` / ``websocket`` / ``scoring``).
        description: What subscribes to this channel.
    """

    id: str
    description: str = ""


class ListObserversResponse(BaseModel):
    """Response for ``GET /api/observers``."""

    observers: list[ObserverInfo] = []


# ---------------------------------------------------------------------------
# Provider settings
# ---------------------------------------------------------------------------


class ProviderSettingsResponse(BaseModel):
    """Response for ``GET /api/settings/providers``.

    Attributes:
        providers: User-configured provider endpoint entries.
        provider_types: Known provider families the UI can offer in the
            "add provider" flow.
        env_configured_providers: Provider families already usable via
            environment credentials (informational; read-only here).
    """

    providers: list[ProviderConfig] = []
    provider_types: list[str] = []
    env_configured_providers: list[str] = []


class ProviderSettingsUpdateRequest(BaseModel):
    """Request body for ``PUT /api/settings/providers`` (full replacement)."""

    providers: list[ProviderConfig] = []


# ---------------------------------------------------------------------------
# Tier settings (reranking + capabilities)
# ---------------------------------------------------------------------------


class TierModelInfo(BaseModel):
    """One model as presented on the tier-configuration surface.

    Attributes:
        id: Prefixed model id (``provider:name``).
        provider: Provider prefix.
        capabilities: Effective capability tags (registry + user overrides).
        capability_overridden: True when the user has overridden capabilities.
    """

    id: str
    provider: str = ""
    capabilities: list[str] = []
    capability_overridden: bool = False


class TierChainModel(BaseModel):
    """Ranking state for one model tier.

    Attributes:
        tier: Tier number (0--5).
        default_chain: Registry-defined fallback chain for the tier.
        override: User-defined ranking from the settings store (empty when
            the registry default is active).
        effective: The ranking actually used by routing (override first,
            then the default chain).
    """

    tier: int
    default_chain: list[str] = []
    override: list[str] = []
    effective: list[str] = []


class TierSettingsResponse(BaseModel):
    """Response for ``GET /api/settings/tiers``.

    Attributes:
        tiers: Per-tier ranking state.
        models: Known models with effective capability tags.
        known_capabilities: Capability tags the UI may assign.
    """

    tiers: list[TierChainModel] = []
    models: list[TierModelInfo] = []
    known_capabilities: list[str] = []


class TierSettingsUpdateRequest(BaseModel):
    """Request body for ``PUT /api/settings/tiers``.

    Attributes:
        tier_overrides: Tier -> ordered model ids. An empty list clears the
            override for that tier.
        model_capabilities: Model id -> capability tags. An empty list clears
            the override for that model.
    """

    tier_overrides: dict[int, list[str]] = Field(default_factory=dict)
    model_capabilities: dict[str, list[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Eval comparison
# ---------------------------------------------------------------------------


class EvalComparisonRequest(BaseModel):
    """Request body for ``POST /api/eval/compare``.

    Re-scores two previously-completed runs (by replaying their captured
    logs) under one rubric so prompt/workflow variants of the same task can
    be compared head-to-head. Nothing is persisted.

    Attributes:
        run_a: Filename or run id of candidate A.
        run_b: Filename or run id of candidate B.
        rubric_id: Rubric override applied to both candidates, or None.
        enforce_hard_gates: If True, hard-gate failures force grade ``F``.
        judge_model: Judge model identifier override, or None.
    """

    run_a: str
    run_b: str
    rubric_id: str | None = None
    enforce_hard_gates: bool = True
    judge_model: str | None = None


class EvalCandidateSummary(BaseModel):
    """Scored summary of one comparison candidate.

    Attributes:
        filename: Run log filename.
        run_id: Run identifier, or None.
        workflow_name: Workflow that produced the run, or None.
        weighted_score: Hybrid weighted composite score (0--100).
        overall_score: Unweighted mean criterion score (0--100).
        grade: Letter grade (A--F).
        passed: Whether the run met the pass threshold.
        criteria: Per-criterion detailed scores.
    """

    filename: str
    run_id: str | None = None
    workflow_name: str | None = None
    weighted_score: float = 0.0
    overall_score: float = 0.0
    grade: str = "F"
    passed: bool = False
    criteria: list[EvaluationCriterionDetail] = []


class CriterionDelta(BaseModel):
    """Per-criterion score difference between the two candidates.

    Attributes:
        criterion: Criterion name.
        score_a: Candidate A normalized score, or None when absent.
        score_b: Candidate B normalized score, or None when absent.
        delta: ``score_a - score_b`` when both present, else None.
    """

    criterion: str
    score_a: float | None = None
    score_b: float | None = None
    delta: float | None = None


class EvalComparisonResponse(BaseModel):
    """Response for ``POST /api/eval/compare``.

    Attributes:
        candidate_a: Scored summary of candidate A.
        candidate_b: Scored summary of candidate B.
        criteria_deltas: Per-criterion differences (A minus B).
        weighted_score_delta: ``candidate_a.weighted_score -
            candidate_b.weighted_score``.
        winner: ``"a"``, ``"b"``, or ``"tie"`` by weighted score.
        rubric_id: Rubric used for both candidates.
    """

    candidate_a: EvalCandidateSummary
    candidate_b: EvalCandidateSummary
    criteria_deltas: list[CriterionDelta] = []
    weighted_score_delta: float = 0.0
    winner: str = "tie"
    rubric_id: str = ""


def build_criteria_deltas(
    criteria_a: list[dict[str, Any]] | list[EvaluationCriterionDetail],
    criteria_b: list[dict[str, Any]] | list[EvaluationCriterionDetail],
) -> list[CriterionDelta]:
    """Pair up two criterion lists by name and compute per-criterion deltas.

    Criteria present on only one side yield a delta of ``None`` so the UI can
    render the asymmetry instead of silently dropping it.
    """

    def _as_map(
        criteria: list[dict[str, Any]] | list[EvaluationCriterionDetail],
    ) -> dict[str, float]:
        result: dict[str, float] = {}
        for item in criteria:
            detail = (
                item
                if isinstance(item, EvaluationCriterionDetail)
                else EvaluationCriterionDetail.model_validate(item)
            )
            result[detail.criterion] = detail.normalized_score
        return result

    map_a = _as_map(criteria_a)
    map_b = _as_map(criteria_b)
    deltas: list[CriterionDelta] = []
    for name in list(map_a) + [n for n in map_b if n not in map_a]:
        score_a = map_a.get(name)
        score_b = map_b.get(name)
        deltas.append(
            CriterionDelta(
                criterion=name,
                score_a=score_a,
                score_b=score_b,
                delta=(
                    score_a - score_b
                    if score_a is not None and score_b is not None
                    else None
                ),
            )
        )
    return deltas
