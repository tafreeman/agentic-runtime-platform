"""Tests for core Protocol definitions (Sprint 1.2).

Verifies:
- All existing executors satisfy ``ExecutionEngine`` via structural subtyping.
- Protocols are importable from both ``core/`` (canonical) and ``engine/``
  (backward-compat shim).
- New Protocols (AgentProtocol, ToolProtocol, MemoryStore) have correct shape.
- Negative cases: classes that DON'T match the protocol fail isinstance checks.
"""

from __future__ import annotations

from agentic_v2.core.protocols import (
    AgentProtocol,
    ExecutionEngine,
    MemoryStore,
    SupportsCheckpointing,
    SupportsStreaming,
    ToolProtocol,
)

# ── ExecutionEngine Protocol ──────────────────────────────────────────


class TestExecutionEngineProtocol:
    """Verify ExecutionEngine conformance for all three native executors."""

    def test_dag_executor_satisfies_protocol(self):
        from agentic_v2.engine.dag_executor import DAGExecutor

        assert isinstance(DAGExecutor(), ExecutionEngine)

    def test_pipeline_executor_satisfies_protocol(self):
        from agentic_v2.engine.pipeline import PipelineExecutor

        assert isinstance(PipelineExecutor(), ExecutionEngine)

    def test_workflow_executor_satisfies_protocol(self):
        from agentic_v2.engine.executor import WorkflowExecutor

        assert isinstance(WorkflowExecutor(), ExecutionEngine)

    def test_non_conforming_class_fails(self):
        class _NotAnEngine:
            pass

        assert not isinstance(_NotAnEngine(), ExecutionEngine)

    def test_wrong_method_name_fails(self):
        class _WrongMethod:
            async def run(self, workflow, ctx=None, **kwargs):
                pass

        assert not isinstance(_WrongMethod(), ExecutionEngine)


# ── Backward-compat shim ──────────────────────────────────────────────


class TestBackwardCompatShim:
    """Verify engine/protocol.py re-exports from core/protocols.py."""

    def test_import_from_engine_protocol(self):
        from agentic_v2.core.protocols import ExecutionEngine as CoreEE
        from agentic_v2.engine.protocol import ExecutionEngine as EngineEE

        assert EngineEE is CoreEE

    def test_import_from_engine_protocol_streaming(self):
        from agentic_v2.core.protocols import SupportsStreaming as CoreSS
        from agentic_v2.engine.protocol import SupportsStreaming as EngineSS

        assert EngineSS is CoreSS

    def test_import_from_engine_protocol_checkpointing(self):
        from agentic_v2.core.protocols import SupportsCheckpointing as CoreCP
        from agentic_v2.engine.protocol import SupportsCheckpointing as EngineCP

        assert EngineCP is CoreCP


# ── SupportsStreaming / SupportsCheckpointing ─────────────────────────


class TestOptionalCapabilities:
    """Verify optional capability protocols."""

    def test_dag_executor_does_not_support_streaming(self):
        from agentic_v2.engine.dag_executor import DAGExecutor

        assert not isinstance(DAGExecutor(), SupportsStreaming)

    def test_dag_executor_does_not_support_checkpointing(self):
        from agentic_v2.engine.dag_executor import DAGExecutor

        assert not isinstance(DAGExecutor(), SupportsCheckpointing)

    def test_conforming_streaming_class(self):
        class _Streamer:
            async def execute(self, workflow, ctx=None, on_update=None, **kw):
                pass

            async def stream(self, workflow, ctx=None, **kw):
                pass

        assert isinstance(_Streamer(), SupportsStreaming)

    def test_conforming_checkpointing_class(self):
        class _Checkpointer:
            async def execute(self, workflow, ctx=None, on_update=None, **kw):
                pass

            def get_checkpoint_state(self, workflow, *, thread_id, **kw):
                return None

            async def resume(self, workflow, *, thread_id, ctx=None, **kw):
                pass

        assert isinstance(_Checkpointer(), SupportsCheckpointing)


# ── AgentProtocol ─────────────────────────────────────────────────────


class TestAgentProtocol:
    """Verify AgentProtocol conformance."""

    def test_conforming_agent(self):
        class _TestAgent:
            @property
            def name(self) -> str:
                return "test"

            async def run(self, input_data, ctx=None):
                return {"result": "ok"}

        assert isinstance(_TestAgent(), AgentProtocol)

    def test_missing_name_property_fails(self):
        class _NoName:
            async def run(self, input_data, ctx=None):
                return {}

        assert not isinstance(_NoName(), AgentProtocol)


