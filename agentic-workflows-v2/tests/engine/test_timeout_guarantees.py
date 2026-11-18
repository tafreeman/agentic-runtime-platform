"""Timeout guarantees G1-G3, as counterexamples found by the Lean model.

Each test reproduces a counterexample stated in ``proofs/Scheduler/TimeoutConfig.lean``
or ``proofs/Scheduler/Timeout.lean`` (branch ``timeout_proofs``) against the real
engine. The theorem named in a docstring is the Lean statement of the defect; the
``fixed_`` theorem beside it is what the engine must satisfy for the test to pass.

No test here needs a provider, Lean, or a wall-clock wait longer than a few
hundred milliseconds.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import pytest

from agentic_v2.contracts import StepStatus
from agentic_v2.engine import dag_executor as dag_executor_module
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.dag import DAG
from agentic_v2.engine.dag_executor import DAGExecutor
from agentic_v2.engine.executor import ExecutionConfig, WorkflowExecutor
from agentic_v2.engine.step import RetryStrategy, StepDefinition, StepExecutor

STEP_TIMEOUT_S = 0.05
HANG_S = 30.0
# How long a test waits for the engine before calling it hung.
VERDICT_S = 3.0
NOT_A_DEADLINE = [0, -1.0, math.nan, math.inf]


def _dag(*steps: StepDefinition) -> DAG:
    dag = DAG(name="timeout-guarantees")
    for step in steps:
        dag.add(step)
    return dag


async def _quick(ctx: ExecutionContext) -> dict[str, Any]:
    return {"ok": True}


async def _swallows_cancel_and_returns(ctx: ExecutionContext) -> dict[str, Any]:
    """Outlive the deadline, suppress the cancellation, then return normally."""
    try:
        await asyncio.sleep(HANG_S)
    except asyncio.CancelledError:
        pass
    return {"late": True}


# --- G1: configuration -------------------------------------------------------


@pytest.mark.parametrize("seconds", [math.nan, math.inf])
def test_step_timeout_must_be_finite_and_positive(seconds: float) -> None:
    """Lean: ``asis_accepts_nan_step_timeout`` / ``fixed_accepted_config``.

    ``nan <= 0`` is false, so the ``<= 0`` test lets NaN through; the step then
    times out at once. An infinite timeout is no deadline at all.
    """
    with pytest.raises(ValueError, match="timeout"):
        StepDefinition(name="a", func=_quick, timeout_seconds=seconds)
    with pytest.raises(ValueError, match="timeout"):
        StepDefinition(name="a", func=_quick).with_timeout(seconds)
    with pytest.raises(ValueError, match="timeout"):
        ExecutionConfig(step_default_timeout_seconds=seconds)


@pytest.mark.parametrize("seconds", NOT_A_DEADLINE)
async def test_dag_executor_rejects_a_bad_workflow_timeout_before_any_step(
    seconds: float,
) -> None:
    """Lean: ``asis_accepts_any_workflow_timeout``,
    ``asis_zero_timeout_schedules_a_step`` / ``rejected_config_has_no_run``.

    ``DAGExecutor.execute`` passes ``timeout`` straight to ``asyncio.timeout``.
    The run is launched, a step is scheduled, and only then does it fail.
    """
    events: list[str] = []

    async def observe(event: dict[str, Any]) -> None:
        events.append(event["type"])

    with pytest.raises(ValueError, match="timeout"):
        await DAGExecutor().execute(
            _dag(StepDefinition(name="a", func=_quick)),
            ExecutionContext(),
            on_update=observe,
            timeout=seconds,
        )
    assert events == []


@pytest.mark.parametrize("seconds", NOT_A_DEADLINE)
def test_execution_config_rejects_a_bad_global_timeout(seconds: float) -> None:
    """Lean: ``asis_zero_global_timeout_is_unlimited`` / ``fixed_global_timeout``."""
    with pytest.raises(ValueError, match="global_timeout_seconds"):
        ExecutionConfig(global_timeout_seconds=seconds)


async def test_global_timeout_is_armed_whenever_it_is_set() -> None:
    """The guard was ``if global_timeout_seconds:``; a set value must arm it."""

    async def slow(ctx: ExecutionContext) -> dict[str, Any]:
        await asyncio.sleep(HANG_S)
        return {}

    executor = WorkflowExecutor(
        config=ExecutionConfig(global_timeout_seconds=STEP_TIMEOUT_S)
    )
    result = await executor.execute(StepDefinition(name="a", func=slow))
    assert result.overall_status is StepStatus.FAILED


# --- G2: termination ---------------------------------------------------------


async def test_workflow_timeout_returns_when_a_step_ignores_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lean: ``asis_resistant_step_defeats_timeout`` /
    ``fixed_resistant_step_run_ends``, ``fixed_run_can_continue``.

    The step hangs and suppresses every cancellation. ``_cancel_in_flight``
    awaited it without a bound, so ``execute(timeout=...)`` never returned.
    """
    monkeypatch.setattr(dag_executor_module, "_CANCEL_GRACE_SECONDS", 0.05, False)
    release = asyncio.Event()

    async def hangs_and_ignores_cancel(ctx: ExecutionContext) -> dict[str, Any]:
        while not release.is_set():
            try:
                await asyncio.wait_for(release.wait(), timeout=HANG_S)
            except asyncio.CancelledError:
                continue
        return {}

    run = asyncio.ensure_future(
        DAGExecutor().execute(
            _dag(StepDefinition(name="a", func=hangs_and_ignores_cancel)),
            ExecutionContext(),
            timeout=STEP_TIMEOUT_S,
        )
    )
    try:
        done, _ = await asyncio.wait({run}, timeout=VERDICT_S)
        assert done, "execute(timeout=...) did not return: cleanup is unbounded"
        result = run.result()
        assert result.overall_status is StepStatus.FAILED
        assert result.metadata.get("timeout_exceeded") is True
        assert [(s.step_name, s.status, s.error_type) for s in result.steps] == [
            ("a", StepStatus.FAILED, "TimeoutError")
        ]
        assert result.metadata.get("abandoned_steps") == ["a"]
    finally:
        # Let the stubborn step end so it cannot outlive the test.
        release.set()
        run.cancel()
        await asyncio.sleep(0.05)


