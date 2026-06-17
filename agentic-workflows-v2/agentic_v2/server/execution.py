"""Workflow execution orchestration.

Contains the background-task lifecycle for running workflows, streaming
LangGraph events via WebSocket, and optionally scoring with an LLM judge.

Public API
----------
_get_lc_runner
    Lazily initialise the LangChain runner singleton.
_resolve_judge_model
    Resolve the LLM model identifier for the evaluation judge.
_merge_stream_state
    Merge a streamed LangGraph node update into aggregate state.
_run_via_native_adapter
    Execute a workflow through a non-LangChain adapter.
_stream_and_run
    Stream LangGraph events then build a WorkflowResult.
_run_and_evaluate
    Full background task: execute, evaluate, broadcast, log.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Mapping

from ..contracts import StepStatus, WorkflowResult
from ..core.tenant import DEFAULT_TENANT_ID
from ..langchain.config import load_workflow_config
from ..langchain.dependencies import (
    is_missing_langchain_dependency_error,
    to_missing_langchain_dependency_error,
)

# LangChain imports — optional.
try:
    from ..langchain import WorkflowRunner as LangChainRunner

    _LANGCHAIN_AVAILABLE = True
    _LANGCHAIN_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:
    if not is_missing_langchain_dependency_error(exc):
        raise
    _LANGCHAIN_AVAILABLE = False
    _LANGCHAIN_IMPORT_ERROR = to_missing_langchain_dependency_error(exc)

from ..integrations.otel import create_trace_adapter
from ..scoring.judge import LLMJudge
from ..scoring.step_scoring import build_step_scoring_listener
from ..workflows.run_logger import RunLogger
from . import websocket
from .evaluation import score_workflow_result
from .result_normalization import as_dict, extract_tokens, normalize_workflow_result

logger = logging.getLogger(__name__)

# LangChain runner — lazily initialised so the server starts without langchain
_lc_runner = None
run_logger = RunLogger()


def _get_lc_runner():
    """Lazily initialize the LangChain runner."""
    global _lc_runner
    if not _LANGCHAIN_AVAILABLE:
        from fastapi import HTTPException

        detail = (
            str(_LANGCHAIN_IMPORT_ERROR)
            if _LANGCHAIN_IMPORT_ERROR is not None
            else "LangChain extras not installed. Install with: pip install -e '.[langchain]'"
        )
        raise HTTPException(
            status_code=501,
            detail=detail,
        )
    if _lc_runner is None:
        _lc_runner = LangChainRunner(trace_adapter=create_trace_adapter())
    return _lc_runner


def _resolve_judge_model() -> str | None:
    """Resolve the LLM model identifier for the evaluation judge.

    Checks environment variables in priority order:
    ``AGENTIC_JUDGE_MODEL``, ``AGENTIC_MODEL_TIER_2``, ``AGENTIC_MODEL_TIER_1``.

    Returns:
        Model identifier string, or None if no judge model is configured.
    """
    for key in ("AGENTIC_JUDGE_MODEL", "AGENTIC_MODEL_TIER_2", "AGENTIC_MODEL_TIER_1"):
        value = os.getenv(key)  # env-pass: dynamic model tier config
        if value and value.strip():
            return value.strip()
    return None


def _merge_stream_state(
    aggregated: dict[str, Any], node_update: Mapping[str, Any]
) -> None:
    """Merge a streamed LangGraph node update into the aggregate run state.

    Incrementally updates ``context``, ``outputs``, ``steps``, and
    ``errors`` in the ``aggregated`` dict.  Step data is merged
    key-by-key so partial updates do not overwrite earlier fields.

    Args:
        aggregated: Mutable aggregate state dict (modified in place).
        node_update: Single LangGraph stream update mapping.
    """
    for payload in node_update.values():
        if isinstance(payload, Mapping):
            _merge_stream_payload(aggregated, payload)


def _merge_stream_payload(
    aggregated: dict[str, Any], payload: Mapping[str, Any]
) -> None:
    """Merge one stream payload's context/outputs/steps/errors into aggregate state."""
    context = payload.get("context")
    if isinstance(context, Mapping):
        aggregated["context"].update(context)

    outputs = payload.get("outputs")
    if isinstance(outputs, Mapping):
        aggregated["outputs"].update(outputs)

    steps = payload.get("steps")
    if isinstance(steps, Mapping):
        _merge_step_updates(aggregated["steps"], steps)

    errors = payload.get("errors")
    if isinstance(errors, list):
        for err in errors:
            if err:
                aggregated["errors"].append(str(err))


