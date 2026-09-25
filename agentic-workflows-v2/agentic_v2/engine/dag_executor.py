"""DAG executor with dynamic parallel scheduling.

Executes workflow steps as soon as their upstream dependencies are satisfied,
achieving maximum parallelism without artificial layer barriers.

Key design decisions:
- **Kahn's algorithm** for in-degree tracking at runtime (not just ordering).
- **asyncio.wait(FIRST_COMPLETED)** to unblock downstream steps the instant
  an upstream finishes, rather than waiting for an entire "wave" to complete.
- **Cascade skip** via BFS: when a step fails, all transitive dependents are
  marked SKIPPED so the executor can still finish cleanly.
- **Deadlock detection**: if no tasks are running and steps remain, the
  remaining steps are skipped and the run fails. This cannot happen for a
  validated DAG with ``max_concurrency >= 1``; the check is a backstop.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from ..contracts import StepResult, StepStatus, WorkflowResult
from ..integrations.otel import get_tracer as _get_tracer
from .context import ExecutionContext, get_context
from .dag import DAG
from .step import StepExecutor
from .step_state import StepState, StepStateManager

logger = logging.getLogger(__name__)

# The only statuses a step may finish with. See _fail_nonterminal.
_TERMINAL_STATUSES = frozenset(
    {StepStatus.SUCCESS, StepStatus.FAILED, StepStatus.SKIPPED}
)

# OpenTelemetry status APIs — optional (bundled in the `tracing` extra).
# Guarded so the engine imports cleanly without OTel installed.
try:
    from opentelemetry.trace import Status, StatusCode

    _OTEL_STATUS_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only without the extra
    _OTEL_STATUS_AVAILABLE = False
    Status = None  # type: ignore[assignment,misc]
    StatusCode = None  # type: ignore[assignment,misc]


def _mark_span_error(span: Any, message: str) -> None:
    """Mark an OTEL span as ERROR and record an exception event.

    No-op when OTel is unavailable or no span is active, so failure
    paths stay safe in local/no-tracing runs.
    """
    if span is None or not _OTEL_STATUS_AVAILABLE:
        return
    try:
        span.set_status(Status(StatusCode.ERROR, message))
        span.record_exception(RuntimeError(message))
    except Exception as exc:  # pragma: no cover — defensive, span impls vary
        logger.debug("Failed to set OTEL error status on engine span: %s", exc)


@dataclass
class _RunState:
    """Mutable scheduling state shared across a single ``_run_dag`` call.

    A plain container that bundles the per-execution configuration and the
    mutable bookkeeping collections so the scheduling helpers can be defined
    at module level (each with a single responsibility) instead of as nested
    closures.  Every collection is held by reference, so helpers mutate the
    same objects the caller observes — behaviour is identical to the previous
    closure-based implementation.

    Attributes:
        step_executor: Delegate that runs a single step.
        dag: The DAG being executed.
        ctx: Shared execution context.
        on_update: Optional async lifecycle callback (UI/WebSocket updates).
        span: Optional active OTEL span for the run.
        timeout: Optional wall-clock timeout in seconds (``None`` disables it).
        max_concurrency: Upper bound on simultaneously running steps.
        state_manager: Per-execution step lifecycle state machine.
        result: The accumulating :class:`WorkflowResult`.
        adjacency: Map of step name -> list of dependent step names.
        in_degree: Remaining unmet-dependency count per step.
        ready: Queue of steps whose in-degree has reached zero.
        running: Names of steps with an in-flight task.
        completed: Names of steps that have reached a terminal state.
        skipped: Names of steps marked SKIPPED.
        results: Map of step name -> its :class:`StepResult`.
        tasks: Set of in-flight asyncio tasks.
    """

    step_executor: StepExecutor
    dag: DAG
    ctx: ExecutionContext
    on_update: Callable[[dict[str, Any]], Awaitable[None]] | None
    span: Any
    timeout: float | None
    max_concurrency: int
    state_manager: StepStateManager
    result: WorkflowResult
    adjacency: dict[str, list[str]]
    in_degree: dict[str, int]
    ready: deque[str]
    running: set[str] = field(default_factory=set)
    completed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    results: dict[str, StepResult] = field(default_factory=dict)
    tasks: set[asyncio.Task] = field(default_factory=set)


async def _notify(state: _RunState, event: dict[str, Any]) -> None:
    """Send *event* to the ``on_update`` observer, if there is one.

    The observer (UI, WebSocket, scoring, checkpoint wrapper) cannot change
    the run. An exception from it used to escape ``execute()`` mid-batch,
    leaving running steps orphaned, or fail a step whose work never ran.
    It is logged and counted in ``metadata["observer_errors"]`` instead;
    cancellation still propagates, including one the observer masked.
    """
    if state.on_update is None:
        return
    task = asyncio.current_task()
    # Compare against the count on entry: a caller that swallowed an earlier
    # CancelledError without uncancel() leaves cancelling() nonzero, and that
    # stale count must not turn an ordinary observer failure into a cancel.
    cancels_before = task.cancelling() if task is not None else 0
    try:
        await state.on_update(event)
    except Exception as exc:
        if task is not None and task.cancelling() > cancels_before:
            # A timeout or the caller's cancel landed while the observer was
            # awaiting, and its cleanup replaced the CancelledError with an
            # ordinary exception. Swallowing that would let asyncio.timeout()
            # uncancel the task and the run carry on past its deadline.
            raise asyncio.CancelledError from exc
        errors = state.result.metadata.get("observer_errors", 0)
        state.result.metadata["observer_errors"] = errors + 1
        logger.warning(
            "on_update observer failed on %s for workflow %r",
            event.get("type"),
            state.dag.name,
            exc_info=True,
        )


async def _run_step(state: _RunState, step_name: str) -> tuple[str, StepResult]:
    """Execute a single step and return its name + result tuple."""
    state.state_manager.transition(step_name, StepState.RUNNING)
    await _notify(
        state,
        {
            "type": "step_start",
            "run_id": state.result.workflow_id,
            "step": step_name,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    step_def = state.dag.steps[step_name]
    step_result = await state.step_executor.execute(step_def, state.ctx)
    return step_name, step_result


def _mark_skipped(state: _RunState, step_name: str, reason: str) -> None:
    """Record a step as SKIPPED with a human-readable reason."""
    if step_name in state.completed or step_name in state.skipped:
        return
    step_result = StepResult(step_name=step_name, status=StepStatus.SKIPPED)
    step_result.metadata["skip_reason"] = reason
    step_result.end_time = datetime.now(UTC)
    state.results[step_name] = step_result
    state.result.add_step(step_result)
    state.completed.add(step_name)
    state.skipped.add(step_name)
    state.state_manager.set_state(step_name, StepState.SKIPPED)
    # Mark as complete in ctx so downstream should_run() dependency
    # checks pass.  Skipped steps are logically "done" — they just
    # didn't produce output.
    if step_name not in state.ctx.completed_steps:
        state.ctx.completed_steps.append(step_name)


def _cascade_skip(state: _RunState, start_step: str, reason: str) -> None:
    """BFS from *start_step* to skip all transitive dependents."""
    queue = deque([start_step])
    while queue:
        current = queue.popleft()
        for dependent in state.adjacency.get(current, []):
            if dependent in state.completed or dependent in state.skipped:
                continue
            _mark_skipped(state, dependent, reason)
            queue.append(dependent)


def _schedule_ready_steps(state: _RunState) -> None:
    """Schedule ready (in-degree 0) steps up to max_concurrency."""
    while state.ready and len(state.running) < state.max_concurrency:
        step_name = state.ready.popleft()
        if step_name in state.completed or step_name in state.skipped:
            continue

        state.running.add(step_name)
        # Move state to READY before spawning task
        state.state_manager.transition(step_name, StepState.READY)
        state.tasks.add(
            asyncio.create_task(_run_step(state, step_name), name=step_name)
        )


async def _record_task_exception(
    state: _RunState, task: asyncio.Task, exc: BaseException
) -> None:
    """Record a step task that raised, or ended cancelled, as a FAILED step.

    The step ends like any other failed step: a FAILED result, lifecycle
    and context entry, its dependents cascade-skipped, and a ``step_end``
    event, which is awaited only after all of that is recorded.
    """
    # Retrieve the step name from the task (set via name= in create_task).
    failed_name = task.get_name()
    logger.error(
        "Unhandled exception in DAG task for step %r: %s",
        failed_name,
        exc,
        exc_info=True,
    )
    state.running.discard(failed_name)
    step_result = StepResult(step_name=failed_name, status=StepStatus.FAILED)
    step_result.error = str(exc)
    step_result.error_type = type(exc).__name__
    step_result.end_time = datetime.now(UTC)
    state.results[failed_name] = step_result
    state.result.add_step(step_result)
    state.completed.add(failed_name)
    # set_state, as in _handle_timeout: the task may have failed before its
    # lifecycle reached RUNNING, and READY -> FAILED is not a transition.
    state.state_manager.set_state(failed_name, StepState.FAILED)
    state.result.overall_status = StepStatus.FAILED
    _cascade_skip(state, failed_name, "unhandled exception")
    # Awaits come last: a workflow timeout that interrupts them must find the
    # step fully recorded, because timeout recovery skips completed steps.
    await _mark_context_failed(state.ctx, failed_name, step_result.error)
    await _emit_step_end(state, failed_name, step_result)


async def _emit_step_end(
    state: _RunState, step_name: str, step_result: StepResult
) -> None:
    """Signal step completion to external observers (UI/WebSockets)."""
    await _notify(
        state,
        {
            "type": "step_end",
            "run_id": state.result.workflow_id,
            "step": step_name,
            "status": step_result.status.value,
            "duration_ms": step_result.duration_ms,
            "model_used": step_result.model_used,
            "tokens_used": step_result.metadata.get("tokens_used"),
            "tier": step_result.tier,
            "input": step_result.input_data,
            "output": step_result.output_data,
            "error": step_result.error,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


def _transition_outcome_state(
    state: _RunState, step_name: str, step_result: StepResult
) -> None:
    """Move the step state machine based on the step's terminal status."""
    if step_result.status == StepStatus.SUCCESS:
        state.state_manager.transition(step_name, StepState.SUCCESS)
    elif step_result.status == StepStatus.SKIPPED:
        state.state_manager.transition(step_name, StepState.SKIPPED)
        # Skipped via should_run() (condition not met).  Mark
        # complete in ctx so downstream dependencies can proceed.
        if step_name not in state.ctx.completed_steps:
            state.ctx.completed_steps.append(step_name)
        state.skipped.add(step_name)
    else:
        state.state_manager.transition(step_name, StepState.FAILED)


