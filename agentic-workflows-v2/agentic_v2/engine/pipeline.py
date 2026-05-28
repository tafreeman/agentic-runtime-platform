"""Pipeline orchestration for multi-step workflows.

Complements the DAG executor with a **linear-first** execution model
that optionally supports parallel groups and conditional branches:

- :class:`Pipeline` — an ordered sequence of :class:`PipelineElement`
  items (steps, parallel groups, conditional branches).
- :class:`PipelineExecutor` — walks elements sequentially, expanding
  parallel groups with ``asyncio.gather`` and conditional branches
  via predicate functions.
- :class:`PipelineBuilder` — fluent API for constructing pipelines.

Key differences from DAG execution:
- Pipelines enforce *element order*; DAGs derive order from dependencies.
- Pipelines support *conditional branches*; DAGs only have ``when`` guards.
- Pipelines support *checkpointing at intervals*; DAGs do not (yet).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

from ..contracts import StepResult, StepStatus, WorkflowResult
from .context import ExecutionContext
from .step import StepDefinition, StepExecutor


class PipelineStatus(str, Enum):
    """Pipeline execution status."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


ProgressCallback = Callable[[str, int, int, StepResult], None]


@dataclass
class ParallelGroup:
    """A group of steps to execute in parallel.

    All steps in the group run concurrently. Group completes when all
    steps complete (or any fails in fail-fast mode).
    """

    name: str
    steps: list[StepDefinition]
    fail_fast: bool = True  # Stop on first failure
    max_concurrency: int | None = None  # Limit parallel execution

    def __post_init__(self):
        if not self.steps:
            raise ValueError("ParallelGroup must have at least one step")


@dataclass
class ConditionalBranch:
    """Conditional branching in pipeline.

    Executes 'then_steps' if condition is True, else 'else_steps'.
    """

    name: str
    condition: Callable[[ExecutionContext], bool]
    then_steps: list[StepDefinition | "ParallelGroup" | "ConditionalBranch"]
    else_steps: list[StepDefinition | "ParallelGroup" | "ConditionalBranch"] = field(
        default_factory=list
    )


# Pipeline element type
PipelineElement = StepDefinition | ParallelGroup | ConditionalBranch


@dataclass
class Pipeline:
    """Ordered sequence of pipeline elements (steps, groups, branches).

    Elements execute in declaration order.  Parallel groups expand
    concurrently within their position; conditional branches pick a
    path at runtime.  Supports fluent construction via ``add()``,
    ``add_step()``, ``add_parallel()``, and ``add_branch()``.

    Attributes:
        name: Human-readable pipeline identifier.
        description: Optional prose description.
        elements: Ordered list of steps, parallel groups, and branches.
        checkpoint_interval: Save a checkpoint every *N* completed steps
            (0 = disabled).
        fail_fast: Stop execution on the first step failure.
        tags: Freeform labels for filtering/grouping.
        metadata: Arbitrary key-value annotations.
    """

    name: str
    description: str = ""

    # Pipeline elements (steps, groups, branches)
    elements: list[PipelineElement] = field(default_factory=list)

    # Checkpointing
    checkpoint_interval: int = 0  # Checkpoint every N steps (0 = disabled)

    # Error handling
    fail_fast: bool = True  # Stop on first failure

    # Metadata
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, element: PipelineElement) -> "Pipeline":
        """Add an element to the pipeline."""
        self.elements.append(element)
        return self

    def add_step(self, step: StepDefinition) -> "Pipeline":
        """Add a single step."""
        return self.add(step)

    def add_parallel(
        self, *steps: StepDefinition, name: str | None = None, fail_fast: bool = True
    ) -> "Pipeline":
        """Add a parallel group of steps."""
        group = ParallelGroup(
            name=name or f"parallel_{len(self.elements)}",
            steps=list(steps),
            fail_fast=fail_fast,
        )
        return self.add(group)

    def add_branch(
        self,
        condition: Callable[[ExecutionContext], bool],
        then_steps: list[PipelineElement],
        else_steps: list[PipelineElement] | None = None,
        name: str | None = None,
    ) -> "Pipeline":
        """Add a conditional branch."""
        branch = ConditionalBranch(
            name=name or f"branch_{len(self.elements)}",
            condition=condition,
            then_steps=then_steps,
            else_steps=else_steps or [],
        )
        return self.add(branch)

    def total_steps(self) -> int:
        """Count total steps (including nested)."""

        def count_element(elem: PipelineElement) -> int:
            if isinstance(elem, StepDefinition):
                return 1
            elif isinstance(elem, ParallelGroup):
                return len(elem.steps)
            elif isinstance(elem, ConditionalBranch):
                then_count = sum(count_element(e) for e in elem.then_steps)
                else_count = sum(count_element(e) for e in elem.else_steps)
                return then_count + else_count
            return 0

        return sum(count_element(e) for e in self.elements)


