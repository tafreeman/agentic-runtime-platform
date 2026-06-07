"""LangChain integration for agentic-workflows-v2.

Provides adapters so V2 components work seamlessly with LangChain:
- AgenticChatModel: Use V2's LLMClientWrapper as a LangChain BaseChatModel
- AgenticTool: Wrap V2 BaseTool instances as LangChain tools
- AgenticAgent: Wrap a V2 BaseAgent as a LangChain Runnable
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import ConfigDict

logger = logging.getLogger(__name__)

try:
    from langchain_core.callbacks import CallbackManagerForLLMRun
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import (
        AIMessage,
        BaseMessage,
        HumanMessage,
        SystemMessage,
    )
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import BaseTool as LangChainBaseTool

    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

from ..models.client import LLMClientWrapper, get_client
from ..models.router import ModelTier
from ..tools.base import BaseTool as V2BaseTool
from ..tools.base import ToolResult


def _require_langchain():
    if not LANGCHAIN_AVAILABLE:
        raise ImportError(
            "langchain-core is required for LangChain integration. "
            "Install with: pip install langchain-core"
        )


# ---------------------------------------------------------------------------
# 1. Chat Model adapter
# ---------------------------------------------------------------------------

if LANGCHAIN_AVAILABLE:

    class AgenticChatModel(BaseChatModel):
        """LangChain ChatModel backed by V2's LLMClientWrapper + SmartModelRouter.

        Usage:
            from agentic_v2.integrations.langchain import AgenticChatModel

            llm = AgenticChatModel(tier=ModelTier.TIER_2)
            response = llm.invoke("Explain async/await in Python")
        """

        # Pydantic v2 fields
        tier: int = ModelTier.TIER_2
        _client: LLMClientWrapper | None = None

        model_config = ConfigDict(arbitrary_types_allowed=True)

        @property
        def _llm_type(self) -> str:
            return "agentic-v2"

        def _get_client(self) -> LLMClientWrapper:
            if self._client is None:
                self._client = get_client()
            return self._client

        def _messages_to_dicts(
            self, messages: list[BaseMessage]
        ) -> list[dict[str, str]]:
            """Convert LangChain messages to OpenAI-style dicts."""
            result = []
            for msg in messages:
                if isinstance(msg, SystemMessage):
                    result.append({"role": "system", "content": msg.content})
                elif isinstance(msg, HumanMessage):
                    result.append({"role": "user", "content": msg.content})
                elif isinstance(msg, AIMessage):
                    result.append({"role": "assistant", "content": msg.content})
                else:
                    result.append({"role": "user", "content": str(msg.content)})
            return result

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: CallbackManagerForLLMRun | None = None,
            **kwargs: Any,
        ) -> ChatResult:
            """Synchronous generation (runs async under the hood)."""
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._agenerate(messages, stop, run_manager, **kwargs)
                )
            finally:
                loop.close()

        async def _agenerate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: CallbackManagerForLLMRun | None = None,
            **kwargs: Any,
        ) -> ChatResult:
            """Async generation via V2 client."""
            client = self._get_client()

            if client.backend is None:
                raise RuntimeError(
                    "No LLM backend configured on LLMClientWrapper. "
                    "Set one with client.set_backend(backend)."
                )

            # Build a single prompt from messages
            msg_dicts = self._messages_to_dicts(messages)

            # Use chat completion if backend supports it
            tier = ModelTier(self.tier)
            model_name = client.router.get_model_for_tier(tier)
            if model_name is None:
                raise RuntimeError(f"No model available for tier {tier}")
            try:
                result, _, _ = await client.complete_chat(
                    messages=msg_dicts,
                    tier=tier,
                    model=model_name,
                    **kwargs,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                raise

            content = result.get("content", "")
            message = AIMessage(content=content)
            generation = ChatGeneration(message=message)
            return ChatResult(generations=[generation])

        @property
        def _identifying_params(self) -> dict[str, Any]:
            return {"tier": self.tier, "llm_type": self._llm_type}

    # ---------------------------------------------------------------------------
    # 2. Tool adapter
    # ---------------------------------------------------------------------------

    class AgenticLangChainTool(LangChainBaseTool):
        """Wrap a V2 BaseTool as a LangChain tool.

        Usage:
            from agentic_v2.tools.builtin.shell_ops import ShellTool
            from agentic_v2.integrations.langchain import AgenticLangChainTool

            lc_tool = AgenticLangChainTool.from_v2_tool(ShellTool())
        """

        name: str = ""
        description: str = ""
        _v2_tool: V2BaseTool | None = None

        model_config = ConfigDict(arbitrary_types_allowed=True)

        @classmethod
        def from_v2_tool(cls, tool: V2BaseTool) -> "AgenticLangChainTool":
            """Create a LangChain tool from a V2 tool instance."""
            instance = cls(name=tool.name, description=tool.description)
            instance._v2_tool = tool
            return instance

        def _run(self, **kwargs: Any) -> str:
            """Sync execution."""
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._arun(**kwargs))
            finally:
                loop.close()

        async def _arun(self, **kwargs: Any) -> str:
            """Async execution via V2 tool."""
            if self._v2_tool is None:
                return "Error: No V2 tool bound"
            result: ToolResult = await self._v2_tool.execute(**kwargs)
            if result.success:
                return json.dumps(result.data, default=str) if result.data else "OK"
            return f"Error: {result.error}"

    # ---------------------------------------------------------------------------
    # 3. Agent adapter (Runnable)
    # ---------------------------------------------------------------------------

    class AgenticRunnable:
        """Wrap a V2 BaseAgent as something chainable in LangChain.

        Usage:
            from agentic_v2.agents import CoderAgent
            from agentic_v2.integrations.langchain import AgenticRunnable

            runnable = AgenticRunnable(CoderAgent())
            result = await runnable.ainvoke({"task": "Write a hello world"})
        """

        def __init__(self, agent):
            self._agent = agent

        async def ainvoke(
            self, input_data: dict[str, Any], _config: Any | None = None
        ) -> dict[str, Any]:
            """Run the V2 agent and return output as dict."""
            # Build typed input from the agent's input class
            input_cls = self._agent.__class__.__orig_bases__[0].__args__[0]
            task = input_cls(**input_data)
            result = await self._agent.run(task)
            if hasattr(result, "model_dump"):
                return result.model_dump()
            return {"result": str(result)}

        def invoke(
            self, input_data: dict[str, Any], _config: Any | None = None
        ) -> dict[str, Any]:
            """Sync wrapper."""
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.ainvoke(input_data, _config))
            finally:
                loop.close()


# ---------------------------------------------------------------------------
# Public API (works even without langchain installed)
# ---------------------------------------------------------------------------

__all__ = [
    "LANGCHAIN_AVAILABLE",
    "AgenticChatModel",
    "AgenticLangChainTool",
    "AgenticRunnable",
]
