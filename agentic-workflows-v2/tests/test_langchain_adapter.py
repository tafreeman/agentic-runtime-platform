"""Tests for the LangChain execution engine adapter (Sprint 3).

Verifies:
- ``LangChainEngine`` satisfies ``ExecutionEngine`` protocol.
- ``LangChainEngine`` satisfies ``SupportsStreaming`` protocol.
- Auto-registration: ``"langchain"`` appears in ``registry.list_adapters()``.
- ``execute()`` delegates to ``WorkflowRunner.run()`` with correct args.
- ``execute()`` rejects non-string workflow arguments with ``TypeError``.
- ``stream()`` delegates to ``WorkflowRunner.astream()`` and returns async iterator.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentic_v2.contracts import StepStatus, WorkflowResult
from agentic_v2.core.protocols import ExecutionEngine, SupportsStreaming

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_result(workflow_name: str = "test_workflow") -> WorkflowResult:
    """Create a minimal ``WorkflowResult`` for mocking."""
    return WorkflowResult(
        workflow_id="run-001",
        workflow_name=workflow_name,
        steps=[],
        overall_status=StepStatus.SUCCESS,
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        final_output={"answer": 42},
    )


def _make_isolated_registry():
    """Create a fresh registry instance using the supported test seam."""
    from agentic_v2.adapters.registry import AdapterRegistry

    AdapterRegistry.reset_for_tests()
    return AdapterRegistry()


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestLangChainEngineProtocol:
    """Verify LangChainEngine satisfies the required protocols."""

    def test_satisfies_execution_engine_protocol(self) -> None:
        """LangChainEngine must be recognised as an ``ExecutionEngine``."""
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        engine = LangChainEngine()
        assert isinstance(engine, ExecutionEngine)

    def test_satisfies_supports_streaming_protocol(self) -> None:
        """LangChainEngine must be recognised as ``SupportsStreaming``."""
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        engine = LangChainEngine()
        assert isinstance(engine, SupportsStreaming)


# ---------------------------------------------------------------------------
# Auto-registration
# ---------------------------------------------------------------------------


class TestLangChainAdapterRegistration:
    """Verify the langchain adapter auto-registers when imported."""

    def test_langchain_in_registry(self) -> None:
        """Importing ``adapters.langchain`` registers the ``'langchain'`` name."""
        reg = _make_isolated_registry()

        # Manually trigger registration into our isolated registry
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        reg.register("langchain", LangChainEngine)
        assert "langchain" in reg.list_adapters()

    def test_global_registry_has_langchain(self) -> None:
        """The global registry should contain ``'langchain'`` after import."""
        import agentic_v2.adapters as adapters
        import agentic_v2.adapters.langchain as langchain_adapter
        from agentic_v2.adapters.registry import AdapterRegistry

        AdapterRegistry.reset_for_tests()
        importlib.reload(langchain_adapter)
        adapters = importlib.reload(adapters)
        reg = adapters.get_registry()
        assert "langchain" in reg.list_adapters()


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------


class TestLangChainEngineExecute:
    """Tests for LangChainEngine.execute()."""

    @pytest.mark.asyncio
    async def test_execute_delegates_to_runner(self) -> None:
        """``execute()`` calls ``WorkflowRunner.run()`` and returns result."""
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        expected = _make_fake_result("code_review")

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=expected)

        engine = LangChainEngine(runner=mock_runner)
        result = await engine.execute("code_review", ctx=None)

        mock_runner.run.assert_awaited_once_with("code_review", ctx=None)
        assert result is expected
        assert result.workflow_name == "code_review"

    @pytest.mark.asyncio
    async def test_execute_passes_kwargs_to_runner(self) -> None:
        """Extra kwargs from execute() are forwarded to WorkflowRunner.run()."""
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        expected = _make_fake_result()
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=expected)

        engine = LangChainEngine(runner=mock_runner)
        result = await engine.execute(
            "code_review",
            ctx=None,
            code_file="example.py",
        )

        mock_runner.run.assert_awaited_once_with(
            "code_review", ctx=None, code_file="example.py"
        )
        assert result is expected

    @pytest.mark.asyncio
    async def test_execute_non_string_workflow_raises_type_error(self) -> None:
        """Passing a non-string workflow to ``execute()`` raises ``TypeError``."""
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        engine = LangChainEngine()
        with pytest.raises(TypeError, match="workflow name must be a string"):
            await engine.execute(12345)

    @pytest.mark.asyncio
    async def test_execute_with_on_update_callback(self) -> None:
        """``execute()`` accepts an ``on_update`` callback without error."""
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        expected = _make_fake_result()
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=expected)

        callback = AsyncMock()

        engine = LangChainEngine(runner=mock_runner)
        result = await engine.execute("test_wf", on_update=callback)

        assert result is expected


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------


class TestLangChainEngineStream:
    """Tests for LangChainEngine.stream()."""

    @pytest.mark.asyncio
    async def test_stream_returns_async_iterator(self) -> None:
        """``stream()`` must return an async iterator of events."""
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        events = [
            {"step": "plan", "status": "started"},
            {"step": "plan", "status": "done"},
        ]

        async def _fake_astream(
            workflow_name: str, **kwargs: Any
        ) -> AsyncIterator[dict[str, Any]]:
            for event in events:
                yield event

        mock_runner = MagicMock()
        mock_runner.astream = _fake_astream

        engine = LangChainEngine(runner=mock_runner)
        collected: list[dict[str, Any]] = []
        async for event in engine.stream("code_review"):
            collected.append(event)

        assert collected == events

    @pytest.mark.asyncio
    async def test_stream_non_string_workflow_raises_type_error(self) -> None:
        """Passing a non-string workflow to ``stream()`` raises ``TypeError``."""
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        engine = LangChainEngine()
        with pytest.raises(TypeError, match="workflow name must be a string"):
            async for _ in engine.stream(42):
                pass

    @pytest.mark.asyncio
    async def test_stream_passes_kwargs(self) -> None:
        """Extra kwargs from ``stream()`` are forwarded to
        ``WorkflowRunner.astream()``."""
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        captured_kwargs: dict[str, Any] = {}

        async def _fake_astream(
            workflow_name: str, *, ctx: Any = None, **kwargs: Any
        ) -> AsyncIterator[dict[str, Any]]:
            # ctx is now always forwarded by the engine; capture the rest
            captured_kwargs.update(kwargs)
            captured_kwargs["ctx"] = ctx
            yield {"done": True}

        mock_runner = MagicMock()
        mock_runner.astream = _fake_astream

        engine = LangChainEngine(runner=mock_runner)
        async for _ in engine.stream("wf", topic="testing"):
            pass

        # ctx=None is forwarded alongside the extra kwargs
        assert captured_kwargs.get("topic") == "testing"
        assert captured_kwargs.get("ctx") is None
