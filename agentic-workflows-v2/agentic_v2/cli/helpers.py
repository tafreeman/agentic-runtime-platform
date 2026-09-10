"""CLI helper functions for adapter comparison.

Extracted from ``main.py`` to keep the command module under 800 lines.
These functions encapsulate the business logic called by the Typer
command handlers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..contracts import WorkflowResult

logger = logging.getLogger(__name__)


@dataclass
class _NormalizedResult:
    """Lightweight result object shaped for CLI display.

    Both adapters' ``execute()``/``run()`` already return a contract
    :class:`~agentic_v2.contracts.WorkflowResult`; this reshapes its typed
    fields (``StepResult`` list, enum status, ...) into the plain
    dict/str/float attributes that ``_show_results`` and the output-file
    block in ``main.py`` display.
    """

    workflow_name: str
    status: str
    steps: dict[str, Any]
    outputs: dict[str, Any]
    errors: list[str]
    elapsed_seconds: float


# ---------------------------------------------------------------------------
# Private normalisation helpers
# ---------------------------------------------------------------------------


def _collect_errors(result: WorkflowResult) -> list[str]:
    """Gather error strings from failed steps and result metadata.

    Returns:
        Deduplicated list of non-empty error strings.
    """
    errors = [step.error for step in result.steps if step.error]

    meta_errors = result.metadata.get("errors")
    if isinstance(meta_errors, list):
        errors.extend(str(e) for e in meta_errors if e)

    return list(dict.fromkeys(str(e) for e in errors))


def _normalize_result(
    workflow_name: str,
    result: WorkflowResult,
    wall_clock: float,
) -> _NormalizedResult:
    """Reshape a contract WorkflowResult into the CLI's display dataclass."""
    duration_ms = result.total_duration_ms
    elapsed_seconds = duration_ms / 1000.0 if duration_ms else wall_clock

    return _NormalizedResult(
        workflow_name=result.workflow_name or workflow_name,
        status=result.overall_status.value,
        steps={
            step.step_name: {
                "status": step.status.value,
                "outputs": step.output_data,
                "error": step.error,
            }
            for step in result.steps
        },
        outputs=result.final_output,
        errors=_collect_errors(result),
        elapsed_seconds=round(elapsed_seconds, 3),
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _run_via_adapter(
    adapter_name: str,
    workflow_name: str,
    input_data: dict[str, Any],
) -> _NormalizedResult:
    """Execute a workflow through the named adapter and return a normalised result.

    Loads the workflow definition via
    :class:`~agentic_v2.workflows.loader.WorkflowLoader`, builds an
    :class:`~agentic_v2.engine.context.ExecutionContext` from *input_data*,
    and calls ``engine.execute(dag, ctx)``.  The raw
    :class:`~agentic_v2.contracts.WorkflowResult` is then normalised into a
    :class:`_NormalizedResult` so the CLI display helpers can consume it
    without knowing about the adapter's internal result shape.

    Args:
        adapter_name: Registered adapter name (e.g. ``"native"``).
        workflow_name: Workflow definition name.
        input_data: Input variables for the workflow.

    Returns:
        A :class:`_NormalizedResult` with ``status``, ``steps``, ``outputs``,
        ``errors``, and ``elapsed_seconds`` attributes.

    Raises:
        AdapterNotFoundError: If *adapter_name* is not registered.
        WorkflowLoadError: If the workflow definition cannot be found.
    """
    from ..adapters import get_registry
    from ..engine.context import ExecutionContext
    from ..workflows.loader import WorkflowLoader
    from ..workflows.runner import (
        resolve_workflow_outputs,
        seed_workflow_inputs,
        validate_workflow_inputs,
    )

    loader = WorkflowLoader()
    workflow_def = loader.load(workflow_name)
    dag = workflow_def.dag
    validated = validate_workflow_inputs(workflow_def, input_data)
    ctx = ExecutionContext(workflow_id=f"wf-{workflow_name}")
    seed_workflow_inputs(ctx, validated)

    engine = get_registry().get_adapter(adapter_name)

    start = time.perf_counter()
    result = asyncio.run(engine.execute(dag, ctx))
    wall_clock = time.perf_counter() - start
    result.final_output = resolve_workflow_outputs(workflow_def, ctx, result)
    result.workflow_name = workflow_def.name
    return _normalize_result(workflow_name, result, wall_clock)


def _summarize_for_compare(result: _NormalizedResult) -> dict[str, Any]:
    """Reduce a normalised result to the summary row the compare table shows."""
    return {
        "status": result.status,
        "step_count": len(result.steps),
        "elapsed": round(result.elapsed_seconds, 2),
    }


def _run_adapter(
    adapter_name: str,
    workflow_name: str,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    """Run a workflow through a specific adapter and return summary metrics.

    Each adapter takes a different ``workflow`` argument: the LangChain
    adapter resolves a workflow *name* itself, while the native engine
    needs an already-loaded :class:`~agentic_v2.engine.dag.DAG` plus an
    :class:`~agentic_v2.engine.context.ExecutionContext`.  Non-LangChain
    adapters therefore go through :func:`_run_via_adapter`, which performs
    that resolution; passing the bare name straight to the native engine
    makes it raise ``TypeError`` and report a spurious ``failed`` row.
    Both branches call through the same :class:`AdapterRegistry` lookup
    above — the split is only in what shape ``execute()`` needs per
    engine, which ``ExecutionEngine``'s protocol intentionally leaves
    engine-specific (see ``core/protocols.py``).

    Args:
        adapter_name: Registered adapter name (e.g. ``"native"``, ``"langchain"``).
        workflow_name: Workflow definition name.
        input_data: Input variables for the workflow.

    Returns:
        Dict with ``status``, ``step_count``, and ``elapsed`` keys.  A
        ``status`` of ``"failed"`` with zero steps is returned when the
        adapter raises during execution, so callers must treat that row as
        a failure.

    Raises:
        AdapterNotFoundError: If *adapter_name* is not registered.
    """
    from ..adapters import get_registry

    # Resolved outside the try below: an unregistered adapter name is a
    # user error (usually a typo) and should surface with the registry's
    # "Available: ..." hint rather than be flattened into a failed row.
    engine = get_registry().get_adapter(adapter_name)

    start = time.perf_counter()
    try:
        if adapter_name == "langchain":
            raw_result = asyncio.run(engine.execute(workflow_name, **input_data))
            wall_clock = time.perf_counter() - start
            normalized = _normalize_result(workflow_name, raw_result, wall_clock)
        else:
            normalized = _run_via_adapter(adapter_name, workflow_name, input_data)
        return _summarize_for_compare(normalized)
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.debug("Adapter %s failed: %s", adapter_name, exc)
        return {
            "status": "failed",
            "step_count": 0,
            "elapsed": round(elapsed, 2),
        }
