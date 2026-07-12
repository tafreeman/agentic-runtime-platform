"""DAG executor with dynamic parallel scheduling.

Executes workflow steps as soon as their upstream dependencies are satisfied,
achieving maximum parallelism without artificial layer barriers.

Key design decisions:
- **Kahn's algorithm** for in-degree tracking at runtime (not just ordering).
- **asyncio.wait(FIRST_COMPLETED)** to unblock downstream steps the instant
  an upstream finishes, rather than waiting for an entire "wave" to complete.
- **Cascade skip** via BFS: when a step fails, all transitive dependents are
  marked SKIPPED so the executor can still finish cleanly.
- **Deadlock detection**: if no tasks are running and steps remain, unmet
  dependencies are flagged and the remaining steps are skipped.
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


async def _run_step(state: _RunState, step_name: str) -> tuple[str, StepResult]:
    """Execute a single step and return its name + result tuple."""
    state.state_manager.transition(step_name, StepState.RUNNING)
    if state.on_update:
        await state.on_update(
            {
                "type": "step_start",
                "run_id": state.result.workflow_id,
                "step": step_name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
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


def _record_task_exception(
    state: _RunState, task: asyncio.Task, exc: Exception
) -> None:
    """Record an unhandled run_step exception as a FAILED step result."""
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
    step_result.end_time = datetime.now(UTC)
    state.results[failed_name] = step_result
    state.result.add_step(step_result)
    state.completed.add(failed_name)
    state.result.overall_status = StepStatus.FAILED
    _cascade_skip(state, failed_name, "unhandled exception")


async def _emit_step_end(
    state: _RunState, step_name: str, step_result: StepResult
) -> None:
    """Signal step completion to external observers (UI/WebSockets)."""
    if state.on_update:
        await state.on_update(
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
            }
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


async def _process_done_task(state: _RunState, task: asyncio.Task) -> None:
    """Handle a single completed task: record result and propagate."""
    try:
        step_name, step_result = task.result()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _record_task_exception(state, task, exc)
        return

    state.running.discard(step_name)
    state.results[step_name] = step_result
    state.result.add_step(step_result)
    state.completed.add(step_name)

    await _emit_step_end(state, step_name, step_result)
    _transition_outcome_state(state, step_name, step_result)

    # Failure propagation: skip all steps that depend on a failed step.
    if step_result.is_failed:
        state.result.overall_status = StepStatus.FAILED
        _cascade_skip(state, step_name, "dependency failed")
        return

    _unlock_downstream(state, step_name)


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
        # If no tasks are running but we aren't done, some steps are
        # unreachable.
        if not state.tasks:
            remaining = set(state.dag.steps.keys()) - state.completed - state.skipped
            for step_name in remaining:
                _mark_skipped(state, step_name, "unmet dependencies")
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

    # 2. Cancel every in-flight asyncio task and await cleanup to
    #    prevent "Task was destroyed but it is pending" warnings.
    if state.tasks:
        for t in state.tasks:
            t.cancel()
        await asyncio.gather(*state.tasks, return_exceptions=True)
        state.tasks.clear()

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
        2. **Deadlock check** — if no tasks running and steps remain, skip them.
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
                  simultaneously running steps.
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
        max_concurrency: int = kwargs.get("max_concurrency", 10)
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

        if on_update:
            await on_update(
                {
                    "type": "workflow_start",
                    "run_id": result.workflow_id,
                    "workflow_name": result.workflow_name,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
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

        try:
            if timeout is not None:
                async with asyncio.timeout(timeout):
                    await _scheduling_loop(state)
            else:
                await _scheduling_loop(state)
        except TimeoutError:
            await _handle_timeout(state)

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

        if on_update:
            await on_update(
                {
                    "type": "workflow_end",
                    "run_id": result.workflow_id,
                    "status": result.overall_status.value,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

        return result
