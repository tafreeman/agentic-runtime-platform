"""Result construction helpers for the LangChain workflow runner.

Bridges between LangGraph execution state and the contract types
(``StepResult``, ``WorkflowResult``) used throughout the rest of the
system.  All functions are pure transformations — they do not mutate
their arguments.

Public API
----------
steps_dict_to_list
    Convert a LangGraph step mapping to an ordered list of
    ``StepResult`` objects.
build_workflow_result
    Construct a canonical ``WorkflowResult`` from execution data.
extract_metadata
    Extract per-step token counts and model identifiers from final
    workflow state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..contracts import StepResult, WorkflowResult
from ..contracts.result_conversion import build_step_results, workflow_status
from ..contracts.result_conversion import extract_metadata as extract_metadata


def steps_dict_to_list(
    steps_dict: dict[str, dict],
    token_counts: dict[str, dict] | None = None,
    models_used: dict[str, str] | None = None,
) -> list[StepResult]:
    """Convert raw steps using the same evidence rules as API and persistence."""
    return build_step_results(
        steps_dict, token_counts=token_counts, models_used=models_used
    )


def build_workflow_result(
    *,
    workflow_name: str,
    run_id: str,
    started_at: datetime,
    elapsed_seconds: float,
    final_state: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    steps: list[StepResult] | None = None,
    errors: list[str] | None = None,
    token_counts: dict[str, dict] | None = None,
    models_used: dict[str, str] | None = None,
    failed: bool = False,
) -> WorkflowResult:
    """Construct a canonical ``WorkflowResult`` from LangGraph execution state.

    Bridges between the LangGraph runner's internal data and the
    contract type used throughout the rest of the system.

    Args:
        workflow_name: Name of the workflow being executed.
        run_id: Unique identifier for this execution run.
        started_at: UTC timestamp when execution began.
        elapsed_seconds: Wall-clock duration of the execution.
        final_state: Raw LangGraph state dict after execution completes.
        outputs: Resolved declared outputs from the workflow config.
        steps: Ordered list of step results; defaults to an empty list.
        errors: Any error messages collected during execution.
        token_counts: Per-step token usage mapping.
        models_used: Per-step model identifier mapping.
        failed: Force overall status to FAILED when ``True``.

    Returns:
        A populated ``WorkflowResult`` contract object.
    """
    errors = errors or []
    overall_status = workflow_status(steps or [], has_errors=failed or bool(errors))

    ended_at = started_at + timedelta(seconds=elapsed_seconds)

    metadata: dict[str, Any] = {
        "elapsed_seconds": elapsed_seconds,
    }
    if token_counts:
        metadata["token_counts"] = token_counts
    if models_used:
        metadata["models_used"] = models_used
    if final_state is not None:
        metadata["final_state"] = final_state
    if errors:
        metadata["errors"] = errors

    return WorkflowResult(
        workflow_id=run_id,
        workflow_name=workflow_name,
        steps=steps or [],
        overall_status=overall_status,
        start_time=started_at,
        end_time=ended_at,
        final_output=outputs or {},
        metadata=metadata,
    )
