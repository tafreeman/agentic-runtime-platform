"""Pure helper functions for normalizing workflow results.

Provides stateless transformations used by the execution engine and route
handlers.  All functions are side-effect-free and operate on standard
Python types.

Public API
----------
is_effectively_empty
    Test whether a value is None, blank, or an empty collection.
merge_dataset_and_request_inputs
    Merge adapted dataset inputs with explicit request inputs.
as_dict
    Normalize an arbitrary value into a JSON-serializable dict.
coerce_step_status
    Map a status-like value to a :class:`StepStatus` enum member.
extract_tokens
    Pull total token count from step metadata.
build_step_results
    Convert LangGraph step state to contract :class:`StepResult` objects.
normalize_workflow_result
    Normalize a runner result into a contract :class:`WorkflowResult`.
load_dataset_sample
    Load a dataset sample based on evaluation configuration.
resolve_evaluation_inputs
    Load, adapt, merge, and validate evaluation inputs.
"""

from __future__ import annotations

import inspect
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from fastapi import HTTPException

from ..contracts import StepResult, StepStatus, WorkflowResult
from ..workflows.run_logger import RunLogger
from .evaluation import (
    adapt_sample_to_workflow_inputs,
    load_local_dataset_sample,
    load_repository_dataset_sample,
    match_workflow_dataset,
    validate_required_inputs_present,
)

logger = logging.getLogger(__name__)
run_logger = RunLogger()


def _call_with_supported_kwargs(func: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Call ``func`` with only the keyword arguments it declares.

    This preserves tenant-aware production calls while remaining compatible
    with legacy monkeypatched test doubles that still expose the older
    signature without ``tenant_id``.
    """
    if not kwargs:
        return func(*args)
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args, **kwargs)

    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return func(*args, **kwargs)

    supported_kwargs = {
        key: value for key, value in kwargs.items() if key in signature.parameters
    }
    return func(*args, **supported_kwargs)


def is_effectively_empty(value: Any) -> bool:
    """Check whether a value is effectively empty (None, blank, or empty collection).

    Args:
        value: The value to test.

    Returns:
        True if the value is considered empty.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def merge_dataset_and_request_inputs(
    adapted_inputs: dict[str, Any],
    request_inputs: dict[str, Any],
) -> dict[str, Any]:
    """Merge adapted dataset inputs with explicit request inputs.

    Request inputs take precedence, except when a request value is
    effectively empty and an adapted value already exists for that key.

    Args:
        adapted_inputs: Inputs derived from the dataset sample.
        request_inputs: Inputs explicitly provided in the API request.

    Returns:
        Merged input dict.
    """
    merged = dict(adapted_inputs)
    for key, value in request_inputs.items():
        if is_effectively_empty(value) and key in merged:
            continue
        merged[key] = value
    return merged


def as_dict(value: Any) -> dict[str, Any]:
    """Normalize an arbitrary value into a JSON-serializable dict.

    Args:
        value: Input value (dict passed through, None becomes ``{}``,
            anything else wrapped as ``{"value": value}``).

    Returns:
        Dict representation of the value.
    """
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    return {"value": value}


def coerce_step_status(value: Any) -> StepStatus:
    """Coerce a status-like value into a :class:`StepStatus` enum member.

    Handles string variants (e.g., ``"succeeded"``, ``"completed"``,
    ``"in_progress"``) and passes through existing ``StepStatus`` instances.

    Args:
        value: Raw status value from a runner or step dict.

    Returns:
        Corresponding ``StepStatus`` member (defaults to ``FAILED``).
    """
    if isinstance(value, StepStatus):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"success", "succeeded", "completed"}:
        return StepStatus.SUCCESS
    if normalized in {"skipped", "skip"}:
        return StepStatus.SKIPPED
    if normalized in {"pending", "queued"}:
        return StepStatus.PENDING
    if normalized in {"running", "in_progress"}:
        return StepStatus.RUNNING
    return StepStatus.FAILED


def extract_tokens(metadata: Mapping[str, Any]) -> int | None:
    """Extract total token count from step metadata.

    Checks for ``tokens_used`` directly, then sums ``input_tokens`` and
    ``output_tokens`` if available.

    Args:
        metadata: Step metadata mapping.

    Returns:
        Total token count, or None if not available.
    """
    direct = metadata.get("tokens_used")
    if isinstance(direct, int):
        return direct
    input_tokens = metadata.get("input_tokens")
    output_tokens = metadata.get("output_tokens")
    if isinstance(input_tokens, int) or isinstance(output_tokens, int):
        return int(input_tokens or 0) + int(output_tokens or 0)
    return None


