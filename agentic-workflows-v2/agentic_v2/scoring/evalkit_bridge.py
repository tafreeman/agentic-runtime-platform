"""ARP-side adapter bridge to the external ``agentic-evalkit`` library (ADR-042).

This module is the ARP half of the evalkit integration described in
``docs/adr/ADR-042-agentic-evalkit-adoption.md``. ``agentic-evalkit`` is a
standalone evaluation framework developed independently of this repository
(see ../agentic-evalkit in the wider workspace) and
does not yet have a public git remote, so it is treated as an **optional**
dependency here: CI for ``agentic-workflows-v2`` must stay green whether or
not it is installed. Every public symbol in this module degrades gracefully
(raises a clear ``RuntimeError``, not an ``ImportError`` at call time) when
evalkit is absent.

``agentic_evalkit`` enforces, via its own AST-based boundary contract test,
that it never imports anything from ``agentic_v2``, ``tools``, or
``executionkit``. That invariant means all of the ARP <-> evalkit adaptation
logic necessarily lives on the ARP side of the boundary — here — rather than
in evalkit itself. This module only *adapts*: it does not change evalkit's
public API and it does not wire into any ARP call site yet (that is Slice C;
see the ADR's slice plan). ``agentic_v2/scoring/step_scoring.py`` is
untouched by this module.

Mirrors the guarded-import convention already used by
``agentic_v2/scoring/step_scoring.py`` (``_EVAL_AVAILABLE``), except the flag
here is public (``EVALKIT_AVAILABLE``) since this module's whole purpose is
to be evalkit-facing and callers need to branch on it explicitly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentic_evalkit.graders import Rubric
    from agentic_evalkit.targets import CallableTarget

EVALKIT_AVAILABLE = False
try:
    from agentic_evalkit.graders import Rubric as _Rubric
    from agentic_evalkit.graders import RubricCriterion as _RubricCriterion
    from agentic_evalkit.targets import CallableTarget as _CallableTarget

    EVALKIT_AVAILABLE = True
except ImportError:
    pass


def _require_evalkit() -> None:
    """Raise a clear error when evalkit is not installed.

    Raises:
        RuntimeError: Always, when ``EVALKIT_AVAILABLE`` is ``False``. The
            message names the install path so a caller in a dev environment
            knows exactly what to do; callers in CI simply never reach here
            because this module's functions are never invoked from
            ``step_scoring.py`` yet (Slice B is additive-only).
    """
    if not EVALKIT_AVAILABLE:
        raise RuntimeError(
            "agentic-evalkit is not installed. It is an optional dependency "
            "until it has a public git remote (see ADR-042). Install it for "
            "local development with: pip install -e '../agentic-evalkit'"
        )


def rubric_from_yaml_dict(rubric_data: dict[str, Any]) -> "Rubric":
    """Convert an ARP rubric-YAML dict into an evalkit :class:`Rubric`.

    ARP's rubric YAML (loaded via ``agentic_v2_eval.rubrics.load_rubric``,
    see e.g. ``agentic-v2-eval/src/agentic_v2_eval/rubrics/code.yaml``) has
    the shape::

        criteria:
          - name: Correctness
            weight: 0.30
            description: "..."
            levels: {5: "...", ..., 0: "..."}   # optional, documentation only
        thresholds:
          pass: 0.75
          excellent: 0.90
          warning: 0.60
        metadata:
          version: "1.0.0"
          ...

    evalkit's :class:`~agentic_evalkit.graders.Rubric` has no equivalent of
    ``levels``, ``thresholds``, or ``metadata`` — those are dropped here.
    ``thresholds.pass`` is a *rubric-level* pass/fail cutoff applied by ARP's
    ``Scorer``-consuming callers (e.g. ``step_scoring._pass_threshold``), not
    a per-criterion concept, so it has no home on evalkit's per-criterion
    :class:`~agentic_evalkit.graders.RubricCriterion`. Callers that need the
    pass threshold should keep reading it from ``rubric_data`` directly, the
    same way ``step_scoring.py`` does today.

    Each ARP criterion maps onto one evalkit ``RubricCriterion``:

    * ``name`` -> ``criterion_id`` (evalkit requires this to be unique within
      the rubric; ARP criterion names are already unique per rubric file, so
      the identity mapping is safe and preserves the criterion identity used
      by :func:`score_criteria` and the legacy ``Scorer``).
    * ``description`` -> ``description`` (defaults to ``""`` when absent).
    * ``weight`` -> ``weight`` (defaults to ``1.0``, matching ``Scorer``).
    * ``scale`` is always ``"bounded"`` with ``scale_min=0.0``/``scale_max=1.0``
      — ARP criterion scores are always normalized floats in ``[0, 1]``
      (``Scorer`` clamps and normalizes against ``min_value``/``max_value``,
      which ARP's rubric YAML never actually overrides away from the 0..1
      default). ``"binary"`` would misrepresent ARP's continuous criteria.
    * ``requires_evidence`` is left at evalkit's default (``True``). ARP's
      rubric YAML has no equivalent flag; defaulting to evidence-required is
      the conservative choice and also satisfies evalkit's own validator,
      which rejects ``requires_evidence=False`` on criteria whose description
      reads as a broad holistic judgment (several ARP criteria, e.g. "Code
      Quality", "Overall correctness"-style text, would trip that check).
    * ``hard_gate`` is always ``False``. ARP's rubric YAML criteria have no
      hard-gate concept — the ``pattern.yaml`` rubric's separate top-level
      ``hard_gates: [{criterion, minimum}, ...]`` list is a distinct,
      unrelated mechanism that ``Scorer`` does not consume at all, so there
      is nothing to map it from/to here.

    ``rubric_id`` is taken from ``rubric_data["name"]`` (a rubric's YAML
    comment header, e.g. ``"Code Generation Rubric"``) when present, else
    from ``rubric_data["metadata"]["description"]``, else a fixed fallback —
    ARP rubric YAML does not always carry an explicit machine ``name`` key
    (``default.yaml``, ``code.yaml`` have none; only free-text comments).

    Args:
        rubric_data: A rubric dict as returned by
            ``agentic_v2_eval.rubrics.load_rubric`` (or an equivalent
            in-memory dict of the same shape).

    Returns:
        An evalkit ``Rubric`` with one ``RubricCriterion`` per ARP criterion.

    Raises:
        RuntimeError: ``agentic-evalkit`` is not installed.
        ValueError: ``rubric_data`` has no usable ``criteria`` list, or a
            criterion entry is missing the required ``name`` key.
    """
    _require_evalkit()

    raw_criteria = rubric_data.get("criteria", [])
    if not isinstance(raw_criteria, list) or not raw_criteria:
        raise ValueError("rubric_data must contain a non-empty 'criteria' list")

    criteria: list[_RubricCriterion] = []
    for item in raw_criteria:
        if not isinstance(item, dict) or "name" not in item:
            raise ValueError(f"rubric criterion missing required 'name' key: {item!r}")
        criteria.append(
            _RubricCriterion(
                criterion_id=str(item["name"]),
                description=str(item.get("description", "")),
                scale="bounded",
                scale_min=0.0,
                scale_max=1.0,
                requires_evidence=True,
                weight=float(item.get("weight", 1.0)),
                hard_gate=False,
            )
        )

    metadata = rubric_data.get("metadata", {})
    rubric_id = (
        rubric_data.get("name")
        or (metadata.get("description") if isinstance(metadata, dict) else None)
        or "arp-rubric"
    )

    return _Rubric(rubric_id=str(rubric_id), criteria=tuple(criteria))


def score_criteria(
    rubric_data: dict[str, Any], criterion_scores: Mapping[str, float]
) -> float:
    """Compute the same weighted score as ARP's legacy ``Scorer`` via evalkit types.

    Reproduces ``agentic_v2_eval.scorer.Scorer(rubric_data).score(criterion_scores)
    .weighted_score`` using evalkit's :class:`~agentic_evalkit.graders.Rubric`
    as the intermediate representation, so callers migrating off
    ``agentic_v2_eval`` get identical numbers.

    Parity is **exact by construction, computed directly from the converted
    Rubric's criteria** rather than by driving evalkit's
    ``CompositeGrader``/``WeightedGrader`` aggregation. Those primitives grade
    a ``NormalizedExecutionResult`` end-to-end (they call ``.grade()`` on
    component graders and combine typed ``GradeResult``s); bridging a bare
    ``{criterion_id: score}`` dict through that path would require
    fabricating a grader per criterion and a fake execution/sample, and their
    weighted-mean semantics differ from ``Scorer`` in a way that matters here:
    ``CompositeGrader`` *excludes* a non-definitive (missing/abstain/error)
    component's weight from **both** the numerator and the denominator, so a
    missing component simply shrinks the averaging pool. ``Scorer`` instead
    fixes the denominator (``total_weight``) as the sum of *every* criterion's
    weight in the rubric **up front**, before it even looks at which criteria
    are present in the ``results`` dict — a missing criterion is excluded only
    from the numerator, not the denominator. That means a missing criterion
    behaves like a scored ``0`` in ``Scorer``'s aggregate, not like an
    abstention — the two aggregations are not interchangeable, and driving
    ``CompositeGrader`` here would silently change the score for any input
    with a missing criterion. Computing the weighted mean directly from
    ``Rubric.criteria`` (the fixed, full criteria list) reproduces ``Scorer``'s
    exact arithmetic instead:

    * The denominator (``total_weight``) is the sum of **every** criterion's
      weight in the rubric, computed before checking ``criterion_scores`` —
      identical to ``Scorer``'s ``total_weight = sum(c.weight for c in
      self.criteria)`` computed ahead of its missing-criterion loop.
    * A criterion whose ``criterion_id`` is absent from ``criterion_scores``
      contributes ``0`` to the numerator but its weight still counts in the
      (already-fixed) denominator — identical to ``Scorer``'s
      ``missing_criteria`` handling, which has the same net effect despite
      being expressed as a ``continue`` in the loop.
    * A present criterion's score is clamped to ``[scale_min, scale_max]``
      (``[0, 1]`` for every rubric produced by :func:`rubric_from_yaml_dict`)
      then normalized by the same ``(value - min) / (max - min)`` formula
      ``Scorer`` uses, before being weighted into the numerator.
    * If the rubric has no criteria at all, or every criterion's weight is
      ``0`` (so the denominator is ``0.0``), the result is ``0.0`` — identical
      to ``Scorer``'s empty-criteria and zero-total-weight branches, both of
      which return ``weighted_score=0.0`` rather than raising or dividing by
      zero.

    Args:
        rubric_data: A rubric dict in the same shape :func:`rubric_from_yaml_dict`
            accepts.
        criterion_scores: Mapping of criterion name to raw score. Names that
            do not match a criterion in ``rubric_data`` are ignored (this
            mirrors ``Scorer``, which only ever reads known criterion names
            out of the ``results`` dict passed to it).

    Returns:
        The weighted score in ``[0.0, 1.0]``, identical to
        ``Scorer(rubric_data).score(criterion_scores).weighted_score``.

    Raises:
        RuntimeError: ``agentic-evalkit`` is not installed.
        ValueError: ``rubric_data`` is malformed (see :func:`rubric_from_yaml_dict`).
    """
    _require_evalkit()

    rubric = rubric_from_yaml_dict(rubric_data)

    # Denominator fixed over ALL criteria up front — matches Scorer's
    # `total_weight = sum(c.weight for c in self.criteria)`, computed before
    # any missing-criterion check. A missing criterion is excluded from the
    # numerator only, so it behaves like a scored 0 in the final average.
    total_weight = sum(criterion.weight for criterion in rubric.criteria)
    if total_weight <= 0.0:
        return 0.0

    weighted_sum = 0.0
    for criterion in rubric.criteria:
        if criterion.criterion_id not in criterion_scores:
            continue
        scale_min = criterion.scale_min if criterion.scale_min is not None else 0.0
        scale_max = criterion.scale_max if criterion.scale_max is not None else 1.0
        value = float(criterion_scores[criterion.criterion_id])
        value = max(scale_min, min(scale_max, value))
        range_size = scale_max - scale_min
        normalized = (value - scale_min) / range_size if range_size > 0 else value
        weighted_sum += criterion.weight * normalized

    return weighted_sum / total_weight


def workflow_callable_target(
    run_workflow: Callable[..., Awaitable[object]],
    *,
    name: str = "arp-workflow",
) -> "CallableTarget":
    """Wrap an ARP workflow-run coroutine as an evalkit :class:`CallableTarget`.

    Lets evalkit's ``EvalRunner`` drive an ARP workflow run as the system
    under test: evalkit calls ``target.execute(sample, attempt=..., timeout_seconds=...)``,
    which invokes ``run_workflow(sample.input)`` and normalizes the result.

    evalkit's ``CallableTarget`` (``agentic_evalkit.targets.callable``)
    accepts either a sync or async callable of signature
    ``(dict[str, JsonValue]) -> Mapping[str, JsonValue] | Awaitable[Mapping[str, JsonValue]]``
    — it inspects the callable with ``inspect.iscoroutinefunction`` and awaits
    it directly if async, or runs it in a thread via ``asyncio.to_thread`` if
    sync. ``run_workflow`` here is always async
    (``Callable[..., Awaitable[object]]``, matching ARP's workflow-executor
    coroutines), so it is passed straight through — ``CallableTarget`` detects
    the coroutine function and awaits it without any wrapping needed on our
    side. The only adaptation this factory performs is at the type boundary:
    ARP's workflow-run coroutines are typed to return ``object`` (the engine's
    result contracts vary by workflow), while ``CallableTarget`` requires a
    ``Mapping`` return; :func:`workflow_callable_target` raises a clear
    ``TypeError`` at call time if a workflow ever returns something else,
    rather than let evalkit's own generic "must return a mapping" error (which
    does not know it is looking at an ARP workflow) be the only signal.

    Args:
        run_workflow: An async ARP workflow-run entry point taking the raw
            ``EvalSample.input`` dict as its sole positional argument and
            returning a mapping-shaped result (e.g. a ``WorkflowResult``
            dumped to a dict, or any ``dict[str, JsonValue]``-compatible
            mapping). Non-mapping returns raise ``TypeError`` when the target
            is executed, in keeping with evalkit's own contract.
        name: Target name recorded in the returned execution's
            ``target_fingerprint`` (``callable:{name}:{hash}``). Defaults to
            ``"arp-workflow"``; callers driving multiple distinct workflows
            through the same eval run should pass a distinguishing name.

    Returns:
        An evalkit ``CallableTarget`` ready to hand to ``EvalRunner``.

    Raises:
        RuntimeError: ``agentic-evalkit`` is not installed.
    """
    _require_evalkit()

    async def _adapted(sample_input: dict[str, Any]) -> Mapping[str, Any]:
        result = await run_workflow(sample_input)
        if not isinstance(result, Mapping):
            raise TypeError(
                f"workflow {name!r} must return a mapping-shaped result for "
                f"evalkit CallableTarget, got {type(result).__name__}"
            )
        return result

    return _CallableTarget(_adapted, name=name)


__all__ = [
    "EVALKIT_AVAILABLE",
    "rubric_from_yaml_dict",
    "score_criteria",
    "workflow_callable_target",
]
