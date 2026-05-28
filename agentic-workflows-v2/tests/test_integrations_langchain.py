"""Tests for agentic_v2.integrations.langchain adapters.

ADR-008 Phase 3 — Tier 1 (branching, error paths) and Tier 2 (contracts,
boundaries) tests for the LangChain integration layer.

All external dependencies (langchain_core, LLM backends) are mocked so
these tests run without network access or installed providers.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_v2.integrations.langchain import (
    AgenticChatModel,
    AgenticLangChainTool,
    AgenticRunnable,
    _require_langchain,
)
from agentic_v2.tools.base import BaseTool, ToolResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeV2Tool(BaseTool):
    """Minimal V2 tool for testing the LangChain tool adapter."""

    @property
    def name(self) -> str:
        return "fake_tool"

    @property
    def description(self) -> str:
        return "A fake tool for tests"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"query": {"type": "string", "required": True}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        if kwargs.get("fail"):
            return ToolResult(success=False, error="deliberate failure")
        return ToolResult(success=True, data={"echo": kwargs.get("query", "")})


class _ErrorV2Tool(BaseTool):
    """Tool that raises during execute."""

    @property
    def name(self) -> str:
        return "error_tool"

    @property
    def description(self) -> str:
        return "Always raises"

    @property
    def parameters(self) -> dict[str, Any]:
        return {}

    async def execute(self, **kwargs: Any) -> ToolResult:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# _require_langchain
# ---------------------------------------------------------------------------


class TestRequireLangchain:
    """Tests for the _require_langchain guard function."""

    def test_does_not_raise_when_available(self):
        """ADR-008 Phase 3: guard passes when langchain is installed."""
        # langchain IS available in this test env, so no error expected
        _require_langchain()

    def test_raises_import_error_when_unavailable(self):
        """ADR-008 Phase 3: guard raises ImportError with install hint."""
        with patch("agentic_v2.integrations.langchain.LANGCHAIN_AVAILABLE", False):
            with pytest.raises(ImportError, match="langchain-core is required"):
                _require_langchain()


# ---------------------------------------------------------------------------
# AgenticChatModel
# ---------------------------------------------------------------------------


class TestAgenticChatModel:
    """Tests for the LangChain BaseChatModel adapter."""

    def test_llm_type_property(self):
        """ADR-008 Phase 3: _llm_type returns expected identifier."""
        model = AgenticChatModel(tier=2)
        assert model._llm_type == "agentic-v2"

    def test_identifying_params(self):
        """ADR-008 Phase 3: identifying params include tier and type."""
        model = AgenticChatModel(tier=3)
        params = model._identifying_params
        assert params["tier"] == 3
        assert params["llm_type"] == "agentic-v2"

    def test_messages_to_dicts_system(self):
        """ADR-008 Phase 3: SystemMessage maps to role=system."""
        from langchain_core.messages import SystemMessage

        model = AgenticChatModel()
        result = model._messages_to_dicts([SystemMessage(content="You are helpful")])
        assert result == [{"role": "system", "content": "You are helpful"}]

    def test_messages_to_dicts_human(self):
        """ADR-008 Phase 3: HumanMessage maps to role=user."""
        from langchain_core.messages import HumanMessage

        model = AgenticChatModel()
        result = model._messages_to_dicts([HumanMessage(content="Hello")])
        assert result == [{"role": "user", "content": "Hello"}]

    def test_messages_to_dicts_ai(self):
        """ADR-008 Phase 3: AIMessage maps to role=assistant."""
        from langchain_core.messages import AIMessage

        model = AgenticChatModel()
        result = model._messages_to_dicts([AIMessage(content="Hi there")])
        assert result == [{"role": "assistant", "content": "Hi there"}]

    def test_messages_to_dicts_unknown_type_falls_back_to_user(self):
        """ADR-008 Phase 3: unknown message type falls back to role=user."""
        from langchain_core.messages import ChatMessage

        model = AgenticChatModel()
        # ChatMessage is a BaseMessage subclass that is NOT System/Human/AI
        msg = ChatMessage(role="function", content="fallback content")
        result = model._messages_to_dicts([msg])
        assert result[0]["role"] == "user"
        assert "fallback content" in result[0]["content"]

    @pytest.mark.parametrize(
        "msg_types,expected_roles",
        [
            (["system", "human", "ai"], ["system", "user", "assistant"]),
            (["human", "human"], ["user", "user"]),
            (
                ["system", "ai", "human", "ai"],
                ["system", "assistant", "user", "assistant"],
            ),
        ],
        ids=["mixed-conversation", "double-user", "four-turn"],
    )
    def test_messages_to_dicts_multi_message(self, msg_types, expected_roles):
        """ADR-008 Phase 3: multi-message conversations preserve order and roles."""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        type_map = {
            "system": lambda c: SystemMessage(content=c),
            "human": lambda c: HumanMessage(content=c),
            "ai": lambda c: AIMessage(content=c),
        }
        model = AgenticChatModel()
        msgs = [type_map[t](f"msg-{i}") for i, t in enumerate(msg_types)]
        result = model._messages_to_dicts(msgs)
        roles = [r["role"] for r in result]
        assert roles == expected_roles

    async def test_agenerate_raises_when_no_backend(self):
        """ADR-008 Phase 3: _agenerate raises RuntimeError when backend is None."""
        from langchain_core.messages import HumanMessage

        model = AgenticChatModel(tier=2)
        mock_client = MagicMock()
        mock_client.backend = None
        model._client = mock_client

        with pytest.raises(RuntimeError, match="No LLM backend configured"):
            await model._agenerate([HumanMessage(content="test")])

    async def test_agenerate_raises_when_no_model_for_tier(self):
        """ADR-008 Phase 3: _agenerate raises RuntimeError when router has no model."""
        from langchain_core.messages import HumanMessage

        model = AgenticChatModel(tier=2)
        mock_client = MagicMock()
        mock_client.backend = MagicMock()  # not None
        mock_client.router.get_model_for_tier.return_value = None
        model._client = mock_client

        with pytest.raises(RuntimeError, match="No model available for tier"):
            await model._agenerate([HumanMessage(content="test")])

    async def test_agenerate_returns_chat_result(self):
        """ADR-008 Phase 3: _agenerate returns ChatResult with AIMessage."""
        from langchain_core.messages import HumanMessage
        from langchain_core.outputs import ChatResult

        model = AgenticChatModel(tier=2)
        mock_client = MagicMock()
        mock_client.backend = MagicMock()
        mock_client.router.get_model_for_tier.return_value = "test-model"
        mock_client.complete_chat = AsyncMock(
            return_value=({"content": "Generated response"}, "test-model", 10)
        )
        model._client = mock_client

        result = await model._agenerate([HumanMessage(content="hello")])

        assert isinstance(result, ChatResult)
        assert len(result.generations) == 1
        assert result.generations[0].message.content == "Generated response"

    async def test_agenerate_handles_empty_content(self):
        """ADR-008 Phase 3: _agenerate handles missing 'content' key gracefully."""
        from langchain_core.messages import HumanMessage

        model = AgenticChatModel(tier=2)
        mock_client = MagicMock()
        mock_client.backend = MagicMock()
        mock_client.router.get_model_for_tier.return_value = "test-model"
        mock_client.complete_chat = AsyncMock(return_value=({}, "test-model", 0))
        model._client = mock_client

        result = await model._agenerate([HumanMessage(content="hello")])
        assert result.generations[0].message.content == ""

    def test_get_client_lazily_initializes(self):
        """ADR-008 Phase 3: _get_client creates client on first call."""
        model = AgenticChatModel(tier=2)
        # Before calling _get_client, _client is None
        assert model._client is None
        client = model._get_client()
        assert client is not None
        # Second call returns same instance
        assert model._get_client() is client


# ---------------------------------------------------------------------------
# AgenticLangChainTool
# ---------------------------------------------------------------------------


class TestAgenticLangChainTool:
    """Tests for the V2 tool -> LangChain tool adapter."""

    def test_from_v2_tool_copies_name_and_description(self):
        """ADR-008 Phase 3: from_v2_tool transfers name and description."""
        v2_tool = _FakeV2Tool()
        lc_tool = AgenticLangChainTool.from_v2_tool(v2_tool)
        assert lc_tool.name == "fake_tool"
        assert lc_tool.description == "A fake tool for tests"

    async def test_arun_returns_json_on_success(self):
        """ADR-008 Phase 3: _arun returns JSON-serialized data on success."""
        v2_tool = _FakeV2Tool()
        lc_tool = AgenticLangChainTool.from_v2_tool(v2_tool)
        result = await lc_tool._arun(query="ping")
        parsed = json.loads(result)
        assert parsed == {"echo": "ping"}

    async def test_arun_returns_ok_when_no_data(self):
        """ADR-008 Phase 3: _arun returns 'OK' when result.data is None."""
        v2_tool = MagicMock(spec=BaseTool)
        v2_tool.name = "noop"
        v2_tool.description = "noop"
        v2_tool.execute = AsyncMock(return_value=ToolResult(success=True, data=None))
        lc_tool = AgenticLangChainTool.from_v2_tool(v2_tool)
        assert await lc_tool._arun() == "OK"

    async def test_arun_returns_error_string_on_failure(self):
        """ADR-008 Phase 3: _arun returns error message on failure."""
        v2_tool = _FakeV2Tool()
        lc_tool = AgenticLangChainTool.from_v2_tool(v2_tool)
        result = await lc_tool._arun(fail=True)
        assert result.startswith("Error:")
        assert "deliberate failure" in result

    async def test_arun_returns_error_when_no_tool_bound(self):
        """ADR-008 Phase 3: _arun returns error string when _v2_tool is None."""
        lc_tool = AgenticLangChainTool(name="empty", description="no tool")
        result = await lc_tool._arun()
        assert result == "Error: No V2 tool bound"


# ---------------------------------------------------------------------------
# AgenticRunnable
# ---------------------------------------------------------------------------


class TestAgenticRunnable:
    """Tests for the V2 agent -> LangChain Runnable adapter."""

    async def test_ainvoke_calls_agent_run(self):
        """ADR-008 Phase 3: ainvoke delegates to agent.run()."""
        mock_agent = MagicMock()
        # Simulate __orig_bases__ for input class discovery
        mock_input_cls = MagicMock()
        mock_agent.__class__.__orig_bases__ = [MagicMock(__args__=[mock_input_cls])]
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"answer": "42"}
        mock_agent.run = AsyncMock(return_value=mock_result)

        runnable = AgenticRunnable(mock_agent)
        output = await runnable.ainvoke({"task": "compute"})

        assert output == {"answer": "42"}
        mock_agent.run.assert_awaited_once()

    async def test_ainvoke_wraps_non_pydantic_result(self):
        """ADR-008 Phase 3: ainvoke wraps plain string results in dict."""
        mock_agent = MagicMock()
        mock_input_cls = MagicMock()
        mock_agent.__class__.__orig_bases__ = [MagicMock(__args__=[mock_input_cls])]
        # Return something without model_dump
        mock_agent.run = AsyncMock(return_value="plain text result")

        runnable = AgenticRunnable(mock_agent)
        output = await runnable.ainvoke({"task": "test"})

        assert output == {"result": "plain text result"}