def _unlock_downstream(state: _RunState, step_name: str) -> None:
    """Decrement dependents' in-degree; enqueue any that reach zero."""
    for dependent in state.adjacency.get(step_name, []):
        if dependent in state.completed or dependent in state.skipped:
            continue
        state.in_degree[dependent] -= 1
        if state.in_degree[dependent] == 0:
            state.ready.append(dependent)


def _fail_nonterminal(step_result: StepResult) -> StepResult:
    """Return *step_result*, or a FAILED copy if its status is not terminal.

    A step executor must finish with SUCCESS, FAILED or SKIPPED. A
    PENDING, RUNNING or RETRYING result used to unblock its dependents
    and let the run report SUCCESS; ADR-060 requires such a step to fail
    closed.
    """
    if step_result.status in _TERMINAL_STATUSES:
        return step_result
    reason = f"step finished with non-terminal status {step_result.status.value!r}"
    failed: StepResult = step_result.model_copy(
        update={
            "status": StepStatus.FAILED,
            "error": f"{reason}: {step_result.error}" if step_result.error else reason,
            "error_type": "NonTerminalStatus",
            "end_time": step_result.end_time or datetime.now(UTC),
            "metadata": {
                **step_result.metadata,
                "nonterminal_status": step_result.status.value,
            },
        }
    )
    return failed


