"""Behavioral tests for the BaseAgent ReAct loop (P1 #9).

Exercises the reason -> act -> observe -> continue path end-to-end without any
network: a stub :class:`BaseAgent` subclass scripts ``_call_model`` so we can
assert that

* a tool call is normalized + executed via the shared
  :mod:`agentic_v2.engine.tool_execution` helpers,
* its serialized result lands in conversation memory as a ``tool``-role message,
* the loop iterates the expected number of times and emits events in order, and
* both OpenAI-shape and Anthropic-shape tool calls flow through the same path.

It also covers :class:`ClaudeAgent`'s ``stop_reason``-driven completion logic and
its direct-SDK inbound sanitization (the indirect-prompt-injection vector) with a
mocked Anthropic client.

All offline. No live keys, no network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agentic_v2.agents.base import BaseAgent
from agentic_v2.agents.config import AgentConfig, AgentEvent
from agentic_v2.agents.implementations.claude_agent import (
    ClaudeAgent,
    SimpleOutput,
    SimpleTask,
)
from agentic_v2.tools.base import BaseTool, ToolResult

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _EchoTool(BaseTool):
    """Tier-0 tool that echoes its ``text`` arg back as ToolResult.data."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo back the provided text."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "text": {
                "type": "string",
                "description": "Text to echo",
                "required": True,
            }
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            success=True,
            data={"echoed": kwargs.get("text")},
            tool_name="echo",
        )


class _ScriptedAgent(BaseAgent[SimpleTask, SimpleOutput]):
    """BaseAgent whose ``_call_model`` returns scripted responses in order.

    ``complete_after`` controls ``_is_task_complete``: it returns ``False`` for
    the first ``complete_after - 1`` text turns, then ``True`` — letting tests
    drive multi-iteration completion deterministically.
    """

    def __init__(
        self,
        script: list[dict[str, Any]],
        *,
        complete_after: int = 1,
        config: AgentConfig | None = None,
    ) -> None:
        super().__init__(config=config or AgentConfig(name="scripted"))
        self._script = list(script)
        self.model_calls: list[list[dict[str, Any]]] = []
        self._complete_after = complete_after
        self._text_turns = 0

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.model_calls.append(list(messages))
        return self._script.pop(0)

    def _format_task_message(self, task: SimpleTask) -> str:
        return task.prompt

    async def _is_task_complete(self, task: SimpleTask, response: str) -> bool:
        self._text_turns += 1
        return self._text_turns >= self._complete_after

    async def _parse_output(self, task: SimpleTask, response: str) -> SimpleOutput:
        return SimpleOutput(response=response, success=True)


