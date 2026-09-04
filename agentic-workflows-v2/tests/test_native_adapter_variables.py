"""Regression tests for explicit variables on low-level native DAG execution.

Named YAML entry points validate inputs and seed the ``inputs`` namespace; their
behavior is covered in ``test_adapter_output_parity.py``.  The ``variables``
constructor remains supported for callers that build a dynamic DAG and choose
its context shape explicitly.
"""

from __future__ import annotations

import pytest

from agentic_v2.adapters import get_registry
from agentic_v2.contracts import StepStatus, WorkflowResult
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.dag import DAG
from agentic_v2.engine.step import StepDefinition


def test_execution_context_accepts_variables_kwarg() -> None:
    """``ExecutionContext(variables=...)`` seeds the variable store (root-cause
    guard)."""
    ctx = ExecutionContext(variables={"alpha": 1, "nested": {"k": "v"}})

    assert ctx.get_sync("alpha") == 1
    assert ctx.get_sync("nested") == {"k": "v"}
    # Omitting the kwarg leaves the store empty (no spurious seeding).
    assert ExecutionContext().get_sync("alpha", "missing") == "missing"


async def test_native_adapter_runs_workflow_with_seeded_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dynamic DAG can opt into flat variables through the low-level API."""
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")

    async def check_input(ctx: ExecutionContext) -> dict[str, object]:
        seen = ctx.get_sync("threshold")
        if seen != 7:
            raise AssertionError(f"seeded workflow input not visible to step: {seen!r}")
        return {"threshold_seen": seen}

    dag = DAG("native_variables_regression")
    dag.add(StepDefinition(name="check_input", func=check_input))

    ctx = ExecutionContext(variables={"threshold": 7})
    engine = get_registry().get_adapter("native")

    result = await engine.execute(dag, ctx)

    assert isinstance(result, WorkflowResult)
    assert result.overall_status == StepStatus.SUCCESS
    assert result.steps[0].step_name == "check_input"
    assert result.steps[0].status == StepStatus.SUCCESS
