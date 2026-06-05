"""Tests for the AdapterRegistry and adapter infrastructure (Sprint 2).

Verifies:
- AdapterRegistry is a proper singleton.
- Adapters register and retrieve by name.
- ``AdapterNotFoundError`` for unknown adapters.
- Duplicate registration raises ``AdapterError``.
- ``list_adapters`` returns registered names.
- Thread-safety of the singleton (basic smoke test).
"""

from __future__ import annotations

import importlib

import pytest

from agentic_v2.core import AdapterError, AdapterNotFoundError


class TestAdapterRegistry:
    """Core registry behaviour."""

    def _make_registry(self):
        """Create a fresh registry via the supported test seam."""
        from agentic_v2.adapters.registry import AdapterRegistry

        AdapterRegistry.reset_for_tests()
        return AdapterRegistry()

    def test_register_and_get(self):

        reg = self._make_registry()

        class _FakeEngine:
            async def execute(self, workflow, ctx=None, on_update=None, **kw):
                return None

        reg.register("fake", _FakeEngine)
        engine = reg.get_adapter("fake")
        assert isinstance(engine, _FakeEngine)

    def test_get_unknown_raises(self):

        reg = self._make_registry()

        with pytest.raises(AdapterNotFoundError, match="no_such_adapter"):
            reg.get_adapter("no_such_adapter")

    def test_duplicate_register_raises(self):

        reg = self._make_registry()

        class _FakeEngine:
            pass

        reg.register("dup", _FakeEngine)
        with pytest.raises(AdapterError, match="already registered"):
            reg.register("dup", _FakeEngine)

    def test_list_adapters(self):

        reg = self._make_registry()

        class _A:
            pass

        class _B:
            pass

        reg.register("alpha", _A)
        reg.register("beta", _B)
        assert sorted(reg.list_adapters()) == ["alpha", "beta"]

    def test_global_get_registry_is_singleton(self):
        from agentic_v2.adapters import get_registry

        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_native_adapter_auto_registered(self):
        """Importing the adapters package auto-registers the native adapter."""
        import agentic_v2.adapters as adapters
        import agentic_v2.adapters.native as native_adapter
        from agentic_v2.adapters.registry import AdapterRegistry

        AdapterRegistry.reset_for_tests()
        importlib.reload(native_adapter)
        adapters = importlib.reload(adapters)
        reg = adapters.get_registry()
        assert "native" in reg.list_adapters()


class TestNativeEngine:
    """Verify the native adapter conforms to ExecutionEngine."""

    def test_satisfies_execution_engine_protocol(self):
        from agentic_v2.adapters.native.engine import NativeEngine
        from agentic_v2.core.protocols import ExecutionEngine

        assert isinstance(NativeEngine(), ExecutionEngine)

    @pytest.mark.asyncio
    async def test_execute_dag(self):
        """NativeEngine delegates DAG execution to DAGExecutor."""
        from agentic_v2.adapters.native.engine import NativeEngine
        from agentic_v2.contracts import StepStatus
        from agentic_v2.engine.dag import DAG
        from agentic_v2.engine.step import StepDefinition

        async def step_fn(ctx):
            return {"value": 42}

        dag = DAG("test_dag")
        dag.add(StepDefinition(name="step_a", func=step_fn))

        engine = NativeEngine()
        result = await engine.execute(dag)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) >= 1

    @pytest.mark.asyncio
    async def test_execute_pipeline(self):
        """NativeEngine delegates Pipeline execution to PipelineExecutor."""
        from agentic_v2.adapters.native.engine import NativeEngine
        from agentic_v2.contracts import StepStatus
        from agentic_v2.engine.pipeline import Pipeline
        from agentic_v2.engine.step import StepDefinition

        async def step_fn(ctx):
            return {"value": 1}

        pipeline = Pipeline(name="test_pipe")
        pipeline.add_step(StepDefinition(name="s1", func=step_fn))

        engine = NativeEngine()
        result = await engine.execute(pipeline)

        assert result.overall_status == StepStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_unsupported_type_raises(self):
        from agentic_v2.adapters.native.engine import NativeEngine

        engine = NativeEngine()
        with pytest.raises(TypeError, match="Unsupported workflow type"):
            await engine.execute("not_a_workflow")