def _openai_tool_call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def _anthropic_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Block-style Anthropic tool_use call (no ``function`` wrapper, no id)."""
    return {
        "content": "",
        "tool_calls": [{"type": "tool_use", "name": name, "input": args}],
    }


def _final(content: str) -> dict[str, Any]:
    return {"content": content, "tool_calls": None}


async def _run_with_bound_tool(
    agent: _ScriptedAgent, tool: BaseTool, task: SimpleTask
) -> SimpleOutput:
    """Initialize the agent, bind ``tool`` directly, then run ``task``."""
    await agent.initialize()
    agent.bind_tool(tool)
    return await agent.run(task)


# ---------------------------------------------------------------------------
# 1. tool -> observe -> continue
# ---------------------------------------------------------------------------


async def test_tool_call_executes_and_result_lands_in_memory() -> None:
    tool = _EchoTool()
    agent = _ScriptedAgent(
        [
            _openai_tool_call("echo", {"text": "ping"}, "call-1"),
            _final("the tool said ping"),
        ]
    )

    result = await _run_with_bound_tool(agent, tool, SimpleTask(prompt="use echo"))

    # The tool executed exactly once with the scripted args.
    assert tool.calls == [{"text": "ping"}]
    # Exactly two model calls: one to request the tool, one to finish.
    assert len(agent.model_calls) == 2
    assert result.response == "the tool said ping"

    # The serialized result landed in memory as a tool-role message.
    tool_msgs = [m for m in agent.memory.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    payload = json.loads(tool_msgs[0].content)
    assert payload["success"] is True
    assert payload["data"] == {"echoed": "ping"}
    assert payload["tool_name"] == "echo"
    assert tool_msgs[0].tool_call_id == "call-1"


# ---------------------------------------------------------------------------
# 2. multi-iteration completion
# ---------------------------------------------------------------------------


async def test_multi_iteration_completion() -> None:
    agent = _ScriptedAgent(
        [_final("draft answer"), _final("final answer")],
        complete_after=2,
    )
    await agent.initialize()

    result = await agent.run(SimpleTask(prompt="think twice"))

    assert len(agent.model_calls) == 2
    assert result.response == "final answer"


# ---------------------------------------------------------------------------
# 3. max_iterations breach
# ---------------------------------------------------------------------------


async def test_max_iterations_raises_runtime_error() -> None:
    agent = _ScriptedAgent(
        [_final("never done"), _final("still not done")],
        complete_after=99,  # _is_task_complete never returns True
        config=AgentConfig(name="capped", max_iterations=2),
    )
    await agent.initialize()

    with pytest.raises(RuntimeError, match="max iterations"):
        await agent.run(SimpleTask(prompt="loop forever"))


# ---------------------------------------------------------------------------
# 4. event emission order
# ---------------------------------------------------------------------------


async def test_event_emission_order() -> None:
    tool = _EchoTool()
    agent = _ScriptedAgent(
        [
            _openai_tool_call("echo", {"text": "x"}, "c1"),
            _final("done"),
        ]
    )

    seen: list[AgentEvent] = []

    def handler(_agent: BaseAgent, event: AgentEvent, _data: dict[str, Any]) -> None:
        if event in {
            AgentEvent.THINKING,
            AgentEvent.TOOL_CALLED,
            AgentEvent.TOOL_RESULT,
        }:
            seen.append(event)

    agent.on_event(handler)
    await _run_with_bound_tool(agent, tool, SimpleTask(prompt="use echo"))

    # First turn: THINKING -> TOOL_CALLED -> TOOL_RESULT; second turn: THINKING.
    assert seen == [
        AgentEvent.THINKING,
        AgentEvent.TOOL_CALLED,
        AgentEvent.TOOL_RESULT,
        AgentEvent.THINKING,
    ]


# ---------------------------------------------------------------------------
# 5. Anthropic-shape tool call normalized by the shared path
# ---------------------------------------------------------------------------


async def test_anthropic_shape_tool_call_is_normalized() -> None:
    tool = _EchoTool()
    agent = _ScriptedAgent(
        [
            _anthropic_tool_call("echo", {"text": "block"}),
            _final("done"),
        ]
    )

    await _run_with_bound_tool(agent, tool, SimpleTask(prompt="use echo"))

    # Block-style call (no function wrapper, no id) still executed the tool.
    assert tool.calls == [{"text": "block"}]
    tool_msgs = [m for m in agent.memory.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    # normalize_tool_call auto-generated a deterministic call id.
    assert tool_msgs[0].tool_call_id
    payload = json.loads(tool_msgs[0].content)
    assert payload["data"] == {"echoed": "block"}


async def test_invalid_tool_params_report_error_without_raising() -> None:
    """Missing required param is reported back as a tool result, not raised."""
    tool = _EchoTool()
    agent = _ScriptedAgent(
        [
            _openai_tool_call("echo", {}, "bad-1"),  # missing required 'text'
            _final("recovered"),
        ]
    )

    result = await _run_with_bound_tool(agent, tool, SimpleTask(prompt="use echo"))

    # Validation failed before execute -> tool never ran.
    assert tool.calls == []
    assert result.response == "recovered"
    tool_msgs = [m for m in agent.memory.messages if m.role == "tool"]
    payload = json.loads(tool_msgs[0].content)
    assert payload["success"] is False
    assert "Invalid parameters" in payload["error"]


# ---------------------------------------------------------------------------
# 5b. OTel span construction reads the agent name from config
# ---------------------------------------------------------------------------


class _RecordingTracer:
    """No-op tracer that records the span name passed to start_as_current_span."""

    def __init__(self) -> None:
        self.span_names: list[str] = []

    def start_as_current_span(self, name: str) -> Any:
        self.span_names.append(name)
        from contextlib import nullcontext

        return nullcontext()


async def test_run_under_tracer_uses_config_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a tracer injected, run() must not raise AttributeError (C-11).

    Regression: the OTel span used ``self.name`` which does not exist on
    BaseAgent; the identifier lives at ``self.config.name``. Any run under an
    enabled tracer crashed with AttributeError before the fix.
    """
    tracer = _RecordingTracer()
    monkeypatch.setattr(
        "agentic_v2.agents.base._get_tracer", lambda: tracer, raising=True
    )

    agent = _ScriptedAgent(
        [_final("done")],
        config=AgentConfig(name="traced-agent"),
    )
    await agent.initialize()

    result = await agent.run(SimpleTask(prompt="hello"))

    assert result.response == "done"
    # The span was opened exactly once and its name carries the config name.
    assert tracer.span_names == ["agent.traced-agent"]


# ---------------------------------------------------------------------------
# 6. ClaudeAgent stop_reason -> completion
# ---------------------------------------------------------------------------


def _claude_agent() -> ClaudeAgent:
    """A ClaudeAgent with a dummy API key (no client call is made here)."""
    return ClaudeAgent(api_key="test-key-not-used")


@pytest.mark.parametrize(
    ("stop_reason", "expected_complete"),
    [
        ("end_turn", True),
        ("stop_sequence", True),
        ("max_tokens", False),
        (None, True),  # backward-compatible single-turn default
    ],
)
async def test_claude_is_task_complete_honors_stop_reason(
    stop_reason: str | None, expected_complete: bool
) -> None:
    agent = _claude_agent()
    agent._last_stop_reason = stop_reason

    complete = await agent._is_task_complete(SimpleTask(prompt="hi"), "answer")

    assert complete is expected_complete