class PipelineExecutor:
    """Executes :class:`Pipeline` definitions with full orchestration.

    Walks pipeline elements sequentially, delegating to:
    - :class:`StepExecutor` for individual steps.
    - ``asyncio.gather`` (or semaphore-bounded tasks) for parallel groups.
    - Predicate evaluation for conditional branches.

    Supports progress callbacks, periodic checkpointing, fail-fast
    cancellation, and external cancellation via :meth:`cancel`.
    """

    def __init__(self):
        self._step_executor = StepExecutor()
        self._status = PipelineStatus.PENDING
        self._cancelled = False
        self._progress_callback: ProgressCallback | None = None

    def on_progress(self, callback: ProgressCallback) -> None:
        """Set progress callback."""
        self._progress_callback = callback

    async def execute(
        self,
        workflow: Any,
        ctx: ExecutionContext | None = None,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Execute a pipeline.

        Args:
            workflow: Pipeline to execute.
            ctx: Optional execution context.
            on_update: Optional async callback for progress events.
            **kwargs: Reserved for future use.

        Returns:
            WorkflowResult with all step results.
        """
        if not isinstance(workflow, Pipeline):
            raise ValueError(
                f"PipelineExecutor expects a Pipeline, got {type(workflow).__name__}"
            )
        pipeline: Pipeline = workflow
        from .context import get_context

        if ctx is None:
            ctx = get_context()

        self._status = PipelineStatus.RUNNING
        self._cancelled = False

        result = WorkflowResult(
            workflow_id=ctx.workflow_id,
            workflow_name=pipeline.name,
            overall_status=StepStatus.RUNNING,
            metadata=pipeline.metadata.copy(),
        )

        completed_count = 0
        total_steps = pipeline.total_steps()
        checkpoint_counter = 0

        try:
            for element in pipeline.elements:
                if self._cancelled:
                    result.overall_status = StepStatus.FAILED
                    result.metadata["cancelled"] = True
                    break

                step_results = await self._execute_element(element, ctx)

                for step_result in step_results:
                    result.add_step(step_result)
                    completed_count += 1

                    # Progress callback
                    if self._progress_callback:
                        self._progress_callback(
                            step_result.step_name,
                            completed_count,
                            total_steps,
                            step_result,
                        )

                    # Check for failure
                    if step_result.is_failed and pipeline.fail_fast:
                        result.overall_status = StepStatus.FAILED
                        self._status = PipelineStatus.FAILED
                        result.mark_complete(success=False)
                        return result

                # Checkpointing
                if pipeline.checkpoint_interval > 0:
                    checkpoint_counter += len(step_results)
                    if checkpoint_counter >= pipeline.checkpoint_interval:
                        await ctx.save_checkpoint(f"pipeline_{completed_count}")
                        checkpoint_counter = 0

            # All elements completed
            if result.overall_status == StepStatus.RUNNING:
                result.overall_status = StepStatus.SUCCESS

            self._status = (
                PipelineStatus.SUCCESS
                if result.overall_status == StepStatus.SUCCESS
                else PipelineStatus.FAILED
            )

        except Exception as e:
            result.overall_status = StepStatus.FAILED
            result.metadata["error"] = str(e)
            self._status = PipelineStatus.FAILED

        result.mark_complete(result.overall_status == StepStatus.SUCCESS)
        return result

    async def _execute_element(
        self, element: PipelineElement, ctx: ExecutionContext
    ) -> list[StepResult]:
        """Execute a single pipeline element."""

        if isinstance(element, StepDefinition):
            result = await self._step_executor.execute(element, ctx)
            return [result]

        elif isinstance(element, ParallelGroup):
            return await self._execute_parallel_group(element, ctx)

        elif isinstance(element, ConditionalBranch):
            return await self._execute_branch(element, ctx)

        return []

    async def _execute_parallel_group(
        self, group: ParallelGroup, ctx: ExecutionContext
    ) -> list[StepResult]:
        """Execute steps in parallel."""

        if group.max_concurrency:
            # Limited concurrency with semaphore
            semaphore = asyncio.Semaphore(group.max_concurrency)

            async def run_with_semaphore(step: StepDefinition) -> StepResult:
                async with semaphore:
                    return await self._step_executor.execute(step, ctx)

            tasks = [run_with_semaphore(step) for step in group.steps]
        else:
            # Unlimited concurrency
            tasks = [self._step_executor.execute(step, ctx) for step in group.steps]

        if group.fail_fast:
            # Return on first failure
            results = []
            pending = set(
                asyncio.create_task(t) if not isinstance(t, asyncio.Task) else t
                for t in tasks
            )

            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )

                for task in done:
                    result = task.result()
                    results.append(result)

                    if result.is_failed:
                        # Cancel remaining tasks
                        for p in pending:
                            p.cancel()
                        return results

            return results
        else:
            # Wait for all
            return await asyncio.gather(*tasks)

    async def _execute_branch(
        self, branch: ConditionalBranch, ctx: ExecutionContext
    ) -> list[StepResult]:
        """Execute conditional branch."""

        condition_result = branch.condition(ctx)
        steps_to_run = branch.then_steps if condition_result else branch.else_steps

        results = []
        for element in steps_to_run:
            element_results = await self._execute_element(element, ctx)
            results.extend(element_results)

            # Check for failure (respect parent pipeline's fail_fast)
            if any(r.is_failed for r in element_results):
                break

        return results

    async def cancel(self) -> None:
        """Cancel pipeline execution."""
        self._cancelled = True
        self._status = PipelineStatus.CANCELLED
        await self._step_executor.cancel_all()

    @property
    def status(self) -> PipelineStatus:
        """Get current pipeline status."""
        return self._status


# Builder for creating pipelines fluently
class PipelineBuilder:
    """Fluent builder for pipelines.

    Usage:
        pipeline = (
            PipelineBuilder("my-pipeline")
            .step(step1)
            .parallel(step2, step3)
            .branch(
                lambda ctx: ctx.get_sync("should_review"),
                then_steps=[review_step],
                else_steps=[skip_step]
            )
            .build()
        )
    """

    def __init__(self, name: str, description: str = ""):
        self._pipeline = Pipeline(name=name, description=description)

    def step(self, step_def: StepDefinition) -> "PipelineBuilder":
        """Add a step."""
        self._pipeline.add_step(step_def)
        return self

    def parallel(
        self, *steps: StepDefinition, name: str | None = None, fail_fast: bool = True
    ) -> "PipelineBuilder":
        """Add parallel steps."""
        self._pipeline.add_parallel(*steps, name=name, fail_fast=fail_fast)
        return self

    def branch(
        self,
        condition: Callable[[ExecutionContext], bool],
        then_steps: list[PipelineElement],
        else_steps: list[PipelineElement] | None = None,
        name: str | None = None,
    ) -> "PipelineBuilder":
        """Add a conditional branch."""
        self._pipeline.add_branch(condition, then_steps, else_steps, name)
        return self

    def with_checkpoints(self, interval: int) -> "PipelineBuilder":
        """Enable checkpointing."""
        self._pipeline.checkpoint_interval = interval
        return self

    def fail_fast(self, enabled: bool = True) -> "PipelineBuilder":
        """Set fail-fast behavior."""
        self._pipeline.fail_fast = enabled
        return self

    def tag(self, *tags: str) -> "PipelineBuilder":
        """Add tags."""
        self._pipeline.tags.extend(tags)
        return self

    def build(self) -> Pipeline:
        """Build the pipeline."""
        return self._pipeline


# Convenience function
async def run_pipeline(
    pipeline: Pipeline,
    ctx: ExecutionContext | None = None,
    progress_callback: ProgressCallback | None = None,
) -> WorkflowResult:
    """Run a pipeline with optional context and progress callback."""
    executor = PipelineExecutor()
    if progress_callback:
        executor.on_progress(progress_callback)
    return await executor.execute(pipeline, ctx)