async def _mark_context_failed(
    ctx: ExecutionContext, step_name: str, error: str
) -> None:
    """Record *step_name* as failed in *ctx*, dropping any stale completion.

    An executor can mark a step complete before its result is settled
    FAILED; the context must agree with the result it is saved beside.
    """
    if step_name in ctx.completed_steps:
        ctx.completed_steps.remove(step_name)
    await ctx.mark_step_failed(step_name, error)


async def _process_done_task(state: _RunState, task: asyncio.Task) -> None:
    """Handle a single completed task: record result and propagate."""
    try:
        step_name, raw_result = task.result()
    except (Exception, asyncio.CancelledError) as exc:
        # A step task that was cancelled, or raised CancelledError itself, is
        # a failed step. Cancellation of execute() itself never surfaces here;
        # it is raised at the scheduler's own await points (see _run_dag).
        await _record_task_exception(state, task, exc)
        return

    step_result = _fail_nonterminal(raw_result)
    state.running.discard(step_name)
    state.results[step_name] = step_result
    state.result.add_step(step_result)
    state.completed.add(step_name)
    _transition_outcome_state(state, step_name, step_result)
    if step_result.is_failed:
        # Failure propagation: skip all steps that depend on a failed step.
        state.result.overall_status = StepStatus.FAILED
        _cascade_skip(state, step_name, "dependency failed")
    else:
        _unlock_downstream(state, step_name)

    # Awaits come last: a workflow timeout that interrupts them must find the
    # step fully recorded, because timeout recovery skips completed steps.
    if step_result is not raw_result:
        await _mark_context_failed(state.ctx, step_name, step_result.error or "")
    await _emit_step_end(state, step_name, step_result)