def _merge_step_updates(
    aggregated_steps: dict[str, Any], steps: Mapping[str, Any]
) -> None:
    """Merge a step-update mapping into ``aggregated_steps`` key-by-key.

    Existing step dicts are copied and updated so partial updates do not
    overwrite previously-streamed fields.
    """
    for step_name, step_data in steps.items():
        if not isinstance(step_data, Mapping):
            continue
        existing = aggregated_steps.get(step_name)
        if isinstance(existing, dict):
            merged = dict(existing)
            merged.update(step_data)
            aggregated_steps[step_name] = merged
        else:
            aggregated_steps[step_name] = dict(step_data)


def _safe_stream_artifact_segment(value: str) -> str:
    """Return a filesystem-safe path segment for stream artifacts."""
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_" for char in value
    ).strip("_")
    return cleaned[:80] or "artifact"


def _looks_like_code_artifact(key_path: str, value: str) -> bool:
    """Heuristic for code-like payloads that should not ride the WebSocket."""
    key = key_path.lower()
    if any(part in key for part in ("code", "script", "source")):
        return "\n" in value or len(value) > 200
    return len(value) > 4_000


def _stream_artifact_extension(key_path: str, value: str) -> str:
    """Pick a useful extension for a materialized text artifact."""
    lowered = key_path.lower()
    stripped = value.lstrip()
    if (
        "python" in lowered
        or "api_code" in lowered
        or stripped.startswith(("def ", "class ", "from ", "import "))
    ):
        return ".py"
    if "typescript" in lowered or lowered.endswith("_ts") or "tsx" in lowered:
        return ".ts"
    if "javascript" in lowered or lowered.endswith("_js") or "jsx" in lowered:
        return ".js"
    if "sql" in lowered or "migration" in lowered:
        return ".sql"
    return ".txt"


