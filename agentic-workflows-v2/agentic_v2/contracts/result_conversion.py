"""Convert external step evidence into the shared result contract.

Recorded metadata takes precedence over supplemental token/model mappings.
Missing or unrecognized statuses fail closed. Conversion never mutates its
inputs and never derives a successful status from the presence of output.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

from .messages import StepResult, StepStatus


def as_dict(value: Any) -> dict[str, Any]:
    """Preserve mappings or wrap scalar evidence in a value field."""
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {} if value is None else {"value": value}


def coerce_step_status(value: Any) -> StepStatus:
    """Map known status aliases, defaulting to FAILED for missing evidence."""
    if isinstance(value, StepStatus):
        return value
    if not isinstance(value, str):
        return StepStatus.FAILED
    normalized = value.strip().lower()
    aliases = {
        "succeeded": StepStatus.SUCCESS,
        "completed": StepStatus.SUCCESS,
        "skip": StepStatus.SKIPPED,
        "queued": StepStatus.PENDING,
        "in_progress": StepStatus.RUNNING,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return StepStatus(normalized)
    except ValueError:
        return StepStatus.FAILED


def workflow_status(
    steps: list[StepResult],
    status: StepStatus = StepStatus.SUCCESS,
    *,
    has_errors: bool = False,
) -> StepStatus:
    """A workflow cannot succeed when its step evidence failed or is incomplete."""
    statuses = {step.status for step in steps}
    if has_errors or StepStatus.FAILED in statuses:
        return StepStatus.FAILED
    if status is not StepStatus.SUCCESS:
        return status
    for unfinished in (StepStatus.RUNNING, StepStatus.RETRYING, StepStatus.PENDING):
        if unfinished in statuses:
            return unfinished
    return StepStatus.SUCCESS


def _count(value: Any) -> int | None:
    """Accept nonnegative whole counts, including decimal strings."""
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    return value if type(value) is int and value >= 0 else None


def extract_tokens(metadata: Any) -> int | None:
    """Use a recorded total, then valid components; never invent usage."""
    if not isinstance(metadata, Mapping):
        return None
    for key in ("tokens_used", "total_tokens"):
        if key in metadata:
            return _count(metadata[key])
    components = [
        metadata[key] for key in ("input_tokens", "output_tokens") if key in metadata
    ]
    counts = [_count(value) for value in components]
    if not counts or any(value is None for value in counts):
        return None
    return sum(value for value in counts if value is not None)


def _metadata(recorded: Any, supplemental: Any) -> dict[str, Any]:
    metadata = as_dict(recorded) if isinstance(recorded, Mapping) else {}
    if isinstance(supplemental, Mapping):
        for key, alias in (("input_tokens", "input"), ("output_tokens", "output")):
            if key not in metadata and alias in supplemental:
                value = _count(supplemental[alias])
                if value is not None:
                    metadata[key] = value
    total = extract_tokens(metadata)
    if total is not None:
        metadata.setdefault("tokens_used", total)
    return metadata


def _text(*values: Any) -> str | None:
    return next((value for value in values if isinstance(value, str) and value), None)


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def build_step_results(
    steps_map: Any,
    *,
    token_counts: Mapping[str, Any] | None = None,
    models_used: Mapping[str, Any] | None = None,
) -> list[StepResult]:
    """Convert ordered raw step mappings, preserving recorded evidence."""
    if not isinstance(steps_map, Mapping):
        return []
    token_counts = token_counts if isinstance(token_counts, Mapping) else {}
    models_used = models_used if isinstance(models_used, Mapping) else {}
    results: list[StepResult] = []
    for name, step in steps_map.items():
        if not isinstance(step, Mapping) or not str(name):
            continue
        metadata = _metadata(step.get("metadata"), token_counts.get(name))
        tier = step.get("tier")
        retry_count = step.get("retry_count")
        error = step.get("error")
        results.append(
            StepResult(
                step_name=str(name),
                status=coerce_step_status(step.get("status")),
                agent_role=_text(step.get("agent_role"), step.get("agent")),
                tier=tier if type(tier) is int and 0 <= tier <= 5 else None,
                model_used=_text(
                    step.get("model_used"),
                    step.get("model"),
                    metadata.get("model_used"),
                    metadata.get("model"),
                    models_used.get(name),
                ),
                input_data=as_dict(step.get("inputs", step.get("input_data"))),
                output_data=as_dict(step.get("outputs", step.get("output_data"))),
                error=str(error) if error is not None else None,
                error_type=_text(step.get("error_type")),
                retry_count=(
                    retry_count if type(retry_count) is int and retry_count >= 0 else 0
                ),
                metadata=metadata,
                start_time=_timestamp(step.get("start_time")) or datetime.now(UTC),
                end_time=_timestamp(step.get("end_time")),
            )
        )
    return results


def extract_metadata(final_state: Any) -> tuple[dict[str, dict], dict[str, str]]:
    """Extract valid component counts and models without losing recorded zeros."""
    tokens: dict[str, dict] = {}
    models: dict[str, str] = {}
    steps = final_state.get("steps") if isinstance(final_state, Mapping) else None
    if not isinstance(steps, Mapping):
        return tokens, models
    for name, step in steps.items():
        if not isinstance(step, Mapping):
            continue
        metadata = _metadata(step.get("metadata"), None)
        counts = {}
        for key, alias in (("input_tokens", "input"), ("output_tokens", "output")):
            value = _count(metadata.get(key))
            if value is not None:
                counts[alias] = value
        if counts:
            tokens[str(name)] = {"input": 0, "output": 0, **counts}
        model = _text(
            step.get("model_used"),
            step.get("model"),
            metadata.get("model_used"),
            metadata.get("model"),
        )
        if model:
            models[str(name)] = model
    return tokens, models
