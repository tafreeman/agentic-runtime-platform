"""Workflow runner — unified entry point for YAML workflows.

Usage:
    runner = WorkflowRunner()
    result = await runner.run("code_review", code_file="main.py")

Combines:
- WorkflowLoader: YAML → WorkflowDefinition (DAG + inputs/outputs)
- DAGExecutor: dynamic parallel execution
- ExpressionEvaluator: runtime ${...} variable resolution
- Output resolution: map final context to declared outputs
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from ..contracts import WorkflowResult
from ..engine.context import ExecutionContext
from ..engine.dag_executor import DAGExecutor
from ..engine.expressions import ExpressionEvaluator
from ..engine.runtime import IsolatedTaskRuntime, create_runtime
from ..engine.step import StepExecutor
from ..integrations.base import TraceAdapter
from ..integrations.tracing import NullTraceAdapter
from .artifact_extractor import extract_artifacts
from .loader import WorkflowDefinition, WorkflowLoader
from .run_logger import RunLogger

logger = logging.getLogger(__name__)


class WorkflowValidationError(ValueError):
    """Raised when workflow inputs fail validation."""

    def __init__(self, workflow: str, errors: list[str]):
        """Initialize with the workflow name and list of validation errors."""
        msg = f"Validation failed for workflow '{workflow}': " + "; ".join(errors)
        super().__init__(msg)
        self.workflow = workflow
        self.errors = errors


def validate_workflow_inputs(
    definition: WorkflowDefinition,
    supplied: dict[str, Any],
) -> dict[str, Any]:
    """Validate supplied values and apply defaults from a workflow definition."""
    validated: dict[str, Any] = {}
    errors: list[str] = []

    for name, input_def in definition.inputs.items():
        if name in supplied:
            value = supplied[name]
            if input_def.required and isinstance(value, str) and not value.strip():
                errors.append(f"Required input '{name}' must not be empty")
                continue
            if input_def.enum and value not in input_def.enum:
                errors.append(
                    f"Input '{name}' must be one of {input_def.enum}, got '{value}'"
                )
            validated[name] = value
        elif input_def.default is not None:
            validated[name] = input_def.default
        elif input_def.required:
            errors.append(f"Missing required input '{name}'")

    if errors:
        raise WorkflowValidationError(definition.name, errors)

    return validated


def seed_workflow_inputs(
    ctx: ExecutionContext,
    validated: Mapping[str, Any],
) -> None:
    """Seed validated values under the namespace used by shipped YAML files."""
    ctx.set_sync("inputs", dict(validated))


def _resolve_workflow_output_expr(
    evaluator: ExpressionEvaluator,
    from_expr: Any,
) -> Any:
    """Resolve a workflow output expression, including nested mappings/lists."""
    if isinstance(from_expr, str):
        expr = from_expr.strip()
        if expr.startswith("${") and expr.endswith("}"):
            expr = expr[2:-1].strip()
        return evaluator.resolve_variable(expr)

    if isinstance(from_expr, dict):
        return {
            key: _resolve_workflow_output_expr(evaluator, value)
            for key, value in from_expr.items()
        }

    if isinstance(from_expr, list):
        return [_resolve_workflow_output_expr(evaluator, item) for item in from_expr]

    return from_expr


def resolve_workflow_outputs(
    definition: WorkflowDefinition,
    ctx: ExecutionContext,
    result: WorkflowResult,
) -> dict[str, Any]:
    """Resolve a workflow's declared outputs from its completed native context."""
    outputs: dict[str, Any] = {}
    unresolved_required_outputs: list[str] = []
    step_results = {step.step_name: step for step in result.steps}
    evaluator = ExpressionEvaluator(ctx, step_results)

    for name, output_def in definition.outputs.items():
        from_expr = output_def.from_expr
        if from_expr in ("", None):
            continue

        try:
            value = _resolve_workflow_output_expr(evaluator, from_expr)
            outputs[name] = value
            if value is None and not output_def.optional:
                unresolved_required_outputs.append(name)
                logger.warning(
                    "Required output '%s' resolved to None from '%s'",
                    name,
                    from_expr,
                )
        except Exception:
            if not output_def.optional:
                unresolved_required_outputs.append(name)
                logger.warning(
                    "Failed to resolve required output '%s' from '%s'",
                    name,
                    from_expr,
                )
            outputs[name] = None

    if unresolved_required_outputs:
        result.metadata["unresolved_required_outputs"] = sorted(
            set(unresolved_required_outputs)
        )
    else:
        result.metadata.pop("unresolved_required_outputs", None)

    return outputs


