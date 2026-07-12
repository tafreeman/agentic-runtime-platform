"""Convergence tests for ``loop_until`` refinement (review item #7).

These tests pin the behaviour the engine *must* have for an iterative
review/rework loop to actually converge:

1. **Inputs are re-resolved on every loop iteration.** A refinement loop
   feeds its own prior output back into its next input via ``coalesce()``
   (see ``workflows/definitions/iterative_review.yaml``). If the engine
   resolves inputs only once — before the loop — that feedback is stale and
   the loop can never observe its own progress, so it never converges.

2. **Loop iterations are bounded by ``loop_max``, not the retry budget.**
   ``loop_until`` re-runs are a distinct concern from error retries; a loop
   that needs more rounds than ``RetryConfig.max_retries`` must still reach
   ``loop_max`` rounds.

Both run offline with a plain in-process step function — no LLM, no EK.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentic_v2.contracts import StepStatus
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.step import StepDefinition, StepExecutor
from agentic_v2.models import ModelTier

pytestmark = pytest.mark.asyncio

# loop_until expression mirroring iterative_review.yaml's quality gate, using
# the proven ``==`` operator form.
_APPROVED_WHEN = "${steps.refine_loop.outputs.review_status} == 'APPROVED'"

# Refinement marker appended on each rework pass. The reviewer "approves" once
# enough passes have flowed back into its input.
_MARK = "# refined"


def _seed_implement_view(ctx: ExecutionContext, code: str) -> None:
    """Seed an upstream ``implement`` step output, as the DAG would."""
    ctx.set_sync("steps", {"implement": {"outputs": {"code": code}}})


def _make_reviewer(*, approve_after_passes: int, seen: list[str]) -> Any:
    """Build a reviewer/reworker step func.

    It reads the ``code`` input (resolved fresh each iteration when the engine
    is correct), records what it saw, appends one refinement marker, and
    approves once the input already reflects ``approve_after_passes`` prior
    reworks — i.e. only once feedback has actually flowed back in.
    """

    async def _reviewer(ctx: ExecutionContext) -> dict[str, Any]:
        code_in = str(ctx.get_sync("code") or "")
        seen.append(code_in)
        passes = code_in.count(_MARK)
        status = "APPROVED" if passes >= approve_after_passes else "NEEDS_FIXES"
        return {
            "reworked_code": f"{code_in}\n{_MARK}",
            "review_status": status,
        }

    return _reviewer


def _refine_loop_step(func: Any, *, loop_max: int) -> StepDefinition:
    """A loop_until step whose input coalesces its own rework over the seed."""
    return StepDefinition(
        name="refine_loop",
        func=func,
        loop_until=_APPROVED_WHEN,
        loop_max=loop_max,
        input_mapping={
            "code": (
                "${coalesce("
                "steps.refine_loop.outputs.reworked_code, "
                "steps.implement.outputs.code"
                ")}"
            ),
        },
        tier=ModelTier.TIER_2,
    )


async def test_refinement_feedback_flows_into_next_iteration() -> None:
    """Each iteration must see the previous iteration's reworked output.

    Without per-iteration input re-resolution the reviewer sees the seed
    code forever (passes==0), never approves, and the loop exhausts its
    bound.
    """
    seen: list[str] = []
    ctx = ExecutionContext()
    _seed_implement_view(ctx, "base")

    step = _refine_loop_step(
        _make_reviewer(approve_after_passes=3, seen=seen),
        loop_max=6,
    )
    result = await StepExecutor().execute(step, ctx)

    # Converged via approval, not by hitting the bound.
    assert result.status is StepStatus.SUCCESS
    steps_view = ctx.get_sync("steps")
    assert steps_view["refine_loop"]["outputs"]["review_status"] == "APPROVED"

    # Feedback actually flowed: the reviewer saw a strictly growing input,
    # one refinement marker more each round (0, 1, 2, 3 ...).
    pass_counts = [c.count(_MARK) for c in seen]
    assert pass_counts == [0, 1, 2, 3], pass_counts


async def test_loop_until_bounded_by_loop_max_not_retry_budget() -> None:
    """A loop needing more rounds than the retry budget still reaches them.

    Default ``RetryConfig.max_retries`` is 3; this loop converges on round 4.
    If loop iterations consumed the retry budget the step would stop at 3
    rounds, still NEEDS_FIXES.
    """
    seen: list[str] = []
    ctx = ExecutionContext()
    _seed_implement_view(ctx, "base")

    step = _refine_loop_step(
        _make_reviewer(approve_after_passes=3, seen=seen),
        loop_max=6,
    )
    result = await StepExecutor().execute(step, ctx)

    assert result.status is StepStatus.SUCCESS
    assert len(seen) == 4  # rounds 1..4, converged on the 4th
    assert result.metadata.get("loop_iteration") == 4


async def test_loop_until_still_terminates_at_loop_max_without_convergence() -> None:
    """A loop that never approves stops at ``loop_max`` rounds (no infinite loop)."""
    seen: list[str] = []
    ctx = ExecutionContext()
    _seed_implement_view(ctx, "base")

    # Demands more passes than loop_max can supply → never approves.
    step = _refine_loop_step(
        _make_reviewer(approve_after_passes=99, seen=seen),
        loop_max=3,
    )
    result = await StepExecutor().execute(step, ctx)

    assert len(seen) == 3
    steps_view = ctx.get_sync("steps")
    assert steps_view["refine_loop"]["outputs"]["review_status"] == "NEEDS_FIXES"
