"""Tests for WorkflowExecutor asyncio.CancelledError handling.

Covers the except asyncio.CancelledError block in WorkflowExecutor.execute()
(~lines 270-292 of engine/executor.py) which emits ExecutorEvent.CANCELLED
and a terminal ExecutorEvent.WORKFLOW_END before re-raising, so that
subscribers receive a terminal event on external cancellation.

NOTE: step.py intentionally catches asyncio.CancelledError *inside* step
execution and converts it to a graceful FAILED StepResult. Cancelling the
executor task while it sits inside a slow step is therefore absorbed before
it reaches execute()'s handler. To exercise the executor's own handler
deterministically, these tests make the CancelledError originate in the
executor's orchestration layer by monkeypatching ``_execute_workflow`` to
raise CancelledError directly — exactly where execute()'s try block awaits
it (with no global timeout, so no asyncio.wait_for wrapping intervenes).
"""

from __future__ import annotations

import asyncio

import pytest

from agentic_v2.engine import (
    ExecutionConfig,
    StepDefinition,
    WorkflowExecutor,
    reset_executor,
)
from agentic_v2.engine.executor import ExecutorEvent


async def _noop_step(ctx):
    return {}


def _make_executor_with_listener() -> tuple[WorkflowExecutor, list[ExecutorEvent]]:
    """Build an executor (no global timeout) with a capturing listener.

    No global timeout means execute() takes the ``else: await
    self._execute_workflow(...)`` branch — no asyncio.wait_for wrapping — so a
    CancelledError raised by _execute_workflow surfaces directly in execute()'s
    try block and reaches the ``except asyncio.CancelledError`` handler.
    """
    executor = WorkflowExecutor(
        config=ExecutionConfig(
            global_timeout_seconds=None,
            cleanup_on_complete=False,
        )
    )

    emitted_events: list[ExecutorEvent] = []

    def listener(event: ExecutorEvent, data: dict) -> None:
        emitted_events.append(event)

    executor.add_listener(listener)
    return executor, emitted_events


class TestWorkflowExecutorCancellation:
    """Verify the executor's own CancelledError handler emits terminal events."""

    def setup_method(self):
        reset_executor()

    async def test_cancellation_emits_cancelled_and_workflow_end_events(self):
        """A CancelledError in executor orchestration emits both ExecutorEvent.CANCELLED
        and ExecutorEvent.WORKFLOW_END before the error propagates.

        This ensures WebSocket / stream subscribers receive a terminal
        event instead of hanging when the run task is cancelled
        externally.
        """
        # Arrange
        executor, emitted_events = _make_executor_with_listener()

        async def _raise_cancel(*args, **kwargs):
            raise asyncio.CancelledError()

        executor._execute_workflow = _raise_cancel
        step_def = StepDefinition(name="noop", func=_noop_step)

        # Act / Assert: the CancelledError must still propagate out of execute()
        with pytest.raises(asyncio.CancelledError):
            await executor.execute(step_def)

        # Assert: both terminal events were emitted before the error propagated
        assert (
            ExecutorEvent.CANCELLED in emitted_events
        ), f"ExecutorEvent.CANCELLED was not emitted; got: {emitted_events}"
        assert (
            ExecutorEvent.WORKFLOW_END in emitted_events
        ), f"ExecutorEvent.WORKFLOW_END was not emitted; got: {emitted_events}"

    async def test_cancelled_event_precedes_workflow_end_event(self):
        """ExecutorEvent.CANCELLED must be emitted before ExecutorEvent.WORKFLOW_END."""
        # Arrange
        executor, emitted_events = _make_executor_with_listener()

        async def _raise_cancel(*args, **kwargs):
            raise asyncio.CancelledError()

        executor._execute_workflow = _raise_cancel
        step_def = StepDefinition(name="noop", func=_noop_step)

        # Act
        with pytest.raises(asyncio.CancelledError):
            await executor.execute(step_def)

        # Assert ordering
        cancelled_idx = next(
            (i for i, e in enumerate(emitted_events) if e == ExecutorEvent.CANCELLED),
            None,
        )
        end_idx = next(
            (
                i
                for i, e in enumerate(emitted_events)
                if e == ExecutorEvent.WORKFLOW_END
            ),
            None,
        )

        assert cancelled_idx is not None, "CANCELLED event never emitted"
        assert end_idx is not None, "WORKFLOW_END event never emitted"
        assert (
            cancelled_idx < end_idx
        ), f"CANCELLED (idx={cancelled_idx}) must precede WORKFLOW_END (idx={end_idx})"

    async def test_full_event_sequence_on_cancellation(self):
        """WORKFLOW_START is emitted before cancellation; verify the full sequence
        includes START, CANCELLED, and END."""
        # Arrange
        executor, emitted_events = _make_executor_with_listener()

        async def _raise_cancel(*args, **kwargs):
            raise asyncio.CancelledError()

        executor._execute_workflow = _raise_cancel
        step_def = StepDefinition(name="noop", func=_noop_step)

        # Act
        with pytest.raises(asyncio.CancelledError):
            await executor.execute(step_def)

        # Assert
        assert ExecutorEvent.WORKFLOW_START in emitted_events
        assert ExecutorEvent.CANCELLED in emitted_events
        assert ExecutorEvent.WORKFLOW_END in emitted_events