def build_step_results(
    steps_map: Mapping[str, Any],
    *,
    token_counts: Mapping[str, Any] | None = None,
    models_used: Mapping[str, Any] | None = None,
) -> list[StepResult]:
    """Convert LangGraph step state mappings into contract :class:`StepResult` objects.

    Merges token counts and model identifiers from separate metadata
    dictionaries into each step result.

    Args:
        steps_map: Mapping of step name to step state dict.
        token_counts: Optional per-step token usage mapping.
        models_used: Optional per-step model identifier mapping.

    Returns:
        List of :class:`StepResult` instances.
    """
    results: list[StepResult] = []
    token_counts = token_counts or {}
    models_used = models_used or {}

    for step_name, step_data in steps_map.items():
        if not isinstance(step_data, Mapping):
            continue

        metadata_raw = step_data.get("metadata")
        metadata: dict[str, Any] = (
            dict(metadata_raw) if isinstance(metadata_raw, Mapping) else {}
        )

        token_meta = token_counts.get(step_name)
        if isinstance(token_meta, Mapping):
            input_tokens = int(token_meta.get("input") or 0)
            output_tokens = int(token_meta.get("output") or 0)
            metadata.setdefault("input_tokens", input_tokens)
            metadata.setdefault("output_tokens", output_tokens)
            metadata.setdefault("tokens_used", input_tokens + output_tokens)

        model_used = models_used.get(step_name)
        if model_used is None:
            model_used = step_data.get("model_used")
        if not isinstance(model_used, str):
            model_used = None

        error_val = step_data.get("error")
        error_text = str(error_val) if error_val else None

        start_ts = step_data.get("start_time")
        start_time = (
            datetime.fromisoformat(start_ts)
            if isinstance(start_ts, str)
            else datetime.now(UTC)
        )

        end_ts = step_data.get("end_time")
        end_time = datetime.fromisoformat(end_ts) if isinstance(end_ts, str) else None

        results.append(
            StepResult(
                step_name=str(step_name),
                status=coerce_step_status(step_data.get("status")),
                agent_role=(
                    str(step_data.get("agent_role"))
                    if step_data.get("agent_role") is not None
                    else None
                ),
                tier=(
                    int(step_data["tier"])
                    if isinstance(step_data.get("tier"), int)
                    else None
                ),
                model_used=model_used,
                input_data=as_dict(step_data.get("inputs")),
                output_data=as_dict(step_data.get("outputs")),
                error=error_text,
                metadata=metadata,
                start_time=start_time,
                end_time=end_time,
            )
        )

    return results


def normalize_workflow_result(
    result: Any,
    *,
    workflow_name: str,
    run_id: str,
) -> WorkflowResult:
    """Normalize a runner result (LangGraph or native) into a contract
    :class:`WorkflowResult`.

    Handles both :class:`WorkflowResult` pass-through and duck-typed runner
    result objects with ``steps``, ``errors``, ``overall_status``, etc.

    Args:
        result: Raw runner result object.
        workflow_name: Name of the executed workflow.
        run_id: Unique run identifier.

    Returns:
        A fully populated :class:`WorkflowResult`.
    """
    if isinstance(result, WorkflowResult):
        return result

    steps_map = getattr(result, "steps", {})
    if not isinstance(steps_map, Mapping):
        steps_map = {}

    token_counts = getattr(result, "token_counts", {})
    if not isinstance(token_counts, Mapping):
        token_counts = {}
    models_used = getattr(result, "models_used", {})
    if not isinstance(models_used, Mapping):
        models_used = {}

    steps = build_step_results(
        steps_map,
        token_counts=token_counts,
        models_used=models_used,
    )

    raw_errors = getattr(result, "errors", [])
    if isinstance(raw_errors, list):
        errors = [str(e) for e in raw_errors if e]
    elif raw_errors:
        errors = [str(raw_errors)]
    else:
        errors = []

    overall_source = getattr(result, "overall_status", None)
    if overall_source is not None:
        overall_status = coerce_step_status(overall_source)
    else:
        status_text = str(getattr(result, "status", "")).lower()
        overall_status = (
            StepStatus.SUCCESS
            if status_text == "success" and not errors
            else StepStatus.FAILED
        )

    elapsed_seconds = getattr(result, "elapsed_seconds", 0.0)
    try:
        elapsed_seconds = float(elapsed_seconds)
    except Exception:
        elapsed_seconds = 0.0

    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(seconds=max(elapsed_seconds, 0.0))

    final_output = as_dict(
        getattr(result, "final_output", None) or getattr(result, "outputs", None)
    )
    metadata: dict[str, Any] = {}
    langgraph_run_id = getattr(result, "run_id", None)
    if isinstance(langgraph_run_id, str) and langgraph_run_id:
        metadata["langgraph_run_id"] = langgraph_run_id
    if errors:
        metadata["errors"] = errors

    return WorkflowResult(
        workflow_id=run_id,
        workflow_name=workflow_name,
        steps=steps,
        overall_status=overall_status,
        start_time=start_time,
        end_time=end_time,
        final_output=final_output,
        metadata=metadata,
    )


