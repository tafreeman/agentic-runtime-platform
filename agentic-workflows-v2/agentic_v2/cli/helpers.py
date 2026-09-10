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
    """Load and execute using the selected adapter's workflow contract."""
    from ..adapters.workflows import execute_workflow, load_workflow

    definition = load_workflow(adapter_name, workflow_name)
    start = time.perf_counter()
    result = asyncio.run(execute_workflow(adapter_name, definition, input_data))
    return _normalize_result(workflow_name, result, time.perf_counter() - start)


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
    """Run a named workflow and reduce its typed result to comparison metrics.

    Unknown adapter names raise; execution failures produce a failed
    row.
    """
    from ..adapters import get_registry

    # Resolved outside the try below: an unregistered adapter name is a
    # user error (usually a typo) and should surface with the registry's
    # "Available: ..." hint rather than be flattened into a failed row.
    get_registry().get_adapter(adapter_name)

    start = time.perf_counter()
    try:
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