def _anthropic_text_response(text: str, stop_reason: str | None) -> Any:
    """Build a minimal stand-in for an Anthropic Messages response object."""

    class _Block:
        type = "text"

        def __init__(self, value: str) -> None:
            self.text = value

    class _Response:
        def __init__(self) -> None:
            self.content = [_Block(text)]
            self.stop_reason = stop_reason

    return _Response()


async def test_claude_convert_response_captures_stop_reason() -> None:
    response = _anthropic_text_response("hello", "end_turn")
    converted = ClaudeAgent._convert_response(response)

    assert converted["content"] == "hello"
    assert converted["stop_reason"] == "end_turn"
    assert converted["tool_calls"] is None


async def test_claude_call_model_stashes_stop_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_call_model captures stop_reason from the live response onto the agent."""
    agent = _claude_agent()
    await agent.initialize()

    async def _fake_create(**_kwargs: Any) -> Any:
        return _anthropic_text_response("the answer", "max_tokens")

    monkeypatch.setattr(agent._client.messages, "create", _fake_create)

    result = await agent._call_model(
        [{"role": "user", "content": "question"}], tools=None
    )

    assert result["stop_reason"] == "max_tokens"
    assert agent._last_stop_reason == "max_tokens"
    # max_tokens means the output was truncated -> not complete.
    assert await agent._is_task_complete(SimpleTask(prompt="q"), "the answer") is False


async def test_claude_max_tokens_continuation_aggregates_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response split across max_tokens turns is reassembled in the output.

    BaseAgent._execute_loop hands only the LAST turn's content to
    _parse_output; without buffering, the earlier truncated segments would be
    silently dropped from the final SimpleOutput.
    """
    agent = _claude_agent()
    await agent.initialize()

    script = [
        _anthropic_text_response("part one, ", "max_tokens"),
        _anthropic_text_response("part two, ", "max_tokens"),
        _anthropic_text_response("the end.", "end_turn"),
    ]

    async def _fake_create(**_kwargs: Any) -> Any:
        return script.pop(0)

    monkeypatch.setattr(agent._client.messages, "create", _fake_create)

    output = await agent.run(SimpleTask(prompt="write something long"))

    assert output.response == "part one, part two, the end."
    assert script == []  # all three turns consumed
    # Buffer is reset so a reused agent does not leak chunks into the next run.
    assert agent._continuation_chunks == []


async def test_claude_single_turn_output_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain end_turn answer is returned verbatim (no aggregation involved)."""
    agent = _claude_agent()
    await agent.initialize()

    async def _fake_create(**_kwargs: Any) -> Any:
        return _anthropic_text_response("just the answer", "end_turn")

    monkeypatch.setattr(agent._client.messages, "create", _fake_create)

    output = await agent.run(SimpleTask(prompt="quick question"))
    assert output.response == "just the answer"


# ---------------------------------------------------------------------------
# 7. ClaudeAgent inbound sanitization over a malicious tool result
# ---------------------------------------------------------------------------


class _BlockingSanitizer:
    """Sanitizer stub that blocks any content containing 'EVIL' (fail-closed)."""

    async def process(
        self, content: str, context: dict[str, object] | None = None
    ) -> Any:
        from agentic_v2.contracts.sanitization import (
            Classification,
            SanitizationResult,
        )

        safe = "EVIL" not in content
        return SanitizationResult(
            classification=Classification.CLEAN if safe else Classification.BLOCKED,
            findings=(),
            sanitized_text=content if safe else None,
            original_hash=SanitizationResult.compute_hash(content),
        )


async def test_claude_call_model_sanitizes_inbound_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malicious tool-result message fails closed before any SDK call."""
    agent = _claude_agent()
    await agent.initialize()
    # Attach a blocking sanitizer to the shared client (same wiring path
    # _maybe_attach_agent_loop_sanitization uses).
    agent.llm_client.sanitization = _BlockingSanitizer()  # type: ignore[assignment]

    create_calls = {"n": 0}

    async def _fake_create(**_kwargs: Any) -> Any:
        create_calls["n"] += 1
        return _anthropic_text_response("should not run", "end_turn")

    monkeypatch.setattr(agent._client.messages, "create", _fake_create)

    messages = [
        {"role": "user", "content": "summarize"},
        {"role": "tool", "content": "EVIL injected instructions"},
    ]

    with pytest.raises(ValueError, match="sanitization"):
        await agent._call_model(messages, tools=None)

    # Fail-closed: the Anthropic SDK was never reached.
    assert create_calls["n"] == 0


async def test_claude_call_model_passes_clean_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A benign tool-result message passes inbound sanitization and reaches the SDK."""
    agent = _claude_agent()
    await agent.initialize()
    agent.llm_client.sanitization = _BlockingSanitizer()  # type: ignore[assignment]

    captured: dict[str, Any] = {}

    async def _fake_create(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _anthropic_text_response("clean answer", "end_turn")

    monkeypatch.setattr(agent._client.messages, "create", _fake_create)

    result = await agent._call_model(
        [
            {"role": "user", "content": "summarize"},
            {"role": "tool", "content": "harmless search result"},
        ],
        tools=None,
    )

    assert result["content"] == "clean answer"
    assert captured  # SDK was reached with the sanitized messages