def _load_dataset_sample(
    evaluation: Any,
    *,
    tenant_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Load a dataset sample based on evaluation configuration.

    Dispatches to :func:`load_repository_dataset_sample` or
    :func:`load_local_dataset_sample` based on ``evaluation.dataset_source``.

    Args:
        evaluation: :class:`WorkflowEvaluationRequest` with dataset settings.

    Returns:
        A 2-tuple of ``(sample_dict, metadata_dict)``, or ``(None, None)``
        if ``dataset_source`` is ``"none"``.

    Raises:
        HTTPException: If required dataset fields are missing.
    """
    if evaluation.dataset_source == "repository":
        if not evaluation.dataset_id:
            raise HTTPException(
                status_code=422,
                detail="evaluation.dataset_id is required for repository datasets",
            )
        return load_repository_dataset_sample(
            evaluation.dataset_id,
            sample_index=evaluation.sample_index,
        )
    if evaluation.dataset_source == "local":
        dataset_ref = evaluation.local_dataset_path or evaluation.dataset_id
        if not dataset_ref:
            raise HTTPException(
                status_code=422,
                detail=(
                    "evaluation.dataset_id or evaluation.local_dataset_path is "
                    "required for local datasets"
                ),
            )
        return _call_with_supported_kwargs(
            load_local_dataset_sample,
            dataset_ref,
            sample_index=evaluation.sample_index,
            tenant_id=tenant_id,
        )
    return None, None


def _resolve_evaluation_inputs(
    workflow_def: Any,
    evaluation: Any,
    run_id: str,
    workflow_inputs: dict[str, Any],
    *,
    artifacts_dir: Path | None = None,
    tenant_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    """Load a dataset sample, adapt it to workflow inputs, and merge with request
    inputs.

    Args:
        workflow_def: Loaded workflow definition.
        evaluation: :class:`WorkflowEvaluationRequest` with dataset settings.
        run_id: Current run identifier (for file materialization).
        workflow_inputs: Explicit inputs from the API request.
        artifacts_dir: Directory for materializing file-type inputs.

    Returns:
        A 3-tuple of ``(merged_inputs, dataset_sample, dataset_meta)``.

    Raises:
        HTTPException: If the dataset is incompatible or required inputs
            are still missing after adaptation.
    """
    _artifacts_dir = artifacts_dir or run_logger.runs_dir / "_inputs"

    try:
        dataset_sample, dataset_meta = _load_dataset_sample(
            evaluation,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not dataset_sample:
        return workflow_inputs, dataset_sample, dataset_meta

    compatible, reasons = match_workflow_dataset(workflow_def, dataset_sample)
    if not compatible:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Dataset sample is incompatible with workflow inputs",
                "reasons": reasons,
            },
        )

    adapted = adapt_sample_to_workflow_inputs(
        workflow_def.inputs,
        dataset_sample,
        run_id=run_id,
        artifacts_dir=_artifacts_dir,
    )
    merged = merge_dataset_and_request_inputs(adapted, workflow_inputs)
    dataset_meta = {
        **(dataset_meta or {}),
        "dataset_workflow_compatible": True,
        "dataset_mismatch_reasons": [],
    }

    missing = validate_required_inputs_present(workflow_def.inputs, merged)
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Missing required workflow inputs after dataset adaptation",
                "missing_inputs": missing,
            },
        )
    return merged, dataset_sample, dataset_meta
