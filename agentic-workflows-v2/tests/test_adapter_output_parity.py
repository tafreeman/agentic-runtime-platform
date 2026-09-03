"""Behavior-level parity checks for the shipped workflow adapters.

Provider-backed steps deliberately produce engine-specific placeholder payloads
under ``AGENTIC_NO_LLM=1``.  The stable parity contract is therefore:

* every shipped YAML is exercised by both registered adapters;
* workflow status and step topology match;
* declared outputs compare value-for-value after engine-specific no-LLM
  placeholders and omitted unresolved values are normalized to no value;
* branches controlled directly by workflow inputs make the same decisions; and
* deterministic workflows produce identical declared outputs.

The native CLI and server entry points are covered separately because both used
to seed workflow inputs as flat context variables.  Shipped YAML expressions
use the ``${inputs.*}`` namespace, so the old shape silently resolved values to
``None`` while still reporting successful execution.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.adapters import get_registry
from agentic_v2.cli.helpers import (
    _normalize_result,
    _NormalizedResult,
    _run_via_adapter,
)
from agentic_v2.server.execution import _run_via_native_adapter
from agentic_v2.workflows.loader import WorkflowLoader
from agentic_v2.workflows.runner import WorkflowValidationError


@dataclass(frozen=True)
class _ParityCase:
    inputs: dict[str, Any]
    input_driven_steps: dict[str, str] = field(default_factory=dict)
    expected_outputs: dict[str, Any] | None = None


_SOURCE_FILE = str(Path(__file__).resolve())
_PARITY_CASES = {
    "bug_resolution": _ParityCase(
        inputs={
            "bug_report": "A workflow input resolves to null",
            "code_file": _SOURCE_FILE,
            "resolution_depth": "quick",
        },
        input_driven_steps={
            "regression_check": "skipped",
            "generate_verification": "skipped",
        },
    ),
    "code_review": _ParityCase(
        inputs={"code_file": _SOURCE_FILE, "review_depth": "quick"},
        input_driven_steps={"generate_summary": "skipped"},
    ),
    "conditional_branching": _ParityCase(
        inputs={
            "feature_spec": "Add a health endpoint",
            "review_depth": "quick",
            "target_env": "development",
        },
        input_driven_steps={
            "quick_review": "success",
            "deep_analysis": "skipped",
            "security_scan": "skipped",
            "deployment_readiness": "skipped",
        },
    ),
    "consensus_review": _ParityCase(
        inputs={"code_file": _SOURCE_FILE, "min_agreement": "0.66"},
    ),
    "fullstack_generation": _ParityCase(
        inputs={"feature_spec": "Add a health endpoint"},
    ),
    "iterative_review": _ParityCase(
        inputs={"feature_spec": "Add a health endpoint", "max_review_rounds": 2},
    ),
    "test_deterministic": _ParityCase(
        inputs={"input_text": "Hello World"},
        expected_outputs={"processed_text": "Hello World", "step_count": 11},
    ),
    "test_workflow": _ParityCase(
        inputs={"input_text": "Hello World"},
        expected_outputs={"processed_text": "Hello World", "step_count": 11},
    ),
}


def _run_langchain(workflow_name: str, inputs: dict[str, Any]) -> _NormalizedResult:
    engine = get_registry().get_adapter("langchain")
    raw = asyncio.run(engine.execute(workflow_name, **inputs))
    return _normalize_result(workflow_name, raw, wall_clock=0.0)


def _normalize_no_llm_output(value: Any) -> Any:
    """Remove adapter-specific placeholder encoding from the parity oracle."""
    if isinstance(value, dict):
        if (
            value.get("placeholder") is True
            and value.get("reason") == "llm_unavailable"
        ):
            return None
        return {key: _normalize_no_llm_output(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_no_llm_output(item) for item in value]
    return value


def test_parity_matrix_covers_every_shipped_workflow() -> None:
    shipped = set(WorkflowLoader().list_workflows())

    assert set(_PARITY_CASES) == shipped


@pytest.mark.parametrize("workflow_name", sorted(_PARITY_CASES))
def test_shipped_workflow_adapter_parity(
    workflow_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    case = _PARITY_CASES[workflow_name]

    native = _run_via_adapter("native", workflow_name, case.inputs)
    langchain = _run_langchain(workflow_name, case.inputs)
    declared_outputs = set(WorkflowLoader().load(workflow_name).outputs)
    native_outputs = {
        output_name: _normalize_no_llm_output(native.outputs.get(output_name))
        for output_name in declared_outputs
    }
    langchain_outputs = {
        output_name: _normalize_no_llm_output(langchain.outputs.get(output_name))
        for output_name in declared_outputs
    }

    assert native.status == langchain.status
    assert set(native.steps) == set(langchain.steps)
    assert native_outputs == langchain_outputs

    for step_name, expected_status in case.input_driven_steps.items():
        assert native.steps[step_name]["status"] == expected_status
        assert langchain.steps[step_name]["status"] == expected_status

    if case.expected_outputs is not None:
        assert native.outputs == case.expected_outputs
        assert langchain.outputs == case.expected_outputs


def test_cli_native_entrypoint_validates_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")

    with pytest.raises(
        WorkflowValidationError, match="Missing required input 'input_text'"
    ):
        _run_via_adapter("native", "test_deterministic", {})


@pytest.mark.asyncio
async def test_server_native_entrypoint_returns_declared_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")

    result = await _run_via_native_adapter(
        "native",
        "test_deterministic",
        "parity-server-run",
        {"input_text": "Hello World"},
    )

    assert result.workflow_id == "parity-server-run"
    assert result.final_output == {
        "processed_text": "Hello World",
        "step_count": 11,
    }

    with pytest.raises(
        WorkflowValidationError, match="Missing required input 'input_text'"
    ):
        await _run_via_native_adapter(
            "native",
            "test_deterministic",
            "parity-server-invalid-run",
            {},
        )
