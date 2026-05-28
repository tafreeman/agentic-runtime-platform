"""Anthropic Messages API agent backed by the ``anthropic`` SDK.

Provides :class:`ClaudeAgent`, a :class:`~agentic_v2.agents.base.BaseAgent`
subclass that bridges the project's internal OpenAI-style message format
and :class:`~agentic_v2.tools.BaseTool` registry to the Anthropic Messages
API.  Registered tools are automatically converted to Anthropic tool
schemas, and responses are translated back into the ``{"content", "tool_calls"}``
dict format that :class:`~agentic_v2.agents.base.BaseAgent` expects.

Requires the ``anthropic`` package (install via
``pip install 'agentic-workflows-v2[claude]'``).

Example::

    from agentic_v2.agents.implementations import ClaudeAgent

    agent = ClaudeAgent(system_prompt="You are a helpful coding assistant.")
    result = await agent.run(task)
"""

from __future__ import annotations

from typing import Any

try:
    import anthropic
except ImportError as e:
    raise ImportError(
        "anthropic package is required: pip install 'agentic-workflows-v2[claude]'"
    ) from e

from ...contracts import TaskInput, TaskOutput
from ..base import AgentConfig, BaseAgent

# ---------------------------------------------------------------------------
# Default task/output types (override for typed agents)
# ---------------------------------------------------------------------------


class SimpleTask(TaskInput):
    """Minimal task input containing a single prompt string.

    Attributes:
        prompt: The user prompt to send to the agent.
    """

    prompt: str


class SimpleOutput(TaskOutput):
    """Minimal task output containing the agent's response text.

    Attributes:
        response: The full text response from the agent.
    """

    response: str


# ---------------------------------------------------------------------------
# ClaudeAgent
# ---------------------------------------------------------------------------


class ClaudeAgent(BaseAgent[SimpleTask, SimpleOutput]):
    """Concrete agent that calls Claude via the Anthropic Messages API.

    Inherits the full :class:`~agentic_v2.agents.base.BaseAgent` lifecycle
    (initialization, tool binding, conversation memory, event system) while
    routing LLM calls through the ``anthropic`` async client.

    Format translation is handled by three static methods:

    - :meth:`_convert_messages` -- splits the system prompt out of the
      message list (Anthropic requires it as a top-level parameter) and
      converts ``"tool"`` role messages to ``tool_result`` content blocks.
    - :meth:`_convert_tools` -- maps OpenAI function-tool schemas to
      Anthropic tool schemas.
    - :meth:`_convert_response` -- maps Anthropic response content blocks
      back to the internal ``{"content", "tool_calls"}`` dict format.

    Args:
        model: Claude model identifier (default ``"claude-opus-4-6"``).
        system_prompt: System-level instruction for the agent.
        config: Optional :class:`~agentic_v2.agents.base.AgentConfig`
            override.
        api_key: Anthropic API key. Falls back to the ``ANTHROPIC_API_KEY``
            environment variable when ``None``.
        **kwargs: Passed through to :class:`BaseAgent.__init__`.
    """

    def __init__(
        self,
        model: str = "claude-opus-4-6",
        system_prompt: str = "You are a helpful AI assistant.",
        config: AgentConfig | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ):
        cfg = config or AgentConfig(
            name="claude_agent",
            system_prompt=system_prompt,
        )
        super().__init__(config=cfg, **kwargs)
        self._model = model
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key
        )  # uses ANTHROPIC_API_KEY if None

    # ------------------------------------------------------------------
    # _call_model — translate formats and call Anthropic
    # ------------------------------------------------------------------

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        system, anthropic_messages = self._convert_messages(messages)
        anthropic_tools = self._convert_tools(tools or [])

        kwargs: dict[str, Any] = dict(
            model=self._model,
            max_tokens=4096,
            messages=anthropic_messages,
            thinking={"type": "adaptive"},
        )
        if system:
            kwargs["system"] = system
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        response = await self._client.messages.create(**kwargs)
        return self._convert_response(response)

    # ------------------------------------------------------------------
    # Format conversions
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Split system prompt out; convert tool-result messages."""
        system: str | None = None
        out: list[dict[str, Any]] = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                # Anthropic wants system as a top-level param
                system = msg["content"]
                continue

            if role == "tool":
                # OpenAI tool result → Anthropic tool_result content block
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": msg["content"],
                            }
                        ],
                    }
                )
                continue

            out.append({"role": role, "content": msg["content"]})

        return system, out

    @staticmethod
    def _convert_tools(
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """OpenAI function-tool schema → Anthropic tool schema."""
        result = []
        for t in tools:
            fn = t.get("function", {})
            result.append(
                {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                }
            )
        return result

    @staticmethod
    def _convert_response(response: Any) -> dict[str, Any]:
        """Anthropic response → internal {content, tool_calls} dict."""
        text = ""
        tool_calls: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "function": {
                            "name": block.name,
                            "arguments": block.input,  # already a dict
                        },
                    }
                )

        return {"content": text, "tool_calls": tool_calls or None}

    # ------------------------------------------------------------------
    # BaseAgent abstract methods
    # ------------------------------------------------------------------

    def _format_task_message(self, task: SimpleTask) -> str:
        return task.prompt

    async def _is_task_complete(self, task: SimpleTask, response: str) -> bool:
        return True  # single-turn by default; override for multi-turn

    async def _parse_output(self, task: SimpleTask, response: str) -> SimpleOutput:
        return SimpleOutput(response=response)