async def _scheduling_loop(state: _RunState) -> None:
    """Inner coroutine containing the DAG scheduling loop.

    Extracted so that :func:`asyncio.timeout` can apply a workflow-level
    timeout boundary without restructuring the outer function.  All mutable
    state is shared via the :class:`_RunState` container.
    """
    # Phase 2: Execution Loop
    # We continue until every step in the DAG is either completed or
    # skipped.
    while len(state.completed) < len(state.dag.steps):

        # 1. Schedule all currently 'ready' steps (in-degree 0)
        # obeying the max_concurrency limit.
        _schedule_ready_steps(state)

        # 2. Deadlock detection
        # Unreachable for a validated DAG with max_concurrency >= 1: an
        # unfinished step whose dependencies have all finished is always
        # queued, running, or cascade-skipped. If scheduling ever stalls
        # anyway, fail the run rather than drop the steps and report success.
        if not state.tasks:
            remaining = set(state.dag.steps.keys()) - state.completed - state.skipped
            for step_name in remaining:
                _mark_skipped(state, step_name, "scheduler deadlock")
            state.result.overall_status = StepStatus.FAILED
            state.result.metadata["error"] = (
                f"Scheduler deadlock: {len(remaining)} step(s) could not be scheduled."
            )
            logger.error(
                "DAG scheduler deadlock: workflow=%r unscheduled=%s",
                state.dag.name,
                sorted(remaining),
            )
            break

        # 3. Wait for the next task to complete
        done, pending = await asyncio.wait(
            state.tasks, return_when=asyncio.FIRST_COMPLETED
        )
        state.tasks.clear()
        state.tasks.update(pending)

        # 4-6. Handle each completed task.
        for task in done:
            await _process_done_task(state, task)


async def _cancel_in_flight(state: _RunState) -> None:
    """Cancel every in-flight step task and wait for each one to finish.

    Awaiting them prevents "Task was destroyed but it is pending"
    warnings and guarantees no step keeps running after the scheduler
    has stopped. A step that suppresses its cancellation delays this
    indefinitely.
    """
    if not state.tasks:
        return
    for task in state.tasks:
        task.cancel()
    await asyncio.gather(*state.tasks, return_exceptions=True)
    state.tasks.clear()


