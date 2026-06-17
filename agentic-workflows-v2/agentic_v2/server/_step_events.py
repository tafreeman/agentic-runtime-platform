"""Step event builders and broadcast logic for LangGraph streaming.

Responsible for:
- Building ``step_start`` / ``step_end`` WebSocket broadcast payloads.
- Computing step duration from state or wall-clock.
- Walking a node update and emitting events per step (_broadcast_node_steps,
  _process_streamed_step).

``_stream_dict`` lives in execution.py (alongside ``_materialize_stream_payload``
and ``run_logger``).  Rather than creating a circular import, this module
accepts the materializer as an injected callable stored in ``_stream_dict_ref``.
``execution.py`` sets this reference immediately after its own definition of
``_stream_dict``.

Internal protocol
-----------------
    import agentic_v2.server._step_events as _se
    _se._stream_dict_ref = _stream_dict   # done once in execution.py
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Mapping

from . import websocket
from .result_normalization import extract_tokens

# Injected by execution.py after it defines _stream_dict.
# Type: (value, *, run_id, step_name, direction, tenant_id) -> dict[str, Any]
_stream_dict_ref: Callable[..., dict[str, Any]] | None = None


def _get_stream_dict() -> Callable[..., dict[str, Any]]:
    """Return the injected stream-dict callable, raising if unset."""
    if _stream_dict_ref is None:
        raise RuntimeError(
            "_step_events._stream_dict_ref was not set by execution.py; "
            "import agentic_v2.server.execution before using _step_events."
        )
    return _stream_dict_ref


def _step_start_event(
    broadcast_step_data: Mapping[str, Any],
    *,
    run_id: str,
    step_name: str,
    tenant_id: str,
    now: str,
) -> dict[str, Any]:
    """Build a ``step_start`` broadcast payload for a single step."""
    stream_dict = _get_stream_dict()
    return {
        "type": "step_start",
        "run_id": run_id,
        "step": step_name,
        "input": stream_dict(
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
        except (ValueError, TypeError):
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
    stream_dict = _get_stream_dict()
    metadata_raw = broadcast_step_data.get("metadata")
    metadata = metadata_raw if isinstance(metadata_raw, Mapping) else {}
    model_used = metadata.get("model")
    if not isinstance(model_used, str):
        model_used = None
    tokens_used = extract_tokens(metadata)
    error_val = broadcast_step_data.get("error")

    output_dict = stream_dict(
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
        "input": stream_dict(
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
