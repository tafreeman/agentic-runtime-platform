"""ARP adapter for the published optional EvalKit dependency (ADR-042).

Slice C uses this bridge from live step scoring. ARP owns its rubric resources;
EVK supplies public Rubric models and the bridge preserves legacy weighted
arithmetic. Runtime callers require complete criterion evidence before scoring.
The dependency remains one-way: EVK never imports ARP.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from .criterion_aggregation import CriterionSpec, score_criterion_values

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
            message names the supported install so a caller knows exactly what
            to do; runtime callers report unavailable scoring when EVK is absent.
    """
    if not EVALKIT_AVAILABLE:
        raise RuntimeError(
            "agentic-evalkit is not installed. It is an optional dependency "
            "(see ADR-042). Enable it with the extra: "
            "pip install 'agentic-workflows-v2[eval]' — or install the "
            "published package directly: pip install 'agentic-evalkit>=0.3.0,<0.4.0'"
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
    """Score an EvalKit rubric using ARP's fixed-denominator rule.

    Missing criteria keep their weight in the denominator. EvalKit's composite
    grader instead excludes unavailable criteria; the policies are distinct.
    The optional EvalKit dependency and its rubric validation remain required.
    """
    _require_evalkit()

    rubric = rubric_from_yaml_dict(rubric_data)

    criteria = tuple(
        CriterionSpec(
            name=criterion.criterion_id,
            weight=criterion.weight,
            min_value=criterion.scale_min if criterion.scale_min is not None else 0.0,
            max_value=criterion.scale_max if criterion.scale_max is not None else 1.0,
        )
        for criterion in rubric.criteria
    )
    return score_criterion_values(criteria, criterion_scores).weighted_score


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
