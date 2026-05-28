"""Step definition and execution."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable, TypeVar

if TYPE_CHECKING:
    from ..contracts.verification import VerificationPolicy

from ..contracts import ReviewStatus, StepResult, StepStatus
from ..models import ModelTier
from .context import ExecutionContext

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryStrategy(str, Enum):
    """Retry backoff strategies."""

    NONE = "none"
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"


@dataclass
class RetryConfig:
    """Configuration for step retry behaviour."""

    max_retries: int = 3
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    jitter: float = 0.1

    retry_on: tuple[type[Exception], ...] = (Exception,)
    no_retry_on: tuple[type[Exception], ...] = ()

    def get_delay(self, attempt: int) -> float:
        """Calculate backoff delay for attempt (1-indexed, with jitter)."""
        import random

        if self.strategy == RetryStrategy.NONE:
            return 0
        elif self.strategy == RetryStrategy.FIXED:
            base = self.base_delay_seconds
        elif self.strategy == RetryStrategy.LINEAR:
            base = self.base_delay_seconds * attempt
        else:  # EXPONENTIAL
            base = self.base_delay_seconds * (2 ** (attempt - 1))

        # Apply cap
        delay = min(base, self.max_delay_seconds)

        # Apply jitter
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)

        return max(0, delay)

    def should_retry(self, error: Exception) -> bool:
        """Check if error should trigger a retry (no_retry_on has priority)."""
        if isinstance(error, self.no_retry_on):
            return False
        return isinstance(error, self.retry_on)


# Type for step functions
StepFunction = Callable[[ExecutionContext], Awaitable[dict[str, Any]]]
HookFunction = Callable[[ExecutionContext, "StepDefinition"], Awaitable[None]]
ConditionFunction = Callable[[ExecutionContext], bool]


@dataclass
class StepDefinition:
    """Declarative step definition for workflow DAGs with fluent builder API."""

    name: str
    description: str = ""

    # Execution
    func: StepFunction | None = None
    tier: ModelTier = ModelTier.TIER_0
    timeout_seconds: float | None = None

    # Retry configuration
    retry: RetryConfig = field(default_factory=RetryConfig)

    # Conditions
    when: ConditionFunction | None = None  # Run only if True
    unless: ConditionFunction | None = None  # Skip if True

    # Loop control (R5)
    # When set, the step re-executes until this expression evaluates to True,
    # or until loop_max iterations have been reached.
    # Example YAML:  loop_until: "${review_report.overall_status} in ['APPROVED']"
    loop_until: str | None = None
    loop_max: int = 3

    # Dependencies
    depends_on: list[str] = field(default_factory=list)

    # I/O mapping
    input_mapping: dict[str, Any] = field(
        default_factory=dict
    )  # step_input -> context_var
    output_mapping: dict[str, str] = field(
        default_factory=dict
    )  # step_output -> context_var

    # Hooks
    pre_hooks: list[HookFunction] = field(default_factory=list)
    post_hooks: list[HookFunction] = field(default_factory=list)
    error_hooks: list[HookFunction] = field(default_factory=list)

    # Verification policy (optional)
    verify: VerificationPolicy | None = None

    # Metadata
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def should_run(self, ctx: ExecutionContext) -> bool:
        """Check if step is eligible to run (dependencies met, when/unless
        satisfied)."""
        # Check dependencies
        for dep in self.depends_on:
            if not ctx.is_step_complete(dep):
                return False
            if ctx.is_step_failed(dep):
                return False

        # Check when condition
        if self.when is not None and not self.when(ctx):
            return False

        # Check unless condition
        if self.unless is not None and self.unless(ctx):
            return False

        return True

    def with_retry(
        self,
        max_retries: int = 3,
        strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
        base_delay: float = 1.0,
    ) -> "StepDefinition":
        """Fluent builder: Configure retry."""
        self.retry = RetryConfig(
            max_retries=max_retries, strategy=strategy, base_delay_seconds=base_delay
        )
        return self

    def with_timeout(self, seconds: float) -> "StepDefinition":
        """Fluent builder: Set timeout."""
        self.timeout_seconds = seconds
        return self

    def with_dependency(self, *step_names: str) -> "StepDefinition":
        """Fluent builder: Add dependencies."""
        self.depends_on.extend(step_names)
        return self

    def with_input(self, **mapping: str) -> "StepDefinition":
        """Fluent builder: Map context variables to step inputs."""
        self.input_mapping.update(mapping)
        return self

    def with_output(self, **mapping: str) -> "StepDefinition":
        """Fluent builder: Map step outputs to context variables."""
        self.output_mapping.update(mapping)
        return self

    def with_pre_hook(self, hook: HookFunction) -> "StepDefinition":
        """Fluent builder: Add pre-execution hook."""
        self.pre_hooks.append(hook)
        return self

    def with_post_hook(self, hook: HookFunction) -> "StepDefinition":
        """Fluent builder: Add post-execution hook."""
        self.post_hooks.append(hook)
        return self

    def with_verify(self, policy: VerificationPolicy) -> StepDefinition:
        """Fluent builder: Set verification policy for self-correction loops."""
        self.verify = policy
        return self


def step(
    name: str,
    description: str = "",
    tier: ModelTier = ModelTier.TIER_0,
    timeout: float | None = None,
    depends_on: list[str] | None = None,
    retry: RetryConfig | None = None,
) -> Callable[[StepFunction], StepDefinition]:
    """Decorator to define a step from an async function."""

    def decorator(func: StepFunction) -> StepDefinition:
        return StepDefinition(
            name=name,
            description=description or func.__doc__ or "",
            func=func,
            tier=tier,
            timeout_seconds=timeout,
            depends_on=depends_on or [],
            retry=retry or RetryConfig(),
        )

    return decorator


class StepExecutor:
    """Executes StepDefinition instances with full lifecycle management."""

    def __init__(self):
        self._running_tasks: dict[str, asyncio.Task] = {}

    async def execute(
        self, step_def: StepDefinition, ctx: ExecutionContext
    ) -> StepResult:
        """Execute a step through the full lifecycle pipeline."""
        result = StepResult(
            step_name=step_def.name,
            status=StepStatus.PENDING,
            tier=(
                step_def.tier.value
                if isinstance(step_def.tier, ModelTier)
                else step_def.tier
            ),
        )

        # Check conditions
        if not step_def.should_run(ctx):
            result.status = StepStatus.SKIPPED
            result.metadata["skip_reason"] = "conditions not met"
            return result

        # Validate function exists
        if step_def.func is None:
            result.status = StepStatus.FAILED
            result.error = "No function defined for step"
            return result

        # Mark step as running
        result.status = StepStatus.RUNNING
        await ctx.mark_step_start(step_def.name)

        # Run pre-hooks
        try:
            for hook in step_def.pre_hooks:
                await hook(ctx, step_def)
        except Exception as e:
            result.status = StepStatus.FAILED
            result.error = f"Pre-hook failed: {e}"
            await ctx.mark_step_failed(step_def.name, result.error)
            return result

        # Prepare inputs
        child_ctx = ctx.child(step_def.name)
        mapped_inputs: dict[str, Any] = {}
        for step_input, ctx_var in step_def.input_mapping.items():
            value = self._resolve_input_mapping_value(ctx, ctx_var)
            mapped_inputs[step_input] = value
            await child_ctx.set(step_input, value)
        result.input_data = mapped_inputs

        # Execute with retry
        attempt = 0
        last_error: Exception | None = None

        while attempt <= step_def.retry.max_retries:
            attempt += 1
            result.retry_count = attempt - 1

            try:
                output = await self._execute_with_timeout(
                    step_def.func, child_ctx, step_def.timeout_seconds, step_def.name
                )

                # Success - map outputs
                result.status = StepStatus.SUCCESS
                result.output_data = output or {}

                # Extract _meta injected by LLM step for model tracking
                meta = result.output_data.pop("_meta", None)
                if isinstance(meta, dict):
                    result.model_used = meta.get("model_used")
                    if meta.get("tokens_used"):
                        result.metadata["tokens_used"] = meta["tokens_used"]

                # Safety-net: reviewer outputs sometimes arrive as raw_response
                # (e.g. fenced/truncated JSON). Ensure gating conditions can still
                # evaluate ${steps.<review>.outputs.review_report.overall_status}.
                if (
                    "review_report" in step_def.output_mapping
                    or step_def.name.startswith("review")
                ) and "review_report" not in result.output_data:
                    raw_text = str(result.output_data.get("raw_response", ""))
                    status_match = re.search(
                        r'"?overall_status"?\s*[:=]\s*"?([A-Za-z_ -]+)"?',
                        raw_text,
                        flags=re.IGNORECASE,
                    )
                    approved_match = re.search(
                        r'"?approved"?\s*[:=]\s*(true|false)',
                        raw_text,
                        flags=re.IGNORECASE,
                    )

                    if status_match:
                        raw_status = status_match.group(1).strip()
                    elif approved_match:
                        raw_status = (
                            "APPROVED"
                            if approved_match.group(1).lower() == "true"
                            else None
                        )
                    else:
                        raw_status = None  # normalize() defaults to NEEDS_FIXES

                    result.output_data["review_report"] = {
                        "overall_status": ReviewStatus.normalize(raw_status).value
                    }

                # Also normalize review_report.overall_status when it IS present
                if isinstance(result.output_data.get("review_report"), dict):
                    rr = result.output_data["review_report"]
                    if "overall_status" in rr:
                        rr["overall_status"] = ReviewStatus.normalize(
                            rr["overall_status"]
                        ).value

                for step_output, ctx_var in step_def.output_mapping.items():
                    if step_output in result.output_data:
                        await ctx.set(ctx_var, result.output_data[step_output])

                # Store step result in context for expression resolution
                # This enables ${steps.<name>.outputs.<key>} in when conditions
                step_view = {
                    "status": result.status.value,
                    "outputs": result.output_data,
                }
                # Store under a shared nested "steps" namespace so expressions
                # like ${steps.review_code.outputs.foo} resolve correctly.
                steps_state = ctx.get_sync("steps")
                if not isinstance(steps_state, dict):
                    steps_state = {}
                steps_state[step_def.name] = step_view
                ctx.set_sync("steps", steps_state)

                # Run post-hooks
                for hook in step_def.post_hooks:
                    await hook(ctx, step_def)

                # Run verification gate if configured
                if step_def.verify is not None and step_def.verify.enabled:
                    from .verification import (
                        VerificationGate,
                    )
                    from .verification import VerificationStatus as VStatus

                    gate = VerificationGate()
                    v_status, failing = await gate.run_checks(
                        step_def.verify.verification_commands,
                        stop_on_first_failure=step_def.verify.stop_on_first_failure,
                    )
                    result.metadata["verification_status"] = v_status.value
                    if failing:
                        result.metadata["verification_failing_checks"] = list(failing)
                    if v_status != VStatus.PASSED:
                        strategy = step_def.verify.escalation_strategy
                        if strategy == "block":
                            result.status = StepStatus.FAILED
                            result.error = f"Verification failed: {', '.join(failing)}"
                            await ctx.mark_step_failed(step_def.name, result.error)
                            return result
                        # "report" and "ask" just log and continue
                        logger.warning(
                            "Verification failed for step %r (strategy=%s): %s",
                            step_def.name,
                            strategy,
                            ", ".join(failing),
                        )

                # Loop-until logic (R5): re-execute until condition is satisfied
                if step_def.loop_until:
                    loop_iteration = result.metadata.get("loop_iteration", 1)
                    if loop_iteration < step_def.loop_max:
                        from .expressions import ExpressionEvaluator

                        satisfied = ExpressionEvaluator(ctx, {}).evaluate(
                            step_def.loop_until
                        )
                        if not satisfied:
                            result.metadata["loop_iteration"] = loop_iteration + 1
                            result.status = StepStatus.RUNNING
                            result.retry_count = 0
                            continue  # re-run the step body

                    result.metadata.setdefault("loop_iteration", loop_iteration)

                await ctx.mark_step_complete(step_def.name)
                break

            except asyncio.CancelledError:
                result.status = StepStatus.FAILED
                result.error = "Step was cancelled"
                result.error_type = "CancelledError"
                await ctx.mark_step_failed(step_def.name, result.error)
                break

            except TimeoutError:
                result.status = StepStatus.FAILED
                result.error = f"Step timed out after {step_def.timeout_seconds}s"
                result.error_type = "TimeoutError"
                last_error = TimeoutError(result.error)

                # Timeout typically shouldn't retry
                await ctx.mark_step_failed(step_def.name, result.error)
                break

            except Exception as e:
                last_error = e
                result.error = str(e)
                result.error_type = type(e).__name__

                # Check if should retry
                if (
                    attempt <= step_def.retry.max_retries
                    and step_def.retry.should_retry(e)
                ):
                    result.status = StepStatus.RETRYING
                    delay = step_def.retry.get_delay(attempt)
                    result.metadata[f"retry_{attempt}_delay"] = delay
                    await asyncio.sleep(delay)
                    continue

                # Run error hooks
                for hook in step_def.error_hooks:
                    try:
                        await hook(ctx, step_def)
                    except Exception:
                        pass  # Don't fail on error hook failure

                result.status = StepStatus.FAILED
                await ctx.mark_step_failed(step_def.name, result.error)
                break

        result.mark_complete(result.status == StepStatus.SUCCESS, result.error)
        return result

    async def _execute_with_timeout(
        self,
        func: StepFunction,
        ctx: ExecutionContext,
        timeout: float | None,
        step_name: str,
    ) -> dict[str, Any]:
        """Execute func with optional timeout and task tracking."""
        task = asyncio.create_task(func(ctx))
        self._running_tasks[step_name] = task

        try:
            if timeout:
                return await asyncio.wait_for(task, timeout=timeout)
            else:
                return await task
        finally:
            self._running_tasks.pop(step_name, None)

    async def cancel(self, step_name: str) -> bool:
        """Cancel a running step by name (returns True if found and cancelled)."""
        task = self._running_tasks.get(step_name)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def cancel_all(self) -> int:
        """Cancel all running steps (returns count of cancelled tasks)."""
        count = 0
        for name in list(self._running_tasks.keys()):
            if await self.cancel(name):
                count += 1
        return count

    @staticmethod
    def _resolve_input_mapping_value(ctx: ExecutionContext, mapping_value: Any) -> Any:
        """Resolve input mapping value from context or expression."""
        if not isinstance(mapping_value, str):
            return mapping_value

        expr = mapping_value.strip()
        if expr.startswith("${") and expr.endswith("}"):
            from .expressions import ExpressionEvaluator

            return ExpressionEvaluator(ctx).resolve_variable(expr[2:-1].strip())

        return ctx.get_sync(mapping_value)


# Convenience function for simple step execution
async def run_step(
    step_def: StepDefinition, ctx: ExecutionContext | None = None
) -> StepResult:
    """Run a single step with optional context."""
    from .context import get_context

    if ctx is None:
        ctx = get_context()

    executor = StepExecutor()
    return await executor.execute(step_def, ctx)
