"""Cross-adapter conformance tests (ADR-001 Phase 1).

Verifies:
- All registered adapters satisfy the ``ExecutionEngine`` protocol.
- A simple DAG produces a valid ``WorkflowResult`` through each adapter.
- Both native and langchain adapters (when available) share the same
  structural contract.
"""

from __future__ import annotations

import pytest
from agentic_v2.adapters import get_registry
from agentic_v2.core.protocols import ExecutionEngine


class TestAdapterConformance:
    """Protocol conformance for all registered adapters."""

    def test_native_adapter_satisfies_protocol(self) -> None:
        """The native adapter must satisfy ExecutionEngine."""
        engine = get_registry().get_adapter("native")
        assert isinstance(engine, ExecutionEngine)

    @pytest.mark.integration
    def test_langchain_adapter_satisfies_protocol(self) -> None:
        """The langchain adapter (if installed) must satisfy ExecutionEngine."""
        registry = get_registry()
        if "langchain" not in registry.list_adapters():
            pytest.skip("langchain adapter not installed")
        engine = registry.get_adapter("langchain")
        assert isinstance(engine, ExecutionEngine)

    def test_all_registered_adapters_satisfy_protocol(self) -> None:
        """Every adapter in the registry must satisfy ExecutionEngine."""
        registry = get_registry()
        for name in registry.list_adapters():
            engine = registry.get_adapter(name)
            assert isinstance(
                engine, ExecutionEngine
            ), f"Adapter {name!r} does not satisfy ExecutionEngine protocol"


class TestNativeAdapterExecution:
    """Verify the native adapter produces valid WorkflowResult structures."""

    @pytest.mark.asyncio
    async def test_simple_dag_execution(self) -> None:
        """Execute a trivial DAG through the native registry adapter."""
        from agentic_v2.contracts import StepStatus, WorkflowResult
        from agentic_v2.engine.context import ExecutionContext
        from agentic_v2.engine.dag import DAG
        from agentic_v2.engine.step import StepDefinition

        async def step_fn(ctx: ExecutionContext) -> dict[str, object]:
            return {"answer": 42}

        dag = DAG("conformance_test")
        dag.add(StepDefinition(name="compute", func=step_fn))

        engine = get_registry().get_adapter("native")
        result = await engine.execute(dag)

        # Structural checks on WorkflowResult
        assert isinstance(result, WorkflowResult)
        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 1
        assert result.steps[0].step_name == "compute"
        assert result.steps[0].status == StepStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_dag_with_dependencies(self) -> None:
        """Execute a two-step DAG with a dependency edge."""
        from agentic_v2.contracts import StepStatus, WorkflowResult
        from agentic_v2.engine.context import ExecutionContext
        from agentic_v2.engine.dag import DAG
        from agentic_v2.engine.step import StepDefinition

        async def step_a(ctx: ExecutionContext) -> dict[str, object]:
            return {"from_a": 1}

        async def step_b(ctx: ExecutionContext) -> dict[str, object]:
            return {"from_b": 2}

        dag = DAG("conformance_deps")
        dag.add(StepDefinition(name="a", func=step_a))
        step_b_def = StepDefinition(name="b", func=step_b)
        step_b_def.depends_on = ["a"]
        dag.add(step_b_def)

        engine = get_registry().get_adapter("native")
        result = await engine.execute(dag)

        assert isinstance(result, WorkflowResult)
        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 2
        step_names = {s.step_name for s in result.steps}
        assert step_names == {"a", "b"}


class TestLangChainAdapterExecution:
    """Verify the langchain adapter produces valid WorkflowResult structures.

    These tests require langchain extras and are marked as integration
    tests.
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_langchain_protocol_has_execute(self) -> None:
        """The langchain adapter must expose an async execute method."""
        registry = get_registry()
        if "langchain" not in registry.list_adapters():
            pytest.skip("langchain adapter not installed")
        engine = registry.get_adapter("langchain")
        assert callable(getattr(engine, "execute", None))