# --- G3: timeout honesty -----------------------------------------------------


async def test_step_whose_deadline_expired_is_not_success() -> None:
    """Lean: ``asis_expired_attempt_can_succeed`` / ``fixed_expired_attempt_fails``."""
    ctx = ExecutionContext()
    step = StepDefinition(
        name="a", func=_swallows_cancel_and_returns, timeout_seconds=STEP_TIMEOUT_S
    )
    result = await StepExecutor().execute(step, ctx)
    assert result.status is StepStatus.FAILED
    assert result.error_type == "TimeoutError"
    assert ctx.is_step_failed("a")
    assert not ctx.is_step_complete("a")


async def test_step_whose_deadline_expired_does_not_unlock_its_dependent() -> None:
    """Lean: ``asis_expired_step_unlocks_dependent`` /
    ``fixed_expired_outcome_blocks`` with ``blocked_dependents_never_start``."""
    ran: list[str] = []

    async def downstream(ctx: ExecutionContext) -> dict[str, Any]:
        ran.append("b")
        return {}

    dag = _dag(
        StepDefinition(
            name="a", func=_swallows_cancel_and_returns, timeout_seconds=STEP_TIMEOUT_S
        ),
        StepDefinition(name="b", func=downstream, depends_on=["a"]),
    )
    result = await DAGExecutor().execute(dag, ExecutionContext())
    assert ran == []
    assert result.overall_status is StepStatus.FAILED
    assert {s.step_name: s.status for s in result.steps} == {
        "a": StepStatus.FAILED,
        "b": StepStatus.SKIPPED,
    }


async def test_step_whose_deadline_expired_is_not_retried() -> None:
    """Lean: ``asis_expired_attempt_can_retry`` / ``fixed_expired_attempt_fails``."""
    calls = 0

    async def raises_when_cancelled(ctx: ExecutionContext) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls > 1:
            return {"second_attempt": True}
        try:
            await asyncio.sleep(HANG_S)
        except asyncio.CancelledError:
            raise RuntimeError("cleanup failed") from None
        return {}

    step = StepDefinition(
        name="a", func=raises_when_cancelled, timeout_seconds=STEP_TIMEOUT_S
    ).with_retry(max_retries=2, strategy=RetryStrategy.NONE)
    result = await StepExecutor().execute(step, ExecutionContext())
    assert calls == 1
    assert result.status is StepStatus.FAILED
    assert result.error_type == "TimeoutError"


async def test_context_agrees_with_result_after_workflow_timeout() -> None:
    """Lean: ``timed_out_steps_never_succeed`` holds for the recorded result;
    the execution context is outside that model and disagreed with it.

    The step swallows the cancel and returns, so ``StepExecutor`` marks it
    complete in the context while ``_handle_timeout`` records it FAILED.
    """
    ctx = ExecutionContext()
    dag = _dag(StepDefinition(name="a", func=_swallows_cancel_and_returns))
    result = await DAGExecutor().execute(dag, ctx, timeout=STEP_TIMEOUT_S)
    assert [(s.step_name, s.status, s.error_type) for s in result.steps] == [
        ("a", StepStatus.FAILED, "TimeoutError")
    ]
    assert ctx.is_step_failed("a")
    assert not ctx.is_step_complete("a")
