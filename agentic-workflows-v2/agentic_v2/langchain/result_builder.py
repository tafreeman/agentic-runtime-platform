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

import logging
from datetime import datetime, timedelta
from typing import Any

from ..contracts import StepResult, StepStatus, WorkflowResult

logger = logging.getLogger(__name__)


def steps_dict_to_list(
    steps_dict: dict[str, dict],
    token_counts: dict[str, dict] | None = None,
    models_used: dict[str, str] | None = None,
) -> list[StepResult]:
    """Convert a LangGraph step mapping to an ordered list of ``StepResult`` objects.

    Args:
        steps_dict: Mapping of step name to step data from LangGraph state.
        token_counts: Per-step token counts extracted from metadata.
        models_used: Per-step model identifiers.

    Returns:
        Ordered list of ``StepResult`` Pydantic models.
    """
    token_counts = token_counts or {}
    models_used = models_used or {}
    results: list[StepResult] = []

    for step_name, step_data in steps_dict.items():
        if not isinstance(step_data, dict):
            continue

        raw_status = step_data.get("status", "success")
        if raw_status == "success":
            status = StepStatus.SUCCESS
        elif raw_status in ("failed", "error"):
            status = StepStatus.FAILED
        elif raw_status == "skipped":
            status = StepStatus.SKIPPED
        else:
            logger.warning(
                "Unknown step status %r for step %r, defaulting to FAILED",
                raw_status,
                step_name,
            )
            status = StepStatus.FAILED

        step_tokens = token_counts.get(step_name, {})
        meta: dict[str, Any] = {}
        if step_tokens:
            meta["input_tokens"] = step_tokens.get("input", 0)
            meta["output_tokens"] = step_tokens.get("output", 0)

        results.append(
            StepResult(
                step_name=step_name,
                status=status,
                agent_role=step_data.get("agent"),
                model_used=models_used.get(step_name),
                input_data=step_data.get("inputs", {}),
                output_data=step_data.get("outputs", {}),
                error=step_data.get("error"),
                metadata=meta,
            )
        )

    return results


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
    if failed or errors:
        overall_status = StepStatus.FAILED
    else:
        overall_status = StepStatus.SUCCESS

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


def extract_metadata(
    final_state: dict[str, Any],
) -> tuple[dict[str, dict], dict[str, str]]:
    """Extract per-step token counts and model identifiers from final workflow state.

    Args:
        final_state: The LangGraph state dict produced after workflow execution.

    Returns:
        A two-tuple of ``(token_counts, models_used)`` where ``token_counts``
        maps step name to ``{"input": int, "output": int}`` and
        ``models_used`` maps step name to the model identifier string.
    """
    token_counts: dict[str, dict] = {}
    models_used: dict[str, str] = {}

    for step_name, step_data in final_state.get("steps", {}).items():
        meta = step_data.get("metadata", {})
        if meta.get("input_tokens") or meta.get("output_tokens"):
            token_counts[step_name] = {
                "input": meta.get("input_tokens", 0),
                "output": meta.get("output_tokens", 0),
            }
        if model := meta.get("model"):
            models_used[step_name] = model

    return token_counts, models_used