# ── ToolProtocol ──────────────────────────────────────────────────────


class TestToolProtocol:
    """Verify ToolProtocol conformance."""

    def test_conforming_tool(self):
        class _TestTool:
            @property
            def name(self) -> str:
                return "test_tool"

            @property
            def description(self) -> str:
                return "A test tool"

            async def execute(self, **kwargs):
                return "done"

        assert isinstance(_TestTool(), ToolProtocol)

    def test_missing_description_fails(self):
        class _NoDesc:
            @property
            def name(self) -> str:
                return "test"

            async def execute(self, **kwargs):
                return "done"

        assert not isinstance(_NoDesc(), ToolProtocol)


# ── MemoryStore ───────────────────────────────────────────────────────


class TestMemoryStore:
    """Verify MemoryStore conformance (now aliases MemoryStoreProtocol)."""

    def test_conforming_memory_store(self):
        class _InMemoryStore:
            async def store(self, key, value, *, metadata=None):
                pass

            async def retrieve(self, key):
                return None

            async def search(self, query, *, top_k=5):
                return []

            async def delete(self, key):
                return False

            async def list_keys(self, *, prefix=None):
                return []

        assert isinstance(_InMemoryStore(), MemoryStore)

    def test_missing_search_fails(self):
        class _Incomplete:
            async def store(self, key, value, *, metadata=None):
                pass

            async def retrieve(self, key):
                return None

            async def delete(self, key):
                return False

        assert not isinstance(_Incomplete(), MemoryStore)


# ── AgentProtocol.run signature ──────────────────────────────────────


class TestProtocolSignatures:
    """Verify no Any in core protocol method signatures."""

    def test_agent_protocol_run_no_any_in_signature(self):
        """run() must not use Any for input_data or return type."""
        annotations = AgentProtocol.run.__annotations__

        input_data_ann = annotations.get("input_data", "")
        assert input_data_ann != "Any", (
            "AgentProtocol.run parameter 'input_data' must not be typed as Any"
        )

        return_ann = annotations.get("return", "")
        assert return_ann != "Any", (
            "AgentProtocol.run return type must not be Any"
        )

    def test_tool_protocol_execute_no_any_in_signature(self):
        """execute() **kwargs and return type must not be typed as Any."""
        from agentic_v2.core.protocols import ToolProtocol

        annotations = ToolProtocol.execute.__annotations__

        return_ann = annotations.get("return", "")
        assert return_ann != "Any", (
            "ToolProtocol.execute return type must not be Any"
        )

        kwargs_ann = annotations.get("kwargs", "")
        assert kwargs_ann != "Any", (
            "ToolProtocol.execute **kwargs must not be typed as Any"
        )

    def test_protocol_type_hints_resolve_without_import_cycles(self):
        """Protocol annotations must be introspectable at runtime."""
        from typing import get_type_hints

        from agentic_v2.core.protocols import (
            DetectorProtocol,
            MiddlewareProtocol,
            VerifierProtocol,
        )

        assert get_type_hints(ExecutionEngine.execute)
        assert get_type_hints(SupportsCheckpointing.resume)
        assert get_type_hints(SupportsStreaming.stream)
        assert get_type_hints(AgentProtocol.run)
        assert get_type_hints(DetectorProtocol.scan)
        assert get_type_hints(MiddlewareProtocol.process)
        assert get_type_hints(VerifierProtocol.verify)


# ── Core module imports ───────────────────────────────────────────────


class TestCoreModuleExports:
    """Verify that core/__init__.py exports all expected types."""

    def test_protocols_available(self):
        from agentic_v2.core import (  # noqa: F401
            AgentProtocol,
            ExecutionEngine,
            MemoryStore,
            SupportsCheckpointing,
            SupportsStreaming,
            ToolProtocol,
        )

    def test_contracts_available(self):
        from agentic_v2.core import (  # noqa: F401
            StepResult,
            StepStatus,
            TaskInput,
            TaskOutput,
            WorkflowResult,
        )

    def test_context_available(self):
        from agentic_v2.core import (  # noqa: F401
            EventType,
            ExecutionContext,
            ServiceContainer,
        )

    def test_dag_available(self):
        from agentic_v2.core import (  # noqa: F401
            DAG,
            CycleDetectedError,
            MissingDependencyError,
        )

    def test_errors_available(self):
        from agentic_v2.core import (  # noqa: F401
            AdapterError,
            AdapterNotFoundError,
            AgenticError,
            SchemaValidationError,
            StepError,
            WorkflowError,
        )