class WorkflowRunner:
    """Load, validate, execute, and resolve YAML workflows.

    This is the primary high-level API.  It orchestrates:
    1. Loading the YAML workflow (cached by default)
    2. Validating supplied inputs against the schema
    3. Seeding the ExecutionContext with validated inputs
    4. Running the DAG via DAGExecutor (max parallelism)
    5. Resolving declared workflow outputs from the final context
    """

    def __init__(
        self,
        definitions_dir: Path | None = None,
        step_executor: StepExecutor | None = None,
        max_concurrency: int = 10,
        run_logger: RunLogger | bool | None = None,
        execution_profile: Mapping[str, Any] | None = None,
        trace_adapter: TraceAdapter | None = None,
        extract_artifacts: bool = True,
        artifacts_dir: Path | None = None,
        adapter_name: str = "native",
    ):
        """Initialize the workflow runner.

        Args:
            definitions_dir: Directory containing YAML workflow files.
            step_executor: Custom step executor; a default is used if omitted.
            max_concurrency: Maximum number of steps that may run in parallel.
            run_logger: Run-log sink. ``True`` → auto-create, ``False``/``None`` → disabled.
            execution_profile: Default execution settings applied to every step.
            trace_adapter: Observability adapter; a no-op adapter is used if omitted.
            extract_artifacts: Whether to extract artifacts from the final state.
            artifacts_dir: Directory where artifacts are written.
            adapter_name: Registered adapter name for engine selection (default ``"native"``).
                Used only when *step_executor* is ``None``; see ``_execute_definition``.
        """
        self._loader = WorkflowLoader(definitions_dir=definitions_dir)
        self._step_executor = step_executor
        self._adapter_name = adapter_name
        self._max_concurrency = max_concurrency
        self._execution_profile = dict(execution_profile or {})
        # run_logger=True → auto-create with default dir; False/None → disabled
        if run_logger is True:
            self._run_logger: RunLogger | None = RunLogger()
        elif isinstance(run_logger, RunLogger):
            self._run_logger = run_logger
        else:
            self._run_logger = None
        # trace_adapter=None → use NullTraceAdapter (no-op)
        self._trace_adapter = (
            trace_adapter if trace_adapter is not None else NullTraceAdapter()
        )
        self._extract_artifacts = extract_artifacts
        self._artifacts_dir = artifacts_dir

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    async def run(
        self,
        workflow_name: str,
        ctx: ExecutionContext | None = None,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        dataset_meta: dict[str, Any] | None = None,
        execution_profile: Mapping[str, Any] | None = None,
        **inputs: Any,
    ) -> WorkflowResult:
        """Run a named workflow end-to-end.

        Args:
            workflow_name: Name of the YAML workflow (without extension).
            ctx: Optional pre-built context; one is created if omitted.
            on_update: Optional async callback for step/workflow events.
            dataset_meta: Optional dataset provenance for run logging.
            **inputs: Keyword arguments matching declared workflow inputs.

        Returns:
            WorkflowResult with step results, final outputs, and status.

        Raises:
            WorkflowLoadError: If the YAML file cannot be found/parsed.
            WorkflowValidationError: If required inputs are missing.
        """
        # 1. Load
        # Always reload at execution time so recent YAML edits (e.g. when/outputs)
        # are applied immediately and not masked by stale in-memory cache.
        definition = self._loader.load(workflow_name, use_cache=False)

        # 2. Validate inputs
        validated = self._validate_inputs(definition, inputs)

        # 3. Build context
        if ctx is None:
            ctx = ExecutionContext(workflow_id=f"wf-{workflow_name}")

        run_id = ctx.workflow_id

        # Emit workflow_start trace event
        self._trace_adapter.emit_workflow_start(workflow_name, run_id, validated)

        # Seed inputs into context as a top-level namespace for expression resolution.
        seed_workflow_inputs(ctx, validated)

        # Register sanitization middleware in DI container if available
        try:
            from ..middleware.sanitization import SanitizationMiddleware

            if ctx.services.resolve(SanitizationMiddleware) is None:
                ctx.services.register_singleton(
                    SanitizationMiddleware, SanitizationMiddleware.default()
                )
        except ImportError:
            pass  # Middleware not installed

        try:
            # 4. Execute DAG
            result, runtime_profile, runtime_artifacts = await self._execute_definition(
                definition,
                ctx,
                on_update=on_update,
                execution_profile=execution_profile,
            )

            # 5. Resolve outputs
            result.final_output = self._resolve_outputs(definition, ctx, result)
            result.workflow_name = definition.name
            result.metadata["execution_profile"] = runtime_profile
            result.metadata["runtime_artifacts"] = runtime_artifacts

            # 6. Extract artifacts to disk
            self._do_extract_artifacts(result)

            # 7. Log run
            self._log_run(result, dataset_meta=dataset_meta, workflow_inputs=validated)

            # Emit workflow_end trace event
            self._trace_adapter.emit_workflow_end(
                workflow_name, run_id, result.overall_status.value, result.final_output
            )

            return result
        except Exception as e:
            # Emit workflow_end with error status
            self._trace_adapter.emit_workflow_end(
                workflow_name, run_id, "error", {"error": str(e)}
            )
            raise

    async def run_definition(
        self,
        definition: WorkflowDefinition,
        ctx: ExecutionContext | None = None,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        dataset_meta: dict[str, Any] | None = None,
        execution_profile: Mapping[str, Any] | None = None,
        **inputs: Any,
    ) -> WorkflowResult:
        """Run a pre-loaded WorkflowDefinition (useful for testing)."""
        validated = self._validate_inputs(definition, inputs)

        if ctx is None:
            ctx = ExecutionContext(workflow_id=f"wf-{definition.name}")

        seed_workflow_inputs(ctx, validated)

        result, runtime_profile, runtime_artifacts = await self._execute_definition(
            definition,
            ctx,
            on_update=on_update,
            execution_profile=execution_profile,
        )

        result.final_output = self._resolve_outputs(definition, ctx, result)
        result.workflow_name = definition.name
        result.metadata["execution_profile"] = runtime_profile
        result.metadata["runtime_artifacts"] = runtime_artifacts

        self._do_extract_artifacts(result)
        self._log_run(result, dataset_meta=dataset_meta, workflow_inputs=validated)
        return result

    def list_workflows(self, include_experimental: bool = False) -> list[str]:
        """List available workflow names."""
        return self._loader.list_workflows(include_experimental=include_experimental)

    def _do_extract_artifacts(self, result: WorkflowResult) -> None:
        """Extract FILE blocks from step outputs to the artifacts directory."""
        if not self._extract_artifacts:
            return
        try:
            out_dir = extract_artifacts(result, artifacts_dir=self._artifacts_dir)
            if out_dir:
                result.metadata["artifacts_dir"] = str(out_dir)
        except Exception:
            logger.exception(
                "Artifact extraction failed for run %s", result.workflow_id
            )

    def _log_run(
        self,
        result: WorkflowResult,
        *,
        dataset_meta: dict[str, Any] | None = None,
        workflow_inputs: dict[str, Any] | None = None,
    ) -> None:
        """Log a run result if a RunLogger is configured."""
        if self._run_logger is None:
            return
        try:
            path = self._run_logger.log(
                result,
                dataset_meta=dataset_meta,
                workflow_inputs=workflow_inputs,
            )
            logger.info("Run logged to %s", path)
        except Exception:
            logger.exception("Failed to log run")

    async def _execute_definition(
        self,
        definition: WorkflowDefinition,
        ctx: ExecutionContext,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        execution_profile: Mapping[str, Any] | None = None,
    ) -> tuple[WorkflowResult, dict[str, Any], dict[str, Any]]:
        runtime_profile = self._resolve_execution_profile(execution_profile)
        runtime = create_runtime(runtime_profile)
        ctx.services.register_singleton(IsolatedTaskRuntime, runtime)
        ctx.metadata["execution_profile"] = runtime_profile

        try:
            await runtime.setup()
        except Exception:
            # Best effort cleanup if setup partially initialized resources.
            await runtime.cleanup()
            raise

        # Create trace-aware callback that emits step events and forwards to user callback
        async def trace_on_update(event: dict[str, Any]) -> None:
            event_type = event.get("type", "")
            run_id = event.get("run_id", "")
            step_name = event.get("step", "")

            if event_type == "step_start":
                self._trace_adapter.emit_step_start(
                    step_name=step_name,
                    run_id=run_id,
                    inputs=event.get("inputs", {}),
                )
            elif event_type == "step_end":
                self._trace_adapter.emit_step_complete(
                    step_name=step_name,
                    run_id=run_id,
                    status=event.get("status", "unknown"),
                    outputs=event.get("outputs", {}),
                )

            # Forward to user callback if provided
            if on_update:
                await on_update(event)

        # TODO(ADR-001): When a custom step_executor is provided we must
        # construct DAGExecutor directly because NativeEngine does not
        # accept a step_executor parameter and the registry returns a
        # shared singleton.  Full unification requires NativeEngine to
        # support per-call step_executor injection or a factory pattern.
        if self._step_executor is not None:
            executor = DAGExecutor(step_executor=self._step_executor)
        else:
            from ..adapters.registry import get_registry

            executor = get_registry().get_adapter(self._adapter_name)

        runtime_artifacts: dict[str, Any] = {}
        try:
            result = await executor.execute(
                definition.dag,
                ctx,
                max_concurrency=self._max_concurrency,
                on_update=trace_on_update,
            )
        finally:
            try:
                runtime_artifacts = await runtime.collect_artifacts()
            finally:
                await runtime.cleanup()

        return result, runtime_profile, runtime_artifacts

    def _resolve_execution_profile(
        self, override: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        profile = dict(self._execution_profile)
        if override:
            profile.update(dict(override))
        runtime_name = str(profile.get("runtime", "subprocess")).strip().lower()
        profile["runtime"] = runtime_name
        return profile

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _validate_inputs(
        self, definition: WorkflowDefinition, supplied: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate and apply defaults for workflow inputs."""
        return validate_workflow_inputs(definition, supplied)

    @staticmethod
    def _resolve_outputs(
        definition: WorkflowDefinition,
        ctx: ExecutionContext,
        result: WorkflowResult,
    ) -> dict[str, Any]:
        """Resolve declared outputs from the execution context."""
        return resolve_workflow_outputs(definition, ctx, result)

    @staticmethod
    def _resolve_output_expr(
        evaluator: ExpressionEvaluator,
        from_expr: Any,
    ) -> Any:
        """Resolve workflow output expressions from string/dict/list mappings."""
        return _resolve_workflow_output_expr(evaluator, from_expr)


# -------------------------------------------------------------------------
# Convenience function
# -------------------------------------------------------------------------


async def run_workflow(
    name: str,
    definitions_dir: Path | None = None,
    max_concurrency: int = 10,
    **inputs: Any,
) -> WorkflowResult:
    """One-liner to run a named workflow.

    Example:
        result = await run_workflow("code_review", code_file="main.py")
    """
    runner = WorkflowRunner(
        definitions_dir=definitions_dir, max_concurrency=max_concurrency
    )
    return await runner.run(name, **inputs)
