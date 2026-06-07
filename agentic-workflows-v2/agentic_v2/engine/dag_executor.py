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
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from ..contracts import StepResult, StepStatus, WorkflowResult
from ..integrations.otel import get_tracer as _get_tracer
from .context import ExecutionContext, get_context
from .dag import DAG
from .step import StepExecutor
from .step_state import StepState, StepStateManager

logger = logging.getLogger(__name__)


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
        effective_timeout: float | None = timeout if timeout is not None else kwargs.get("timeout")
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

        ready = deque([name for name, deg in in_degree.items() if deg == 0])
        running: set[str] = set()
        completed: set[str] = set()
        skipped: set[str] = set()
        results: dict[str, StepResult] = {}

        async def run_step(step_name: str) -> tuple[str, StepResult]:
            """Execute a single step and return its name + result tuple."""
            state_manager.transition(step_name, StepState.RUNNING)
            if on_update:
                await on_update(
                    {
                        "type": "step_start",
                        "run_id": result.workflow_id,
                        "step": step_name,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
            step_def = dag.steps[step_name]
            step_result = await self._step_executor.execute(step_def, ctx)
            return step_name, step_result

        def mark_skipped(step_name: str, reason: str) -> None:
            """Record a step as SKIPPED with a human-readable reason."""
            if step_name in completed or step_name in skipped:
                return
            step_result = StepResult(step_name=step_name, status=StepStatus.SKIPPED)
            step_result.metadata["skip_reason"] = reason
            step_result.end_time = datetime.now(UTC)
            results[step_name] = step_result
            result.add_step(step_result)
            completed.add(step_name)
            skipped.add(step_name)
            state_manager.set_state(step_name, StepState.SKIPPED)
            # Mark as complete in ctx so downstream should_run() dependency
            # checks pass.  Skipped steps are logically "done" — they just
            # didn't produce output.
            if step_name not in ctx.completed_steps:
                ctx.completed_steps.append(step_name)

        def cascade_skip(start_step: str, reason: str) -> None:
            """BFS from *start_step* to skip all transitive dependents."""
            queue = deque([start_step])
            while queue:
                current = queue.popleft()
                for dependent in adjacency.get(current, []):
                    if dependent in completed or dependent in skipped:
                        continue
                    mark_skipped(dependent, reason)
                    queue.append(dependent)

        tasks: set[asyncio.Task] = set()

        def _schedule_ready_steps() -> None:
            """Schedule ready (in-degree 0) steps up to max_concurrency."""
            while ready and len(running) < max_concurrency:
                step_name = ready.popleft()
                if step_name in completed or step_name in skipped:
                    continue

                running.add(step_name)
                # Move state to READY before spawning task
                state_manager.transition(step_name, StepState.READY)
                tasks.add(
                    asyncio.create_task(run_step(step_name), name=step_name)
                )

        def _record_task_exception(task: asyncio.Task, exc: Exception) -> None:
            """Record an unhandled run_step exception as a FAILED step result."""
            # Retrieve the step name from the task (set via name= in create_task).
            failed_name = task.get_name()
            logger.error(
                "Unhandled exception in DAG task for step %r: %s",
                failed_name,
                exc,
                exc_info=True,
            )
            running.discard(failed_name)
            step_result = StepResult(
                step_name=failed_name, status=StepStatus.FAILED
            )
            step_result.error = str(exc)
            step_result.end_time = datetime.now(UTC)
            results[failed_name] = step_result
            result.add_step(step_result)
            completed.add(failed_name)
            result.overall_status = StepStatus.FAILED
            cascade_skip(failed_name, "unhandled exception")

        async def _emit_step_end(step_name: str, step_result: StepResult) -> None:
            """Signal step completion to external observers (UI/WebSockets)."""
            if on_update:
                await on_update(
                    {
                        "type": "step_end",
                        "run_id": result.workflow_id,
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
            step_name: str, step_result: StepResult
        ) -> None:
            """Move the step state machine based on the step's terminal status."""
            if step_result.status == StepStatus.SUCCESS:
                state_manager.transition(step_name, StepState.SUCCESS)
            elif step_result.status == StepStatus.SKIPPED:
                state_manager.transition(step_name, StepState.SKIPPED)
                # Skipped via should_run() (condition not met).  Mark
                # complete in ctx so downstream dependencies can proceed.
                if step_name not in ctx.completed_steps:
                    ctx.completed_steps.append(step_name)
                skipped.add(step_name)
            else:
                state_manager.transition(step_name, StepState.FAILED)

        def _unlock_downstream(step_name: str) -> None:
            """Decrement dependents' in-degree; enqueue any that reach zero."""
            for dependent in adjacency.get(step_name, []):
                if dependent in completed or dependent in skipped:
                    continue
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)

        async def _process_done_task(task: asyncio.Task) -> None:
            """Handle a single completed task: record result and propagate."""
            try:
                step_name, step_result = task.result()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _record_task_exception(task, exc)
                return

            running.discard(step_name)
            results[step_name] = step_result
            result.add_step(step_result)
            completed.add(step_name)

            await _emit_step_end(step_name, step_result)
            _transition_outcome_state(step_name, step_result)

            # Failure propagation: skip all steps that depend on a failed step.
            if step_result.is_failed:
                result.overall_status = StepStatus.FAILED
                cascade_skip(step_name, "dependency failed")
                return

            _unlock_downstream(step_name)

        async def _scheduling_loop() -> None:
            """Inner coroutine containing the DAG scheduling loop.

            Extracted so that :func:`asyncio.wait_for` can apply a
            workflow-level timeout boundary without restructuring the outer
            function.  All mutable state (``tasks``, ``running``,
            ``completed``, ``skipped``, ``results``, ``result``) is shared
            via closure with ``_run_dag``.
            """
            # Phase 2: Execution Loop
            # We continue until every step in the DAG is either completed or
            # skipped.
            while len(completed) < len(dag.steps):

                # 1. Schedule all currently 'ready' steps (in-degree 0)
                # obeying the max_concurrency limit.
                _schedule_ready_steps()

                # 2. Deadlock detection
                # If no tasks are running but we aren't done, some steps are
                # unreachable.
                if not tasks:
                    remaining = set(dag.steps.keys()) - completed - skipped
                    for step_name in remaining:
                        mark_skipped(step_name, "unmet dependencies")
                    break

                # 3. Wait for the next task to complete
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                tasks.clear()
                tasks.update(pending)

                # 4-6. Handle each completed task.
                for task in done:
                    await _process_done_task(task)

        async def _handle_timeout() -> None:
            """Recover from a workflow-level timeout: cancel, fail, skip."""
            # 1. Record the event on the active OTEL span (if any).
            if span is not None:
                span.set_attribute("workflow.timeout_exceeded", True)
                span.add_event(
                    "workflow.timeout",
                    {"workflow.timeout_seconds": timeout},
                )
            timeout_msg = (
                f"Workflow '{dag.name}' exceeded the {timeout}s timeout. "
                "In-flight steps were cancelled."
            )
            logger.warning(
                "DAG timeout: workflow=%r timeout_seconds=%s",
                dag.name,
                timeout,
            )

            # 2. Cancel every in-flight asyncio task and await cleanup to
            #    prevent "Task was destroyed but it is pending" warnings.
            if tasks:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                tasks.clear()

            # 3. Transition every step still in RUNNING state to FAILED and
            #    record a StepResult for it.
            now = datetime.now(UTC)
            for step_name in running:
                if step_name not in completed:
                    step_result = StepResult(
                        step_name=step_name, status=StepStatus.FAILED
                    )
                    step_result.error = timeout_msg
                    step_result.error_type = "TimeoutError"
                    step_result.end_time = now
                    results[step_name] = step_result
                    result.add_step(step_result)
                    completed.add(step_name)
                    state_manager.set_state(step_name, StepState.FAILED)
                    cascade_skip(step_name, "workflow timeout")

            # 4. Skip any remaining steps that never started.
            remaining = set(dag.steps.keys()) - completed - skipped
            for step_name in remaining:
                mark_skipped(step_name, "workflow timeout")

            result.overall_status = StepStatus.FAILED
            result.metadata["timeout_exceeded"] = True
            result.metadata["timeout_seconds"] = timeout
            result.metadata["error"] = timeout_msg

        try:
            if timeout is not None:
                async with asyncio.timeout(timeout):
                    await _scheduling_loop()
            else:
                await _scheduling_loop()
        except TimeoutError:
            await _handle_timeout()

        if result.overall_status == StepStatus.RUNNING:
            result.overall_status = StepStatus.SUCCESS

        result.steps = [
            results[step_name]
            for step_name in dag.steps
            if step_name in results
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