async def _handle_timeout(state: _RunState) -> None:
    """Recover from a workflow-level timeout: cancel, fail, skip."""
    timeout_msg = (
        f"Workflow '{state.dag.name}' exceeded the {state.timeout}s timeout. "
        "In-flight steps were cancelled."
    )
    # 1. Record the event on the active OTEL span (if any) and mark it ERROR so
    #    a timed-out workflow does not render green in the exported trace.
    if state.span is not None:
        state.span.set_attribute("workflow.timeout_exceeded", True)
        state.span.add_event(
            "workflow.timeout",
            {"workflow.timeout_seconds": state.timeout},
        )
        _mark_span_error(state.span, timeout_msg)
    logger.warning(
        "DAG timeout: workflow=%r timeout_seconds=%s",
        state.dag.name,
        state.timeout,
    )

    # 2. Cancel every in-flight asyncio task and await its cleanup.
    await _cancel_in_flight(state)

    # 3. Transition every step still in RUNNING state to FAILED and
    #    record a StepResult for it.
    now = datetime.now(UTC)
    for step_name in state.running:
        if step_name not in state.completed:
            step_result = StepResult(step_name=step_name, status=StepStatus.FAILED)
            step_result.error = timeout_msg
            step_result.error_type = "TimeoutError"
            step_result.end_time = now
            state.results[step_name] = step_result
            state.result.add_step(step_result)
            state.completed.add(step_name)
            state.state_manager.set_state(step_name, StepState.FAILED)
            _cascade_skip(state, step_name, "workflow timeout")

    # 4. Skip any remaining steps that never started.
    remaining = set(state.dag.steps.keys()) - state.completed - state.skipped
    for step_name in remaining:
        _mark_skipped(state, step_name, "workflow timeout")

    state.result.overall_status = StepStatus.FAILED
    state.result.metadata["timeout_exceeded"] = True
    state.result.metadata["timeout_seconds"] = state.timeout
    state.result.metadata["error"] = timeout_msg