def _materialize_stream_payload(
    value: Any,
    *,
    run_id: str,
    step_name: str,
    direction: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    key_path: str = "value",
) -> Any:
    """Replace code-like stream strings with on-disk artifact references."""
    if isinstance(value, Mapping):
        return {
            str(key): _materialize_stream_payload(
                item,
                run_id=run_id,
                step_name=step_name,
                direction=direction,
                tenant_id=tenant_id,
                key_path=f"{key_path}.{key}",
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _materialize_stream_payload(
                item,
                run_id=run_id,
                step_name=step_name,
                direction=direction,
                tenant_id=tenant_id,
                key_path=f"{key_path}.{index}",
            )
            for index, item in enumerate(value)
        ]
    if not isinstance(value, str) or not _looks_like_code_artifact(key_path, value):
        return value

    artifact_root = (
        run_logger.for_tenant(tenant_id).runs_dir
        / "_stream_artifacts"
        / _safe_stream_artifact_segment(run_id)
        / _safe_stream_artifact_segment(step_name)
        / _safe_stream_artifact_segment(direction)
    )
    artifact_root.mkdir(parents=True, exist_ok=True)
    filename = _safe_stream_artifact_segment(key_path) + _stream_artifact_extension(
        key_path, value
    )
    artifact_path = (artifact_root / filename).resolve()
    artifact_root_resolved = artifact_root.resolve()
    try:
        artifact_path.relative_to(artifact_root_resolved)
    except ValueError:
        raise ValueError(f"Unsafe stream artifact path: {artifact_path}") from None
    artifact_path.write_text(value, encoding="utf-8")
    return {
        "artifact_path": str(artifact_path),
        "bytes": len(value.encode("utf-8")),
        "content_type": "text/plain",
    }


def _stream_dict(
    value: Any,
    *,
    run_id: str,
    step_name: str,
    direction: str,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> dict[str, Any]:
    """Normalize a stream payload and materialize large/code-like text leaves."""
    normalized = as_dict(value)
    materialized = _materialize_stream_payload(
        normalized,
        run_id=run_id,
        step_name=step_name,
        direction=direction,
        tenant_id=tenant_id,
    )
    return materialized if isinstance(materialized, dict) else as_dict(materialized)


async def _run_via_native_adapter(
    adapter_name: str,
    workflow_name: str,
    run_id: str,
    workflow_inputs: dict[str, Any],
    on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> WorkflowResult:
    """Execute a workflow through a non-LangChain adapter and return a normalised
    :class:`WorkflowResult`.

    Args:
        adapter_name: Registered adapter name (e.g. ``"native"``).
        workflow_name: Name of the workflow to execute.
        run_id: Unique run identifier (used as ``workflow_id``).
        workflow_inputs: Input variables for the workflow.
        on_update: Optional async callback for step/workflow events.

    Returns:
        A fully populated :class:`WorkflowResult`.
    """
    from ..adapters import get_registry
    from ..engine.context import ExecutionContext
    from ..workflows.loader import WorkflowLoader

    loader = WorkflowLoader()
    workflow_def = loader.load(workflow_name)
    dag = workflow_def.dag
    ctx = ExecutionContext(variables=dict(workflow_inputs))

    engine = get_registry().get_adapter(adapter_name)
    raw = await engine.execute(
        dag,
        ctx,
        on_update=on_update,
        thread_id=run_id,
    )

    return normalize_workflow_result(raw, workflow_name=workflow_name, run_id=run_id)


async def _stream_and_run(
    workflow_name: str,
    run_id: str,
    workflow_inputs: dict[str, Any],
    adapter_name: str = "langchain",
    tenant_id: str = DEFAULT_TENANT_ID,
) -> WorkflowResult:
    """Stream LangGraph node events to WebSocket clients, then build a final
    WorkflowResult.

    When *adapter_name* is ``"langchain"`` (the default), iterates over the
    LangGraph async stream, broadcasting ``step_start`` and ``step_end``
    events via WebSocket.  Falls back to a non-streaming ``invoke`` if the
    stream raises an exception.

    Args:
        workflow_name: Name of the workflow to execute.
        run_id: Unique run identifier.
        workflow_inputs: Input variables for the workflow.
        adapter_name: Execution adapter to use (default ``"langchain"``).

    Returns:
        The completed :class:`WorkflowResult`.
    """
    if adapter_name != "langchain":
        return await _run_native_stream(
            adapter_name,
            workflow_name,
            run_id,
            workflow_inputs,
        )

    scoring_listener = build_step_scoring_listener()
    started_perf = time.perf_counter()
    step_start_times: dict[str, float] = {}
    last_status_by_step: dict[str, str] = {}
    aggregated_state: dict[str, Any] = {
        "context": {},
        "steps": {},
        "outputs": {},
        "errors": [],
    }

    try:
        async for node_update in _get_lc_runner().astream(
            workflow_name,
            thread_id=run_id,
            **workflow_inputs,
        ):
            if not isinstance(node_update, Mapping):
                continue

            _merge_stream_state(aggregated_state, node_update)
            now = datetime.now(UTC).isoformat()
            await _broadcast_node_steps(
                node_update,
                aggregated_state=aggregated_state,
                run_id=run_id,
                tenant_id=tenant_id,
                now=now,
                step_start_times=step_start_times,
                last_status_by_step=last_status_by_step,
                scoring_listener=scoring_listener,
            )

        result = _build_stream_result(
            aggregated_state,
            workflow_name=workflow_name,
            run_id=run_id,
            started_perf=started_perf,
        )
        if scoring_listener is not None:
            result.metadata["step_scores"] = scoring_listener.get_summary()
        return result
    except Exception as stream_err:
        logger.warning("Streaming failed (%s); falling back to invoke", stream_err)
        fallback = await _get_lc_runner().run(
            workflow_name,
            thread_id=run_id,
            **workflow_inputs,
        )
        return normalize_workflow_result(
            fallback,
            workflow_name=workflow_name,
            run_id=run_id,
        )


async def _run_native_stream(
    adapter_name: str,
    workflow_name: str,
    run_id: str,
    workflow_inputs: dict[str, Any],
) -> WorkflowResult:
    """Execute via a non-LangChain adapter, broadcasting and scoring updates."""
    scoring_listener = build_step_scoring_listener()

    async def _broadcast_and_score_update(event: dict[str, Any]) -> None:
        """Broadcast to WebSocket clients and collect per-step scores."""
        if scoring_listener is not None:
            await scoring_listener.handle_update(event)
        await websocket.manager.broadcast(run_id, event)

    result = await _run_via_native_adapter(
        adapter_name,
        workflow_name,
        run_id,
        workflow_inputs,
        on_update=_broadcast_and_score_update,
    )
    if scoring_listener is not None:
        result.metadata["step_scores"] = scoring_listener.get_summary()
    return result


def _step_start_event(
    broadcast_step_data: Mapping[str, Any],
    *,
    run_id: str,
    step_name: str,
    tenant_id: str,
    now: str,
) -> dict[str, Any]:
    """Build a ``step_start`` broadcast payload for a single step."""
    return {
        "type": "step_start",
        "run_id": run_id,
        "step": step_name,
        "input": _stream_dict(
            broadcast_step_data.get("inputs"),
            run_id=run_id,
            step_name=step_name,
            direction="input",
            tenant_id=tenant_id,
        ),
        "timestamp": now,
    }


def _step_duration_ms(
    broadcast_step_data: Mapping[str, Any],
    *,
    step_name: str,
    step_start_times: dict[str, float],
) -> int:
    """Resolve a non-negative step duration in milliseconds.

    Prefers an explicit ``duration_ms``, then a start/end timestamp delta,
    then the wall-clock time since the locally-recorded start.
    """
    duration_from_state = broadcast_step_data.get("duration_ms")
    if duration_from_state is not None:
        return max(0, int(duration_from_state))

    calc_duration = 0
    start_ts_str = broadcast_step_data.get("start_time")
    end_ts_str = broadcast_step_data.get("end_time")
    if isinstance(start_ts_str, str) and isinstance(end_ts_str, str):
        try:
            st = datetime.fromisoformat(start_ts_str)
            et = datetime.fromisoformat(end_ts_str)
            calc_duration = int((et - st).total_seconds() * 1000)
        except ValueError:
            pass

    if calc_duration <= 0:
        step_start = step_start_times.pop(step_name, time.time())
        calc_duration = int((time.time() - step_start) * 1000)

    return max(0, calc_duration)


def _step_end_event(
    broadcast_step_data: Mapping[str, Any],
    *,
    run_id: str,
    step_name: str,
    tenant_id: str,
    now: str,
    status: str,
    duration_ms: int,
) -> dict[str, Any]:
    """Build a ``step_end`` broadcast payload for a single step."""
    metadata_raw = broadcast_step_data.get("metadata")
    metadata = metadata_raw if isinstance(metadata_raw, Mapping) else {}
    model_used = metadata.get("model")
    if not isinstance(model_used, str):
        model_used = None
    tokens_used = extract_tokens(metadata)
    error_val = broadcast_step_data.get("error")

    output_dict = _stream_dict(
        broadcast_step_data.get("outputs"),
        run_id=run_id,
        step_name=step_name,
        direction="output",
        tenant_id=tenant_id,
    )
    return {
        "type": "step_end",
        "run_id": run_id,
        "step": step_name,
        "status": status,
        "duration_ms": duration_ms,
        "model_used": model_used,
        "tokens_used": tokens_used,
        "tier": broadcast_step_data.get("tier"),
        "input": _stream_dict(
            broadcast_step_data.get("inputs"),
            run_id=run_id,
            step_name=step_name,
            direction="input",
            tenant_id=tenant_id,
        ),
        "output": output_dict,
        "outputs": output_dict,
        "error": str(error_val) if error_val else None,
        "timestamp": now,
    }


async def _process_streamed_step(
    step_name_raw: Any,
    step_data: Mapping[str, Any],
    *,
    aggregated_state: dict[str, Any],
    run_id: str,
    tenant_id: str,
    now: str,
    step_start_times: dict[str, float],
    last_status_by_step: dict[str, str],
    scoring_listener: Any,
) -> None:
    """Emit step_start/step_end events for a single streamed step update.

    Mirrors the original per-step state machine: a step transitions to
    ``running`` (emitting ``step_start`` once) and then to a terminal status
    (emitting ``step_end`` once, plus a scoring update on success).
    """
    step_name = str(step_name_raw)
    merged_step_data = aggregated_state.get("steps", {}).get(step_name_raw)
    broadcast_step_data = (
        merged_step_data if isinstance(merged_step_data, Mapping) else step_data
    )
    status = str(step_data.get("status", "running")).strip().lower()
    previous_status = last_status_by_step.get(step_name)

    if status in {"running", "pending"}:
        if previous_status == "running":
            return
        last_status_by_step[step_name] = "running"
        step_start_times.setdefault(step_name, time.time())
        await websocket.manager.broadcast(
            run_id,
            _step_start_event(
                broadcast_step_data,
                run_id=run_id,
                step_name=step_name,
                tenant_id=tenant_id,
                now=now,
            ),
        )
        return

    if status not in {"success", "failed", "skipped"}:
        return
    if previous_status == status:
        return

    if previous_status is None:
        last_status_by_step[step_name] = "running"
        step_start_times.setdefault(step_name, time.time())
        await websocket.manager.broadcast(
            run_id,
            _step_start_event(
                broadcast_step_data,
                run_id=run_id,
                step_name=step_name,
                tenant_id=tenant_id,
                now=now,
            ),
        )

    last_status_by_step[step_name] = status
    duration_ms = _step_duration_ms(
        broadcast_step_data,
        step_name=step_name,
        step_start_times=step_start_times,
    )

    await websocket.manager.broadcast(
        run_id,
        _step_end_event(
            broadcast_step_data,
            run_id=run_id,
            step_name=step_name,
            tenant_id=tenant_id,
            now=now,
            status=status,
            duration_ms=duration_ms,
        ),
    )

    if scoring_listener is not None and status == "success":
        output_text = str(
            broadcast_step_data.get("outputs")
            or broadcast_step_data.get("output")
            or ""
        )
        await scoring_listener.handle_update(
            {
                "type": "step_end",
                "step": step_name,
                "status": status,
                "output": output_text,
            }
        )


async def _broadcast_node_steps(
    node_update: Mapping[str, Any],
    *,
    aggregated_state: dict[str, Any],
    run_id: str,
    tenant_id: str,
    now: str,
    step_start_times: dict[str, float],
    last_status_by_step: dict[str, str],
    scoring_listener: Any,
) -> None:
    """Walk a node update's step maps and emit events for each step."""
    for step_state in node_update.values():
        if not isinstance(step_state, Mapping):
            continue
        step_map = step_state.get("steps")
        if not isinstance(step_map, Mapping):
            continue

        for step_name_raw, step_data in step_map.items():
            if not isinstance(step_data, Mapping):
                continue
            await _process_streamed_step(
                step_name_raw,
                step_data,
                aggregated_state=aggregated_state,
                run_id=run_id,
                tenant_id=tenant_id,
                now=now,
                step_start_times=step_start_times,
                last_status_by_step=last_status_by_step,
                scoring_listener=scoring_listener,
            )


def _build_stream_result(
    aggregated_state: dict[str, Any],
    *,
    workflow_name: str,
    run_id: str,
    started_perf: float,
) -> WorkflowResult:
    """Resolve outputs/metadata from aggregate state into a WorkflowResult."""
    workflow_cfg = load_workflow_config(workflow_name)
    resolved_outputs = _get_lc_runner().resolve_outputs(workflow_cfg, aggregated_state)
    if not isinstance(resolved_outputs, dict):
        resolved_outputs = {}
    if not resolved_outputs:
        resolved_outputs = as_dict(aggregated_state.get("outputs"))

    token_counts, models_used = _get_lc_runner().extract_metadata(aggregated_state)
    errors = [str(err) for err in aggregated_state.get("errors", []) if err]

    overall_status = StepStatus.SUCCESS
    step_state = aggregated_state.get("steps", {})
    if errors or any(
        isinstance(step_data, Mapping)
        and str(step_data.get("status", "")).strip().lower() == "failed"
        for step_data in step_state.values()
    ):
        overall_status = StepStatus.FAILED

    raw_result = SimpleNamespace(
        steps=step_state,
        token_counts=token_counts,
        models_used=models_used,
        errors=errors,
        overall_status=overall_status,
        elapsed_seconds=max(0.0, time.perf_counter() - started_perf),
        final_output=resolved_outputs,
    )
    return normalize_workflow_result(
        raw_result,
        workflow_name=workflow_name,
        run_id=run_id,
    )


async def _run_and_evaluate(
    workflow_name: str,
    run_id: str,
    workflow_inputs: dict[str, Any],
    workflow_def: Any,
    evaluation: Any,
    dataset_sample: dict[str, Any] | None,
    dataset_meta: dict[str, Any] | None,
    adapter_name: str = "langchain",
    tenant_id: str = DEFAULT_TENANT_ID,
) -> None:
    """Background task: execute workflow, optionally evaluate, broadcast
    events, and log.

    Orchestrates the full run lifecycle:
    1. Broadcast ``workflow_start`` event.
    2. Execute via :func:`_stream_and_run` (with WebSocket step events).
    3. Broadcast ``workflow_end`` event.
    4. If evaluation is enabled, score the result and broadcast
       ``evaluation_complete``.
    5. Persist the run log.

    Args:
        workflow_name: Name of the workflow to execute.
        run_id: Unique run identifier.
        workflow_inputs: Input variables for the workflow.
        workflow_def: Loaded workflow definition.
        evaluation: Evaluation settings from the request (or None).
        dataset_sample: Dataset sample dict for scoring (or None).
        dataset_meta: Dataset metadata dict for scoring (or None).
        adapter_name: Execution adapter to use (default ``"langchain"``).
    """
    try:
        logger.info("Starting background execution for run_id=%s", run_id)
        await websocket.manager.broadcast(
            run_id,
            {
                "type": "workflow_start",
                "run_id": run_id,
                "workflow_name": workflow_name,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        result = await _stream_and_run(
            workflow_name,
            run_id,
            workflow_inputs,
            adapter_name=adapter_name,
            tenant_id=tenant_id,
        )

        status = result.overall_status.value
        workflow_errors = [
            step.error
            for step in result.steps
            if step.status == StepStatus.FAILED and step.error
        ]
        metadata_errors = result.metadata.get("errors")
        if isinstance(metadata_errors, list):
            workflow_errors.extend(str(err) for err in metadata_errors if err)

        await websocket.manager.broadcast(
            run_id,
            {
                "type": "workflow_end",
                "run_id": run_id,
                "status": status,
                "outputs": result.final_output,
                "elapsed_seconds": (
                    (result.total_duration_ms or 0.0) / 1000.0
                    if result.total_duration_ms is not None
                    else 0.0
                ),
                "errors": workflow_errors,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        scored_evaluation: dict[str, Any] | None = None
        if evaluation and evaluation.enabled:
            await websocket.manager.broadcast(
                run_id,
                {
                    "type": "evaluation_start",
                    "run_id": run_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            judge_model = _resolve_judge_model()
            judge = LLMJudge(model=judge_model) if judge_model else LLMJudge()

            scored_evaluation = score_workflow_result(
                result,
                dataset_meta=dataset_meta,
                dataset_sample=dataset_sample,
                rubric=(evaluation.rubric_id or evaluation.rubric),
                workflow_definition=workflow_def,
                enforce_hard_gates=evaluation.enforce_hard_gates,
                judge=judge,
            )
            await websocket.manager.broadcast(
                run_id,
                {
                    "type": "evaluation_complete",
                    "run_id": run_id,
                    **{
                        k: scored_evaluation[k]
                        for k in (
                            "rubric",
                            "rubric_id",
                            "rubric_version",
                            "weighted_score",
                            "overall_score",
                            "grade",
                            "passed",
                            "pass_threshold",
                            "criteria",
                            "hard_gates",
                            "hard_gate_failures",
                            "step_scores",
                        )
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        run_logger.for_tenant(tenant_id).log(
            result,
            dataset_meta=dataset_meta,
            workflow_inputs=workflow_inputs,
            extra={
                "evaluation_requested": bool(evaluation and evaluation.enabled),
                "evaluation": scored_evaluation,
            },
        )
        logger.info("Completed background execution for run_id=%s", run_id)
    except Exception as e:
        logger.error(
            "Error in background execution for run_id=%s: %s",
            run_id,
            e,
            exc_info=True,
        )
        await websocket.manager.broadcast(
            run_id,
            {
                "type": "error",
                "run_id": run_id,
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
