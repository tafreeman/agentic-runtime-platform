"""Top-level workflow executor with unified orchestration.

:class:`WorkflowExecutor` is the single entry point for running any
workflow structure — a single :class:`StepDefinition`, a :class:`Pipeline`,
a :class:`DAG`, or a plain list of steps.  It wraps the lower-level
:class:`DAGExecutor` and :class:`PipelineExecutor` with:

- **Global timeout** with graceful cancellation.
- **Execution history** — timestamped audit trail of every lifecycle event.
- **Event listeners** — pluggable callbacks for observability.
- **Service injection** — registers :class:`SmartModelRouter` and
  :class:`ToolRegistry` into the execution context's DI container.
- **Context growth monitoring** — warns when variable count exceeds limits.
- **Cleanup guarantees** — context reference is cleared on completion.

Module-level convenience functions :func:`execute` and :func:`run` provide
a global-singleton shortcut for simple scripts and tests.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

from ..contracts import StepResult, StepStatus, WorkflowResult
from ..models import SmartModelRouter, get_smart_router
from ..tools import ToolRegistry, get_registry
from .context import ExecutionContext
from .dag import DAG
from .dag_executor import DAGExecutor
from .pipeline import ConditionalBranch, ParallelGroup, Pipeline, PipelineExecutor
from .step import StepDefinition, StepExecutor


class ExecutorEvent(str, Enum):
    """Events emitted by executor."""

    WORKFLOW_START = "workflow_start"
    WORKFLOW_END = "workflow_end"
    STEP_START = "step_start"
    STEP_END = "step_end"
    ERROR = "error"
    CANCELLED = "cancelled"
    CHECKPOINT = "checkpoint"


EventListener = Callable[[ExecutorEvent, dict[str, Any]], None]


@dataclass
class ExecutionConfig:
    """Configuration knobs for :class:`WorkflowExecutor`.

    Attributes:
        global_timeout_seconds: Wall-clock cap for the entire workflow
            (``None`` = unlimited).
        step_default_timeout_seconds: Default per-step timeout applied when
            a step definition has no explicit timeout.
        max_global_retries: Number of full-workflow retries on failure.
        enable_checkpoints: Whether to save checkpoints during execution.
        checkpoint_interval: Save a checkpoint every *N* completed steps.
        max_memory_mb: Reserved — memory limit for the executor process.
        max_context_variables: Soft cap; a warning is emitted when exceeded.
        cleanup_on_complete: Clear the context reference after execution.
        debug_mode: Enable verbose diagnostic output.
        trace_steps: Log every step start/end at DEBUG level.
    """

    # Timeouts
    global_timeout_seconds: float | None = None
    step_default_timeout_seconds: float = 300.0

    # Retries
    max_global_retries: int = 0

    # Checkpointing
    enable_checkpoints: bool = False
    checkpoint_interval: int = 5

    # Resource limits
    max_memory_mb: int | None = None
    max_context_variables: int = 1000

    # Cleanup
    cleanup_on_complete: bool = True

    # Debugging
    debug_mode: bool = False
    trace_steps: bool = False


@dataclass
class ExecutionHistory:
    """Audit trail for workflow execution."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        event_type: str,
        step_name: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Record an event."""
        self.entries.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": event_type,
                "step": step_name,
                "data": data or {},
            }
        )

    def get_step_history(self, step_name: str) -> list[dict[str, Any]]:
        """Get history for a specific step."""
        return [e for e in self.entries if e.get("step") == step_name]

    def get_errors(self) -> list[dict[str, Any]]:
        """Get all error entries."""
        return [e for e in self.entries if e.get("event") == "error"]


class WorkflowExecutor:
    """Unified executor for all workflow types.

    Dispatches to :class:`DAGExecutor` (for :class:`DAG`),
    :class:`PipelineExecutor` (for :class:`Pipeline`), or runs steps
    directly (single step / list).  Wraps execution with global timeout,
    event emission, history recording, and service injection.

    Attributes:
        config: Execution configuration (timeouts, checkpoints, limits).
        router: :class:`SmartModelRouter` injected into the context's
            DI container for LLM model selection.
        tools: :class:`ToolRegistry` injected into the context.
    """

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        router: SmartModelRouter | None = None,
        tools: ToolRegistry | None = None,
    ):
        self.config = config or ExecutionConfig()
        self.router = router or get_smart_router()
        self.tools = tools or get_registry()

        self._step_executor = StepExecutor()
        self._pipeline_executor = PipelineExecutor()

        self._listeners: list[EventListener] = []
        self._history = ExecutionHistory()
        self._cancelled = False
        self._current_ctx: ExecutionContext | None = None

    def add_listener(self, listener: EventListener) -> None:
        """Add an event listener."""
        self._listeners.append(listener)

    def remove_listener(self, listener: EventListener) -> None:
        """Remove an event listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def _emit(self, event: ExecutorEvent, data: dict[str, Any]) -> None:
        """Emit event to all listeners."""
        for listener in self._listeners:
            try:
                result = listener(event, data)
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "Event listener %s failed for %s: %s",
                    getattr(listener, "__name__", repr(listener)),
                    event.value,
                    e,
                    exc_info=True,
                )

    async def execute(
        self,
        workflow: Any,
        ctx: ExecutionContext | None = None,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Execute a workflow.

        Accepts:
        - Single StepDefinition
        - Pipeline
        - DAG
        - List of StepDefinitions (sequential execution)

        Args:
            workflow: What to execute (StepDefinition, Pipeline, DAG, or list).
            ctx: Optional execution context.
            on_update: Optional async callback for progress events.
            **kwargs: Engine-specific options.  Use ``initial_vars`` (dict)
                to seed context variables.  ``max_concurrency`` is forwarded
                to :class:`DAGExecutor` when the workflow is a DAG.

        Returns:
            WorkflowResult with execution details.
        """
        initial_vars = kwargs.pop("initial_vars", {})
        self._validate_execute_inputs(workflow, ctx, initial_vars)
        self._engine_kwargs = kwargs

        # 1. Setup Execution Context
        # Every workflow run requires a context for variable storage and service registry.
        if ctx is None:
            ctx = ExecutionContext()

        self._current_ctx = ctx
        self._cancelled = False

        # 2. Seed Initial Variables
        # These are usually passed from the CLI or API (e.g., input file paths).
        for key, value in initial_vars.items():
            ctx.set_sync(key, value)

        # 3. Dynamic Service Injection
        # We register the router and tool registry into the context so that
        # individual steps/agents can access them without global lookups.
        ctx.services.register_singleton(SmartModelRouter, self.router)
        ctx.services.register_singleton(ToolRegistry, self.tools)

        # 4. Initialize Result Object
        workflow_name = self._get_workflow_name(workflow)
        result = WorkflowResult(
            workflow_id=ctx.workflow_id,
            workflow_name=workflow_name,
            overall_status=StepStatus.RUNNING,
        )

        # 5. Signal Start
        self._history.record("workflow_start", data={"name": workflow_name})
        await self._emit(ExecutorEvent.WORKFLOW_START, {"workflow": workflow_name})

        try:
            # Execute with global timeout
            if self.config.global_timeout_seconds:
                result = await asyncio.wait_for(
                    self._execute_workflow(workflow, ctx, result),
                    timeout=self.config.global_timeout_seconds,
                )
            else:
                result = await self._execute_workflow(workflow, ctx, result)

        except TimeoutError:
            result.overall_status = StepStatus.FAILED
            result.metadata["error"] = (
                f"Global timeout after {self.config.global_timeout_seconds}s"
            )
            result.metadata["error_type"] = "timeout"
            self._history.record("error", data={"type": "timeout"})

        except asyncio.CancelledError:
            result.overall_status = StepStatus.FAILED
            result.metadata["cancelled"] = True
            self._history.record("cancelled")
            await self._emit(ExecutorEvent.CANCELLED, {})
            # Finalize before propagating cancellation so subscribers (e.g. the
            # WebSocket run stream) receive a terminal WORKFLOW_END event instead
            # of hanging when the task is cancelled externally (e.g. shutdown).
            result.mark_complete(False)
            result.metadata["history_entries"] = len(self._history.entries)
            self._history.record(
                "workflow_end", data={"status": result.overall_status.value}
            )
            await self._emit(
                ExecutorEvent.WORKFLOW_END,
                {
                    "status": result.overall_status.value,
                    "duration_ms": result.total_duration_ms,
                },
            )
            if self.config.cleanup_on_complete:
                self._current_ctx = None
            raise

        except Exception as e:
            result.overall_status = StepStatus.FAILED
            result.metadata["error"] = str(e)
            result.metadata["traceback"] = traceback.format_exc()
            self._history.record(
                "error", data={"type": type(e).__name__, "message": str(e)}
            )
            await self._emit(ExecutorEvent.ERROR, {"error": str(e)})

        result.mark_complete(result.overall_status == StepStatus.SUCCESS)
        result.metadata["history_entries"] = len(self._history.entries)

        self._history.record(
            "workflow_end", data={"status": result.overall_status.value}
        )
        await self._emit(
            ExecutorEvent.WORKFLOW_END,
            {
                "status": result.overall_status.value,
                "duration_ms": result.total_duration_ms,
            },
        )

        # Cleanup
        if self.config.cleanup_on_complete:
            self._current_ctx = None

        return result

    async def _execute_workflow(
        self,
        workflow: StepDefinition | Pipeline | DAG | list[StepDefinition],
        ctx: ExecutionContext,
        result: WorkflowResult,
    ) -> WorkflowResult:
        """Dispatch to the appropriate sub-executor based on workflow type.

        - :class:`DAG` → :class:`DAGExecutor` (parallel, dependency-driven).
        - :class:`Pipeline` → :class:`PipelineExecutor` (sequential + parallel groups).
        - :class:`StepDefinition` → single step execution.
        - ``list[StepDefinition]`` → sequential execution with fail-fast.
        """

        if isinstance(workflow, DAG):
            # DAG execution via DAGExecutor
            dag_executor = DAGExecutor(step_executor=self._step_executor)
            mc = self._engine_kwargs.get("max_concurrency", 10)
            dag_result = await dag_executor.execute(workflow, ctx, max_concurrency=mc)
            result.steps = dag_result.steps
            result.overall_status = dag_result.overall_status
            result.final_output = dag_result.final_output

        elif isinstance(workflow, StepDefinition):
            # Single step
            step_result = await self._execute_step(workflow, ctx)
            result.add_step(step_result)
            result.overall_status = (
                StepStatus.SUCCESS if step_result.is_success else StepStatus.FAILED
            )

        elif isinstance(workflow, Pipeline):
            # Pipeline
            pipeline_result = await self._pipeline_executor.execute(workflow, ctx)
            result.steps = pipeline_result.steps
            result.overall_status = pipeline_result.overall_status
            result.final_output = pipeline_result.final_output

        elif isinstance(workflow, list):
            # Sequential steps
            for step_def in workflow:
                if self._cancelled:
                    break

                step_result = await self._execute_step(step_def, ctx)
                result.add_step(step_result)

                if step_result.is_failed:
                    result.overall_status = StepStatus.FAILED
                    break
            else:
                result.overall_status = StepStatus.SUCCESS

        # Set final output from context
        result.final_output = ctx.all_variables()

        return result

    async def _execute_step(
        self, step_def: StepDefinition, ctx: ExecutionContext
    ) -> StepResult:
        """Execute a single step with history recording and monitoring.

        Applies the default timeout from :attr:`config` if the step
        definition does not specify one, and checks context variable
        count against the configured limit afterward.
        """

        self._history.record("step_start", step_def.name)
        await self._emit(ExecutorEvent.STEP_START, {"step": step_def.name})

        # Apply default timeout if not set
        if step_def.timeout_seconds is None:
            step_def.timeout_seconds = self.config.step_default_timeout_seconds

        result = await self._step_executor.execute(step_def, ctx)

        self._history.record(
            "step_end",
            step_def.name,
            {"status": result.status.value, "duration_ms": result.duration_ms},
        )
        await self._emit(
            ExecutorEvent.STEP_END,
            {"step": step_def.name, "status": result.status.value},
        )

        # Check context size limits
        if self.config.max_context_variables:
            var_count = len(ctx.all_variables())
            if var_count > self.config.max_context_variables:
                result.metadata["warning"] = (
                    f"Context has {var_count} variables (limit: {self.config.max_context_variables})"
                )

        return result

    async def cancel(self) -> None:
        """Cancel current execution."""
        self._cancelled = True
        await self._step_executor.cancel_all()
        await self._pipeline_executor.cancel()

    def _get_workflow_name(
        self, workflow: StepDefinition | Pipeline | DAG | list[StepDefinition]
    ) -> str:
        """Get workflow name for logging."""
        if isinstance(workflow, DAG):
            return f"dag:{workflow.name}"
        elif isinstance(workflow, StepDefinition):
            return f"step:{workflow.name}"
        elif isinstance(workflow, Pipeline):
            return workflow.name
        elif isinstance(workflow, list):
            return f"sequence:{len(workflow)}_steps"
        return "unknown"

    def _validate_execute_inputs(
        self,
        workflow: Any,
        ctx: ExecutionContext | None,
        initial_vars: Any,
    ) -> None:
        """Validate execution contracts before lifecycle side effects."""
        if ctx is not None and not isinstance(ctx, ExecutionContext):
            raise TypeError(
                f"ctx must be an ExecutionContext, got {type(ctx).__name__}"
            )

        if not isinstance(initial_vars, Mapping):
            raise TypeError(
                f"initial_vars must be a mapping, got {type(initial_vars).__name__}"
            )

        self._validate_workflow_definition(workflow)

    def _validate_workflow_definition(self, workflow: Any) -> None:
        """Validate supported workflow shapes and definition invariants."""
        if isinstance(workflow, DAG):
            workflow.validate()
            return

        if isinstance(workflow, StepDefinition):
            return

        if isinstance(workflow, Pipeline):
            self._validate_pipeline_definition(workflow)
            return

        if isinstance(workflow, list):
            for index, step_def in enumerate(workflow):
                if not isinstance(step_def, StepDefinition):
                    raise TypeError(
                        "workflow step list items must be StepDefinition "
                        f"instances; item {index} is {type(step_def).__name__}"
                    )
            return

        raise TypeError(
            "workflow must be a StepDefinition, Pipeline, DAG, or list of "
            f"StepDefinition instances, got {type(workflow).__name__}"
        )

    def _validate_pipeline_definition(self, pipeline: Pipeline) -> None:
        """Validate pipeline elements before runtime execution."""
        if not pipeline.elements:
            raise ValueError(f"Pipeline '{pipeline.name}' has no elements")

        for index, element in enumerate(pipeline.elements):
            self._validate_pipeline_element(element, f"Pipeline element {index}")

        if pipeline.total_steps() == 0:
            raise ValueError(f"Pipeline '{pipeline.name}' has no executable steps")

    def _validate_pipeline_element(self, element: Any, path: str) -> None:
        """Validate a Pipeline element and nested child elements."""
        if isinstance(element, StepDefinition):
            return

        if isinstance(element, ParallelGroup):
            if not element.steps:
                raise ValueError(f"{path} parallel group has no steps")
            for index, step_def in enumerate(element.steps):
                if not isinstance(step_def, StepDefinition):
                    raise TypeError(
                        f"{path} parallel step {index} must be StepDefinition, "
                        f"got {type(step_def).__name__}"
                    )
            return

        if isinstance(element, ConditionalBranch):
            if not callable(element.condition):
                raise TypeError(f"{path} branch condition must be callable")
            if not isinstance(element.then_steps, list):
                raise TypeError(f"{path} then_steps must be a list")
            if not isinstance(element.else_steps, list):
                raise TypeError(f"{path} else_steps must be a list")

            for index, child in enumerate(element.then_steps):
                self._validate_pipeline_element(child, f"{path}.then[{index}]")
            for index, child in enumerate(element.else_steps):
                self._validate_pipeline_element(child, f"{path}.else[{index}]")
            return

        raise TypeError(
            f"{path} must be a Pipeline element, got {type(element).__name__}"
        )

    @property
    def history(self) -> ExecutionHistory:
        """Get execution history."""
        return self._history

    @property
    def current_context(self) -> ExecutionContext | None:
        """Get current execution context."""
        return self._current_ctx


# Global executor instance
_executor: WorkflowExecutor | None = None


def get_executor() -> WorkflowExecutor:
    """Get or create global executor."""
    global _executor
    if _executor is None:
        _executor = WorkflowExecutor()
    return _executor


def reset_executor() -> None:
    """Reset global executor (for testing)."""
    global _executor
    _executor = None


# Convenience functions
async def execute(
    workflow: StepDefinition | Pipeline | DAG | list[StepDefinition],
    **initial_vars: Any,
) -> WorkflowResult:
    """Execute a workflow with the global executor."""
    return await get_executor().execute(workflow, initial_vars=initial_vars)


async def run(step_def: StepDefinition, **initial_vars: Any) -> StepResult:
    """Run a single step and return its result."""
    result = await execute(step_def, **initial_vars)
    if result.steps:
        return result.steps[0]
    return StepResult(
        step_name=step_def.name, status=StepStatus.FAILED, error="No step result"
    )