class DAGExecutor:
    """Execute a DAG with maximum parallelism.

    Orchestrates the full lifecycle of a workflow run: validation,
    scheduling, parallel execution, failure propagation, and result
    assembly.  Uses :class:`StepExecutor` for individual step runs and
    :class:`StepStateManager` for lifecycle state tracking.

    Attributes:
        _step_executor: Delegate that handles single-step execution
            (input mapping, retry, timeout, hooks).  Shared across calls;
            must itself be concurrency-safe (stateless between executions).
    """

    def __init__(self, step_executor: StepExecutor | None = None):
        self._step_executor = step_executor or StepExecutor()

    async def execute(
        self,
        workflow: Any,
        ctx: ExecutionContext | None = None,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Execute a validated DAG with dynamic scheduling and concurrency limits.

        Execution proceeds in a tight loop:

        1. **Schedule** — pop ready steps (in-degree 0) up to *max_concurrency*.
        2. **Deadlock check** — if no tasks running and steps remain, skip them
           and fail the run.
        3. **Await** — ``asyncio.wait(FIRST_COMPLETED)`` for the next result.
        4. **Handle outcome** — on success, decrement downstream in-degrees;
           on failure, cascade-skip all transitive dependents.
        5. **Repeat** until every step is completed or skipped.

        Args:
            workflow: Validated DAG definition to execute.
            ctx: Shared execution context.  A new one is created if *None*.
            on_update: Optional async callback invoked on every lifecycle
                event (``workflow_start``, ``step_start``, ``step_end``,
                ``workflow_end``).  Used by the server layer to broadcast
                real-time updates via WebSocket/SSE.
            timeout: Optional wall-clock timeout in seconds for the entire
                workflow.  When exceeded, all in-flight asyncio tasks are
                cancelled (awaited to prevent leaks), any step still in
                ``RUNNING`` state is transitioned to ``FAILED``, transitive
                dependents are cascade-skipped, and the returned
                :class:`WorkflowResult` has ``overall_status=FAILED`` with
                a descriptive error.  ``None`` (default) disables the
                boundary and preserves existing behaviour exactly.

                This parameter is also accepted via ``**kwargs`` as
                ``timeout=<value>`` so callers that dispatch options through
                ``kwargs`` (e.g. the server layer) work without signature
                changes elsewhere::

                    await executor.execute(dag, **{"timeout": 30.0})

            **kwargs: Engine-specific options.  Supported:
                - ``max_concurrency`` (int, default 10): Upper bound on
                  simultaneously running steps.  Must be an integer >= 1;
                  anything else raises :class:`ValueError`.
                - ``timeout`` (float | None): Alias for the *timeout*
                  positional keyword argument above.

        Returns:
            :class:`WorkflowResult` with per-step results, overall status,
            and the final merged context as ``final_output``.
        """
        if not isinstance(workflow, DAG):
            raise ValueError(
                f"DAGExecutor expects a DAG, got {type(workflow).__name__}"
            )
        dag: DAG = workflow
        raw_concurrency = kwargs.get("max_concurrency", 10)
        # A limit below 1 schedules nothing, which used to skip every step and
        # still report SUCCESS. bool is excluded because it is an int subclass.
        if (
            isinstance(raw_concurrency, bool)
            or not isinstance(raw_concurrency, int)
            or raw_concurrency < 1
        ):
            raise ValueError(
                f"max_concurrency must be an integer >= 1, got {raw_concurrency!r}"
            )
        max_concurrency: int = raw_concurrency
        # Accept timeout via **kwargs as documented — explicit param wins.
        effective_timeout: float | None = (
            timeout if timeout is not None else kwargs.get("timeout")
        )
        if ctx is None:
            ctx = get_context()

        dag.validate()

        _tracer = _get_tracer()
        if _tracer:
            with _tracer.start_as_current_span("engine.execute") as _span:
                _span.set_attribute("workflow.name", dag.name)
                if effective_timeout is not None:
                    _span.set_attribute("workflow.timeout_seconds", effective_timeout)
                return await self._run_dag(
                    dag, ctx, on_update, max_concurrency, effective_timeout, _span
                )
        return await self._run_dag(
            dag, ctx, on_update, max_concurrency, effective_timeout, None
        )

    async def _run_dag(
        self,
        dag: DAG,
        ctx: ExecutionContext,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None,
        max_concurrency: int,
        timeout: float | None = None,
        span: Any = None,
    ) -> WorkflowResult:
        """Internal DAG scheduling loop (separated for OTEL span instrumentation)."""
        # Local per-execution state manager — safe for concurrent calls on the
        # same DAGExecutor instance (e.g. NativeEngine reuses one executor).
        state_manager = StepStateManager()

        result = WorkflowResult(
            workflow_id=ctx.workflow_id,
            workflow_name=dag.name,
            overall_status=StepStatus.RUNNING,
        )

        adjacency = dag.build_adjacency_list()
        in_degree = {name: len(step.depends_on) for name, step in dag.steps.items()}

        # Bundle all per-execution state so the scheduling helpers (module
        # level) can share it by reference — preserving the original
        # closure-based behaviour exactly.
        state = _RunState(
            step_executor=self._step_executor,
            dag=dag,
            ctx=ctx,
            on_update=on_update,
            span=span,
            timeout=timeout,
            max_concurrency=max_concurrency,
            state_manager=state_manager,
            result=result,
            adjacency=adjacency,
            in_degree=in_degree,
            ready=deque([name for name, deg in in_degree.items() if deg == 0]),
        )
        await _notify(
            state,
            {
                "type": "workflow_start",
                "run_id": result.workflow_id,
                "workflow_name": result.workflow_name,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        try:
            if timeout is not None:
                async with asyncio.timeout(timeout):
                    await _scheduling_loop(state)
            else:
                await _scheduling_loop(state)
        except TimeoutError:
            await _handle_timeout(state)
        except BaseException:
            # execute() itself was cancelled, or the loop raised: never leave
            # step tasks running with nothing left to await them.
            await _cancel_in_flight(state)
            raise

        if result.overall_status == StepStatus.RUNNING:
            result.overall_status = StepStatus.SUCCESS

        # Surface a failed workflow on the engine.execute span. The timeout
        # path already marked the span ERROR with a timeout-specific message
        # (metadata flag set in _handle_timeout); only mark here for the
        # non-timeout failure paths (a step failed and cascaded).
        if result.overall_status == StepStatus.FAILED and not result.metadata.get(
            "timeout_exceeded"
        ):
            _mark_span_error(
                span, f"Workflow '{dag.name}' failed: one or more steps errored."
            )

        result.steps = [
            state.results[step_name]
            for step_name in dag.steps
            if step_name in state.results
        ]
        result.final_output = ctx.all_variables()
        result.mark_complete(result.overall_status == StepStatus.SUCCESS)

        await _notify(
            state,
            {
                "type": "workflow_end",
                "run_id": result.workflow_id,
                "status": result.overall_status.value,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        return result
