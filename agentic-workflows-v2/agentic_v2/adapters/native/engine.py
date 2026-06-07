"""Native execution engine — wraps DAGExecutor and PipelineExecutor.

:class:`NativeEngine` satisfies the :class:`ExecutionEngine` protocol
by delegating to the existing ``engine/`` executors based on the
workflow type.  This is the default adapter for runtime-generated DAG
and Pipeline execution; named YAML workflows default to the LangGraph
adapter in CLI/server requests unless ``--adapter native`` or
``adapter="native"`` is supplied.

Additionally satisfies :class:`SupportsCheckpointing` (via structural
subtyping) when constructed with a ``checkpoint_db_path``.  Checkpoint
data is persisted to a SQLite database using :class:`CheckpointStore`.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from ...contracts import StepStatus, WorkflowResult
from ...engine.context import ExecutionContext
from ...engine.dag import DAG
from ...engine.dag_executor import DAGExecutor
from ...engine.pipeline import Pipeline, PipelineExecutor
from ...workflows.loader import WorkflowDefinition
from ._checkpoint_store import CheckpointStore

logger = logging.getLogger(__name__)


class NativeEngine:
    """Adapter that delegates to the native DAG/Pipeline executors.

    Satisfies :class:`~agentic_v2.core.protocols.ExecutionEngine` via
    structural subtyping — no explicit inheritance required.

    When *checkpoint_db_path* is provided, also satisfies
    :class:`~agentic_v2.core.protocols.SupportsCheckpointing` by
    persisting per-step results to a SQLite database keyed by
    ``thread_id``.

    Supported workflow types:

    - :class:`DAG` → :class:`DAGExecutor`
    - :class:`Pipeline` → :class:`PipelineExecutor`
    """

    def __init__(
        self,
        checkpoint_db_path: Path | None = None,
    ) -> None:
        self._dag_executor = DAGExecutor()
        self._pipeline_executor = PipelineExecutor()
        self._checkpoint_store: CheckpointStore | None = (
            CheckpointStore(checkpoint_db_path)
            if checkpoint_db_path is not None
            else None
        )
        self._checkpoint_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # ExecutionEngine protocol
    # ------------------------------------------------------------------

    async def execute(
        self,
        workflow: Any,
        ctx: ExecutionContext | None = None,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Execute a workflow using the appropriate native executor.

        If a ``thread_id`` is supplied via *kwargs* and a checkpoint store
        is configured, each successfully completed step is persisted to
        SQLite so that :meth:`resume` can skip already-finished work.

        Args:
            workflow: A :class:`DAG` or :class:`Pipeline` instance.
            ctx: Execution context for shared variables and services.
            on_update: Async callback for progress events.
            **kwargs: Forwarded to the underlying executor.  Supported
                extra keys:

                - ``thread_id`` (str): enables checkpointing for this run.
                - ``max_concurrency`` (int): DAG parallelism limit.

        Returns:
            :class:`WorkflowResult` with step results and status.

        Raises:
            TypeError: If *workflow* is not a supported type.
        """
        if ctx is None:
            ctx = ExecutionContext()

        thread_id: str | None = kwargs.pop("thread_id", None)
        should_checkpoint = thread_id is not None and self._checkpoint_store is not None

        # Wrap on_update to intercept step completions for checkpointing
        wrapped_update = (
            self._wrap_on_update(
                workflow,
                on_update,
                thread_id,
            )
            if should_checkpoint
            else on_update
        )

        try:
            return await self._dispatch(workflow, ctx, wrapped_update, **kwargs)
        finally:
            if self._checkpoint_tasks:
                await asyncio.gather(
                    *list(self._checkpoint_tasks),
                    return_exceptions=True,
                )

    # ------------------------------------------------------------------
    # SupportsCheckpointing protocol
    # ------------------------------------------------------------------

    def get_checkpoint_state(
        self,
        workflow: Any,
        *,
        thread_id: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Retrieve the latest checkpoint state for a workflow thread.

        Runs the async :meth:`CheckpointStore.read` synchronously via
        a new event-loop invocation so that the method signature matches
        the :class:`SupportsCheckpointing` protocol (which is sync).

        Args:
            workflow: Workflow definition (unused; present for protocol
                conformance).
            thread_id: Execution thread identifier.
            **kwargs: Reserved for future use.

        Returns:
            Mapping of ``{step_name: {status, output_data, ...}}``, or
            ``None`` if no checkpoints exist for *thread_id*.
        """
        if self._checkpoint_store is None:
            return None

        # Use asyncio.run in a sync context, or get the running loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # We're inside an async context — create a future and run it
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                state = pool.submit(
                    asyncio.run,
                    self._checkpoint_store.read(thread_id),
                ).result()
        else:
            state = asyncio.run(self._checkpoint_store.read(thread_id))

        if not state:
            return None
        return state

    async def resume(
        self,
        workflow: Any,
        *,
        thread_id: str,
        ctx: ExecutionContext | None = None,
        **kwargs: Any,
    ) -> Any:
        """Resume execution from the last checkpoint.

        Loads previously checkpointed step results for *thread_id* and
        pre-populates the execution context so that already-completed
        steps are skipped by the DAG executor.

        If no checkpoints exist for *thread_id*, the workflow is executed
        from scratch (identical to calling :meth:`execute`).

        Args:
            workflow: A :class:`DAG` or :class:`Pipeline` instance.
            thread_id: Execution thread to resume.
            ctx: Execution context (created if ``None``).
            **kwargs: Forwarded to :meth:`execute`.

        Returns:
            :class:`WorkflowResult` from the (resumed) execution.
        """
        if ctx is None:
            ctx = ExecutionContext()

        if self._checkpoint_store is not None:
            saved = await self._checkpoint_store.read(thread_id)
            if saved:
                logger.info(
                    "Resuming thread=%s with %d checkpointed steps",
                    thread_id,
                    len(saved),
                )
                self._restore_checkpoint_state(ctx, saved)

        return await self.execute(
            workflow,
            ctx=ctx,
            thread_id=thread_id,
            **kwargs,
        )

    @staticmethod
    def _restore_checkpoint_state(
        ctx: ExecutionContext, saved: dict[str, Any]
    ) -> None:
        """Replay successful checkpointed steps into *ctx*.

        Marks each successful step as completed (so the DAG executor skips it)
        and restores its output data into the context variables.
        """
        for step_name, step_data in saved.items():
            if step_data["status"] != StepStatus.SUCCESS.value:
                continue
            # Mark step as completed in context so DAG executor
            # skips it via should_run() dependency checks.
            if step_name not in ctx.completed_steps:
                ctx.completed_steps.append(step_name)
            # Restore output data into context variables
            for key, value in step_data["output_data"].items():
                ctx.set_sync(key, value)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _schedule_checkpoint_write(self, coro: Awaitable[None]) -> None:
        """Track a checkpoint write task until it finishes."""
        task = asyncio.create_task(coro)
        self._checkpoint_tasks.add(task)

        def _discard_done_task(done_task: asyncio.Task[None]) -> None:
            self._checkpoint_tasks.discard(done_task)
            try:
                done_task.result()
            except Exception:
                logger.exception("Checkpoint write failed")

        task.add_done_callback(_discard_done_task)

    async def _dispatch(
        self,
        workflow: Any,
        ctx: ExecutionContext,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Route *workflow* to the correct underlying executor.

        Raises:
            TypeError: If *workflow* is not a supported type.
        """
        if isinstance(workflow, WorkflowDefinition):
            workflow = workflow.dag
        if isinstance(workflow, DAG):
            return await self._dag_executor.execute(
                workflow, ctx, on_update=on_update, **kwargs
            )
        elif isinstance(workflow, Pipeline):
            return await self._pipeline_executor.execute(
                workflow, ctx, on_update=on_update, **kwargs
            )
        else:
            raise TypeError(
                f"Unsupported workflow type: {type(workflow).__name__}. "
                f"NativeEngine supports DAG and Pipeline."
            )

    def _wrap_on_update(
        self,
        workflow: Any,
        original_callback: Callable[[dict[str, Any]], Awaitable[None]] | None,
        thread_id: str | None,
    ) -> Callable[[dict[str, Any]], Awaitable[None]]:
        """Create a wrapper around *original_callback* that also writes checkpoints on
        ``step_end`` events.

        The checkpoint write is launched as a tracked background task so it
        does not block DAG scheduling.
        """
        store = self._checkpoint_store
        workflow_name = getattr(workflow, "name", "unknown")

        async def _on_update(event: dict[str, Any]) -> None:
            # Forward to the original callback first
            if original_callback is not None:
                await original_callback(event)

            # Persist checkpoint on successful step completion
            if (
                store is not None
                and thread_id is not None
                and event.get("type") == "step_end"
                and event.get("status") == StepStatus.SUCCESS.value
            ):
                step_name = event.get("step", "")
                output_data = event.get("output", {}) or {}
                self._schedule_checkpoint_write(
                    store.write(
                        thread_id=thread_id,
                        workflow_name=workflow_name,
                        step_name=step_name,
                        status=StepStatus.SUCCESS.value,
                        output_data=output_data,
                    )
                )

        return _on_update
