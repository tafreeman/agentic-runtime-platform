"""Dataset-to-workflow matching and sample adaptation utilities.

Provides heuristic field-name matching to map dataset sample fields onto
workflow input schemas, input validation, and file materialization for
code/file-type inputs.

Key functions:

* :func:`match_workflow_dataset` -- verify that a dataset sample can
  satisfy a workflow's required inputs.
* :func:`adapt_sample_to_workflow_inputs` -- map dataset sample fields
  onto the workflow's input schema using heuristic matching.
* :func:`validate_required_inputs_present` -- check that all required
  workflow inputs have been provided.

This module was extracted from :mod:`~agentic_v2.server.datasets` to
keep file sizes manageable.  All public names are re-exported from
``datasets.py`` for backward compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..workflows.loader import (
    WorkflowDefinition,
    WorkflowInput,
)

# ---------------------------------------------------------------------------
# Text / value helpers
# ---------------------------------------------------------------------------


def _is_empty_value(value: Any) -> bool:
    """Check whether a value is effectively empty (None, blank string, or empty
    collection).

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


def _extract_message_text(
    sample: dict[str, Any],
    preferred_roles: tuple[str, ...] = ("user", "system", "assistant"),
) -> str | None:
    """Extract the best text snippet from chat-style ``messages`` in a dataset sample.

    Iterates through the ``messages`` list and returns the content of the
    first message matching a preferred role.  Falls back to the first
    message with non-empty content.

    Args:
        sample: A single dataset sample dict.
        preferred_roles: Role priority order for message selection.

    Returns:
        The extracted text string, or None if no messages are found.
    """
    messages = sample.get("messages")
    if not isinstance(messages, list):
        return None

    candidates: list[tuple[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        role = str(message.get("role", "")).lower()
        candidates.append((role, text))

    if not candidates:
        return None

    for role in preferred_roles:
        for candidate_role, text in candidates:
            if candidate_role == role:
                return text
    return candidates[0][1]


def _pick_first(sample: dict[str, Any], keys: list[str]) -> Any:
    """Return the first non-empty value found in the sample for any of the given keys.

    Searches the top-level sample dict, then ``sample["inputs"]``, then
    ``sample["input"]`` (if they are dicts).

    Args:
        sample: Dataset sample dict.
        keys: Ordered list of field names to try.

    Returns:
        The first non-empty value found, or None.
    """
    nested_inputs = sample.get("inputs")
    nested_input = sample.get("input")
    for key in keys:
        if key in sample and sample[key] not in (None, ""):
            return sample[key]
        if (
            isinstance(nested_inputs, dict)
            and key in nested_inputs
            and nested_inputs[key] not in (None, "")
        ):
            return nested_inputs[key]
        if (
            isinstance(nested_input, dict)
            and key in nested_input
            and nested_input[key] not in (None, "")
        ):
            return nested_input[key]
        if key == "input" and isinstance(nested_input, str) and nested_input.strip():
            return nested_input
    return None


# ---------------------------------------------------------------------------
# Heuristic field matching
# ---------------------------------------------------------------------------


def _dataset_value_for_input(
    input_name: str,
    input_def: WorkflowInput,
    dataset_sample: dict[str, Any],
) -> Any:
    """Resolve a single workflow input value from a dataset sample using heuristic field
    matching.

    Tries exact name match first, then semantic matching based on the
    input name (e.g., ``file`` inputs look for ``code_file``, ``patch``;
    ``spec`` inputs look for ``feature_spec``, ``task_description``).

    Args:
        input_name: Workflow input name.
        input_def: Workflow input definition (for type and default info).
        dataset_sample: The dataset sample dict to search.

    Returns:
        The resolved value, or None if no suitable match is found.
    """
    lowered = input_name.lower()
    explicit = dataset_sample.get(input_name)
    if explicit not in (None, ""):
        return explicit
    nested_inputs = dataset_sample.get("inputs")
    if isinstance(nested_inputs, dict):
        nested_value = nested_inputs.get(input_name)
        if nested_value not in (None, ""):
            return nested_value

    if "file" in lowered or "patch" in lowered:
        return _pick_first(
            dataset_sample,
            [
                "code_file",
                "file_path",
                "path",
                "source_path",
                "patch",
                "code",
                "body",
                "prompt",
                "task_description",
                "instruction",
                "input",
            ],
        )
    if "bug" in lowered or "report" in lowered or "issue" in lowered:
        value = _pick_first(
            dataset_sample,
            [
                "bug_report",
                "problem_statement",
                "issue_text",
                "issue_body",
                "description",
                "prompt",
                "task_description",
                "body",
                "instruction",
                "input",
                "question",
                "query",
                "request",
            ],
        )
        if value not in (None, ""):
            return value
        return _extract_message_text(dataset_sample)
    if "spec" in lowered or "requirement" in lowered:
        value = _pick_first(
            dataset_sample,
            [
                "feature_spec",
                "task_description",
                "prompt",
                "description",
                "instruction",
                "input",
                "question",
                "query",
                "request",
                "body",
            ],
        )
        if value not in (None, ""):
            return value
        return _extract_message_text(dataset_sample)
    if "tech_stack" in lowered and input_def.type == "object":
        stack = dataset_sample.get("tech_stack")
        if stack not in (None, ""):
            return stack
        if input_def.default not in (None, ""):
            return input_def.default

    if input_def.enum or input_def.default not in (None, ""):
        return input_def.default

    value = _pick_first(
        dataset_sample,
        [
            "prompt",
            "task_description",
            "problem_statement",
            "description",
            "body",
            "instruction",
            "input",
            "question",
            "query",
            "request",
            "issue_text",
            "content",
            "text",
            "code",
        ],
    )
    if value not in (None, ""):
        return value
    return _extract_message_text(dataset_sample)


# ---------------------------------------------------------------------------
# Workflow compatibility checking
# ---------------------------------------------------------------------------


def match_workflow_dataset(
    workflow_def: WorkflowDefinition,
    dataset_sample: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check whether a dataset sample can satisfy a workflow's required inputs.

    Verifies that every required input (without a default) and every
    capability-declared input can be resolved from the dataset sample
    via :func:`_dataset_value_for_input`.

    Args:
        workflow_def: Loaded workflow definition.
        dataset_sample: A single dataset sample dict.

    Returns:
        A 2-tuple of ``(is_compatible, sorted_list_of_missing_reason_strings)``.
    """
    if not isinstance(dataset_sample, dict):
        return False, ["invalid_dataset_sample"]

    missing_reasons: list[str] = []
    required_input_names = []
    for name, input_def in workflow_def.inputs.items():
        if not input_def.required:
            continue
        if input_def.default not in (None, ""):
            continue
        required_input_names.append(name)

    for input_name in required_input_names:
        value = _dataset_value_for_input(
            input_name,
            workflow_def.inputs[input_name],
            dataset_sample,
        )
        if _is_empty_value(value):
            missing_reasons.append(f"missing: {input_name}")

    caps = workflow_def.capabilities
    capability_inputs = (
        caps.get("inputs", [])
        if isinstance(caps, dict)
        else getattr(caps, "inputs", [])
    )
    if capability_inputs:
        for capability_input in capability_inputs:
            input_def = workflow_def.inputs.get(capability_input)
            if input_def is not None and input_def.default not in (None, ""):
                continue

            if input_def is not None:
                value = _dataset_value_for_input(
                    capability_input, input_def, dataset_sample
                )
            else:
                value = dataset_sample.get(capability_input)

            if _is_empty_value(value):
                missing_reasons.append(f"missing: {capability_input}")

    return len(missing_reasons) == 0, sorted(set(missing_reasons))


def validate_required_inputs_present(
    workflow_inputs: dict[str, WorkflowInput],
    provided_inputs: dict[str, Any],
) -> list[str]:
    """Return names of required workflow inputs that are missing or empty.

    Args:
        workflow_inputs: Full workflow input schema.
        provided_inputs: Actual input values provided for the run.

    Returns:
        List of missing required input names (empty if all present).
    """
    missing: list[str] = []
    for input_name, input_def in workflow_inputs.items():
        if not input_def.required:
            continue
        if input_def.default not in (None, ""):
            continue
        value = provided_inputs.get(input_name)
        if _is_empty_value(value):
            missing.append(input_name)
    return missing


# ---------------------------------------------------------------------------
# File materialization
# ---------------------------------------------------------------------------


def _materialize_file_input(
    value: Any,
    *,
    input_name: str,
    run_id: str,
    artifacts_dir: Path,
) -> Any:
    """Materialize a string value to a file on disk for file-type workflow inputs.

    If the value contains Python code markers (``def``, ``class``, ``import``),
    writes it as a ``.py`` file.  If it looks like a path, resolves it
    relative to ``artifacts_dir`` (with traversal prevention).  Otherwise,
    writes as a ``.txt`` file.

    Args:
        value: The string value to materialize.
        input_name: Workflow input name (used in the generated filename).
        run_id: Current run identifier (used in the generated filename).
        artifacts_dir: Directory where materialized files are written.

    Returns:
        The original value if not a string, or the path to the written file.
    """
    if not isinstance(value, str):
        return value

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root = artifacts_dir.resolve()

    looks_python = any(marker in value for marker in ("def ", "class ", "import "))

    if looks_python:
        suffix = ".py"
        file_path = artifacts_root / f"{run_id}_{input_name}{suffix}"
        file_path.write_text(value, encoding="utf-8")
        return str(file_path)

    candidate: Path | None = None
    if any(sep in value for sep in ("/", "\\")) or value.endswith((".py", ".txt")):
        try:
            candidate = (artifacts_root / value).resolve()
            try:
                candidate.relative_to(artifacts_root)
                if candidate.is_file():
                    return str(candidate)
            except ValueError:
                candidate = None
        except (OSError, ValueError):
            candidate = None

    suffix = ".py" if looks_python else ".txt"
    file_path = artifacts_root / f"{run_id}_{input_name}{suffix}"
    file_path.write_text(value, encoding="utf-8")
    return str(file_path)


# ---------------------------------------------------------------------------
# Sample adaptation
# ---------------------------------------------------------------------------


def adapt_sample_to_workflow_inputs(
    workflow_inputs: dict[str, WorkflowInput],
    sample: dict[str, Any],
    *,
    run_id: str,
    artifacts_dir: Path,
) -> dict[str, Any]:
    """Map dataset sample fields onto workflow input schema.

    For each workflow input, attempts heuristic field matching against the
    sample, applies type coercion (JSON parse for objects/arrays, stringify
    for dicts/lists into strings), and materializes file-type inputs to disk.

    Args:
        workflow_inputs: Workflow input definitions keyed by name.
        sample: Dataset sample dict to adapt.
        run_id: Current run identifier (for file materialization).
        artifacts_dir: Directory for materialized file artifacts.

    Returns:
        Dict of adapted input values keyed by workflow input name.
        Inputs that could not be resolved are omitted.
    """
    if not isinstance(sample, dict):
        return {}

    adapted: dict[str, Any] = {}
    generic_text = _pick_first(
        sample,
        [
            "prompt",
            "task_description",
            "problem_statement",
            "description",
            "body",
            "instruction",
            "input",
            "question",
            "query",
            "request",
            "issue_text",
            "content",
            "text",
            "code",
            "expected_output",
        ],
    )
    if generic_text in (None, ""):
        generic_text = _extract_message_text(sample)
    for name, definition in workflow_inputs.items():
        lowered = name.lower()
        explicit = sample.get(name)
        value = explicit

        if value in (None, ""):
            if "file" in lowered or "patch" in lowered:
                value = _pick_first(
                    sample,
                    [
                        "code_file",
                        "file_path",
                        "path",
                        "source_path",
                        "patch",
                        "code",
                        "body",
                        "prompt",
                        "task_description",
                    ],
                )
            elif "bug" in lowered or "report" in lowered or "issue" in lowered:
                value = _pick_first(
                    sample,
                    [
                        "bug_report",
                        "problem_statement",
                        "issue_text",
                        "issue_body",
                        "description",
                        "prompt",
                        "task_description",
                        "body",
                        "instruction",
                        "input",
                        "question",
                        "query",
                        "request",
                    ],
                )
                if value in (None, ""):
                    value = _extract_message_text(sample)
            elif "spec" in lowered or "requirement" in lowered:
                value = _pick_first(
                    sample,
                    [
                        "feature_spec",
                        "task_description",
                        "prompt",
                        "description",
                        "instruction",
                        "input",
                        "question",
                        "query",
                        "request",
                        "body",
                    ],
                )
                if value in (None, ""):
                    value = _extract_message_text(sample)
            elif "tech_stack" in lowered and definition.type == "object":
                value = sample.get("tech_stack") or {
                    "frontend": "react",
                    "backend": "fastapi",
                    "database": "postgresql",
                }
            else:
                if definition.default not in (None, ""):
                    value = definition.default
                elif definition.enum:
                    value = definition.enum[0]
                else:
                    value = generic_text

        if value in (None, ""):
            continue

        if definition.type == "string":
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            if "file" in lowered:
                value = _materialize_file_input(
                    value,
                    input_name=name,
                    run_id=run_id,
                    artifacts_dir=artifacts_dir,
                )
        elif definition.type in {"object", "array"} and isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                value = {"value": value}

        adapted[name] = value

    return adapted
