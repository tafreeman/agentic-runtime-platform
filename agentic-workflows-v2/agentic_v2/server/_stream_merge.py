"""Stream state merging helpers for LangGraph node updates.

Incrementally merges node update payloads (context, outputs, steps, errors)
into a mutable aggregate state dict produced by :func:`_stream_and_run`.
"""

from __future__ import annotations

from typing import Any, Mapping


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
