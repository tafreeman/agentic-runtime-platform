"""Tests for human-approval gates on the tool-execution hot path (P1 #12).

Covers the injectable :class:`ApprovalProvider` abstraction and its enforcement
at BOTH dispatch points:

* the engine tool loop —
  :func:`agentic_v2.engine.tool_execution._dispatch_single_tool_call`, and
* the agent loop — :meth:`agentic_v2.agents.base.BaseAgent._dispatch_tool`.

The agent path is driven via a scripted ``BaseAgent`` subclass mirroring the
stub pattern in ``tests/test_agent_react_loop.py``. All offline, no network.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agentic_v2.agents.base import BaseAgent
from agentic_v2.agents.config import AgentConfig
from agentic_v2.agents.implementations.claude_agent import SimpleOutput, SimpleTask
from agentic_v2.engine.tool_execution import _dispatch_single_tool_call
from agentic_v2.governance.approval import (
    ApprovalDecision,
    ApprovalRequest,
    AutoApproveProvider,
    AutoDenyProvider,
    CallbackApprovalProvider,
    PolicyApprovalProvider,
    evaluate_tool_approval,
    set_approval_provider,
    tool_requires_approval,
)
from agentic_v2.tools.base import BaseTool, ToolResult

# Async tests are auto-detected (asyncio_mode = "auto" in pyproject.toml); a
# module-level asyncio mark would spuriously warn on the sync tests below.


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _SpyTool(BaseTool):
    """Tier-0 tool that records every execution.

    ``requires_approval`` settable.
    """

    def __init__(self, *, name: str = "spy", requires_approval: bool = False) -> None:
        super().__init__()
        self._name = name
        self._requires_approval = requires_approval
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Spy tool that records calls."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "text": {
                "type": "string",
                "description": "Text to echo",
                "required": True,
            }
        }

    @property
    def requires_approval(self) -> bool:
        return self._requires_approval

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            success=True, data={"echoed": kwargs.get("text")}, tool_name=self._name
        )


class _ScriptedAgent(BaseAgent[SimpleTask, SimpleOutput]):
    """BaseAgent whose ``_call_model`` returns scripted responses in order."""

    def __init__(
        self,
        script: list[dict[str, Any]],
        *,
        complete_after: int = 1,
        config: AgentConfig | None = None,
    ) -> None:
        super().__init__(config=config or AgentConfig(name="scripted"))
        self._script = list(script)
        self._complete_after = complete_after
        self._text_turns = 0

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
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


def _final(content: str) -> dict[str, Any]:
    return {"content": content, "tool_calls": None}


@pytest.fixture(autouse=True)
def _clear_provider_and_settings():
    """Reset the global provider and settings cache around every test."""
    import agentic_v2.settings as settings_mod

    set_approval_provider(None)
    settings_mod.get_settings.cache_clear()
    try:
        yield
    finally:
        set_approval_provider(None)
        settings_mod.get_settings.cache_clear()


async def _agent_dispatch(tool: BaseTool, args: dict[str, Any]) -> dict[str, Any]:
    """Drive the agent path: build an agent, dispatch one tool, return payload."""
    agent = _ScriptedAgent([_final("done")])
    await agent.initialize()
    agent.bind_tool(tool)
    result_str = await agent._dispatch_tool(tool, tool.name, args, "call-test")
    return json.loads(result_str)


async def _engine_dispatch(tool: BaseTool, args: dict[str, Any]) -> dict[str, Any]:
    """Drive the engine path: dispatch one tool, return parsed payload."""
    result_str = await _dispatch_single_tool_call(tool, tool.name, args)
    return json.loads(result_str)


# Parametrize the shared cases over both dispatch points.
_DISPATCHERS = [
    pytest.param(_engine_dispatch, id="engine"),
    pytest.param(_agent_dispatch, id="agent"),
]


# ---------------------------------------------------------------------------
# a. gated + AutoApprove -> executes normally
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dispatch", _DISPATCHERS)
async def test_gated_tool_auto_approve_executes(dispatch) -> None:
    set_approval_provider(AutoApproveProvider())
    tool = _SpyTool(requires_approval=True)

    payload = await dispatch(tool, {"text": "hi"})

    assert tool.calls == [{"text": "hi"}]
    assert payload["success"] is True
    assert payload["data"] == {"echoed": "hi"}


# ---------------------------------------------------------------------------
# b. gated + AutoDeny -> tool never executes, error mentions approval
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dispatch", _DISPATCHERS)
async def test_gated_tool_auto_deny_blocks_execution(dispatch) -> None:
    set_approval_provider(AutoDenyProvider())
    tool = _SpyTool(requires_approval=True)

    payload = await dispatch(tool, {"text": "hi"})

    assert tool.calls == []  # execute NEVER called
    assert payload["success"] is False
    assert "approval" in payload["error"].lower()
    assert payload["metadata"]["approval_decision"] == "denied"


# ---------------------------------------------------------------------------
# c. gated + NO provider -> fail-closed deny, never executes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dispatch", _DISPATCHERS)
async def test_gated_tool_no_provider_fails_closed(dispatch) -> None:
    set_approval_provider(None)
    tool = _SpyTool(requires_approval=True)

    payload = await dispatch(tool, {"text": "hi"})

    assert tool.calls == []
    assert payload["success"] is False
    assert "no provider" in payload["error"].lower()
    assert payload["metadata"]["approval_decision"] == "denied"
    assert payload["metadata"]["approval_provider"] == "no provider registered"


# ---------------------------------------------------------------------------
# d. ungated tool + no provider -> executes (no regression)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dispatch", _DISPATCHERS)
async def test_ungated_tool_executes_without_provider(dispatch) -> None:
    set_approval_provider(None)
    tool = _SpyTool(requires_approval=False)

    payload = await dispatch(tool, {"text": "hi"})

    assert tool.calls == [{"text": "hi"}]
    assert payload["success"] is True


# ---------------------------------------------------------------------------
# e. global override gates a normally-ungated tool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dispatch", _DISPATCHERS)
async def test_global_override_gates_ungated_tool(dispatch, monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_REQUIRE_TOOL_APPROVAL", "1")
    import agentic_v2.settings as settings_mod

    settings_mod.get_settings.cache_clear()
    set_approval_provider(AutoDenyProvider())
    tool = _SpyTool(requires_approval=False)

    payload = await dispatch(tool, {"text": "hi"})

    assert tool.calls == []
    assert payload["success"] is False
    assert "approval" in payload["error"].lower()


# ---------------------------------------------------------------------------
# f. per-name settings gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dispatch", _DISPATCHERS)
async def test_per_name_setting_gates_tool(dispatch, monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_APPROVAL_REQUIRED_TOOLS", "other, my_tool ")
    import agentic_v2.settings as settings_mod

    settings_mod.get_settings.cache_clear()
    set_approval_provider(AutoDenyProvider())
    tool = _SpyTool(name="my_tool", requires_approval=False)

    payload = await dispatch(tool, {"text": "hi"})

    assert tool.calls == []
    assert payload["success"] is False

    # A different tool name is NOT gated.
    other = _SpyTool(name="unlisted", requires_approval=False)
    other_payload = await dispatch(other, {"text": "hi"})
    assert other.calls == [{"text": "hi"}]
    assert other_payload["success"] is True


# ---------------------------------------------------------------------------
# g. CallbackApprovalProvider with async per-request decisions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dispatch", _DISPATCHERS)
async def test_callback_provider_async_per_request(dispatch) -> None:
    async def decide(request: ApprovalRequest) -> ApprovalDecision:
        if request.tool_name == "tool_a":
            return ApprovalDecision.APPROVED
        return ApprovalDecision.DENIED

    set_approval_provider(CallbackApprovalProvider(decide))

    tool_a = _SpyTool(name="tool_a", requires_approval=True)
    tool_b = _SpyTool(name="tool_b", requires_approval=True)

    payload_a = await dispatch(tool_a, {"text": "a"})
    payload_b = await dispatch(tool_b, {"text": "b"})

    assert tool_a.calls == [{"text": "a"}]
    assert payload_a["success"] is True
    assert tool_b.calls == []
    assert payload_b["success"] is False


async def test_callback_provider_sync_callable() -> None:
    """A sync callback is wrapped transparently."""

    def decide(_request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision.APPROVED

    set_approval_provider(CallbackApprovalProvider(decide))
    tool = _SpyTool(requires_approval=True)

    payload = await _engine_dispatch(tool, {"text": "hi"})
    assert payload["success"] is True
    assert tool.calls == [{"text": "hi"}]


# ---------------------------------------------------------------------------
# PolicyApprovalProvider
# ---------------------------------------------------------------------------


async def test_policy_provider_allowlist() -> None:
    set_approval_provider(PolicyApprovalProvider(frozenset({"allowed"})))

    allowed = _SpyTool(name="allowed", requires_approval=True)
    blocked = _SpyTool(name="blocked", requires_approval=True)

    assert (await _engine_dispatch(allowed, {"text": "x"}))["success"] is True
    assert (await _engine_dispatch(blocked, {"text": "x"}))["success"] is False
    assert allowed.calls == [{"text": "x"}]
    assert blocked.calls == []


# ---------------------------------------------------------------------------
# i. destructive builtins are flagged; read-only are not
# ---------------------------------------------------------------------------


def test_destructive_builtins_require_approval() -> None:
    from agentic_v2.tools.builtin.build_ops import BuildAppTool
    from agentic_v2.tools.builtin.code_execution import CodeExecutionTool
    from agentic_v2.tools.builtin.file_ops import (
        DirectoryCreateTool,
        FileCopyTool,
        FileDeleteTool,
        FileMoveTool,
        FileReadTool,
        FileWriteTool,
    )
    from agentic_v2.tools.builtin.http_ops import (
        HttpGetTool,
        HttpPostTool,
        HttpTool,
    )
    from agentic_v2.tools.builtin.shell_ops import ShellExecTool, ShellTool

    for cls in (
        BuildAppTool,
        ShellTool,
        ShellExecTool,
        CodeExecutionTool,
        FileWriteTool,
        FileDeleteTool,
        FileMoveTool,
        FileCopyTool,
        DirectoryCreateTool,
        HttpTool,
        HttpPostTool,
    ):
        assert cls().requires_approval is True, cls.__name__

    # Read-only tools stay un-gated.
    assert FileReadTool().requires_approval is False
    assert HttpGetTool().requires_approval is False


async def test_build_app_gate_fires_before_execute() -> None:
    """build_app is denied (fail-closed) before its shell phases ever run.

    Regression for the A2 gap: BuildAppTool ran install/build/test shell
    commands with no approval gate. The gate must be consulted *before* execute.
    """
    from agentic_v2.tools.builtin.build_ops import BuildAppTool

    executed = {"ran": False}

    class _SpyBuildApp(BuildAppTool):
        async def execute(self, **kwargs: Any) -> ToolResult:
            executed["ran"] = True
            return await super().execute(**kwargs)

    set_approval_provider(AutoDenyProvider())
    tool = _SpyBuildApp()

    payload = await _engine_dispatch(tool, {"project_root": ".", "dry_run": True})

    assert executed["ran"] is False  # gate fired before execute ran
    assert payload["success"] is False
    assert "approval" in payload["error"].lower()
    assert payload["metadata"]["approval_decision"] == "denied"


async def test_build_app_no_provider_fails_closed() -> None:
    """No provider registered → build_app fails closed, never executes."""
    from agentic_v2.tools.builtin.build_ops import BuildAppTool

    set_approval_provider(None)
    tool = BuildAppTool()

    payload = await _engine_dispatch(tool, {"project_root": ".", "dry_run": True})

    assert payload["success"] is False
    assert "no provider" in payload["error"].lower()
    assert payload["metadata"]["approval_decision"] == "denied"


def test_tool_requires_approval_helper() -> None:
    """The shared helper OR's the per-tool flag with settings triggers."""
    gated = _SpyTool(requires_approval=True)
    ungated = _SpyTool(requires_approval=False)

    assert tool_requires_approval(gated, gated.name) is True
    assert tool_requires_approval(ungated, ungated.name) is False


# ---------------------------------------------------------------------------
# ApprovalRequest redaction
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# LangChain adapter dispatch is gated (CRITICAL-1)
# ---------------------------------------------------------------------------


async def test_langchain_adapter_gated_tool_denied_never_executes() -> None:
    """A gated V2 tool wrapped via AgenticLangChainTool is denied, never runs."""
    from agentic_v2.integrations.langchain import (
        LANGCHAIN_AVAILABLE,
        AgenticLangChainTool,
    )

    if not LANGCHAIN_AVAILABLE:  # pragma: no cover — langchain-core is a dep
        pytest.skip("langchain-core not installed")

    set_approval_provider(AutoDenyProvider())
    tool = _SpyTool(name="gated", requires_approval=True)
    lc_tool = AgenticLangChainTool.from_v2_tool(tool)

    result = await lc_tool._arun(text="hi")

    assert tool.calls == []  # execute NEVER called
    assert result.startswith("Error:")
    assert "approval" in result.lower()


async def test_langchain_adapter_gated_tool_no_provider_fails_closed() -> None:
    """No provider registered → wrapped gated tool fails closed, never runs."""
    from agentic_v2.integrations.langchain import (
        LANGCHAIN_AVAILABLE,
        AgenticLangChainTool,
    )

    if not LANGCHAIN_AVAILABLE:  # pragma: no cover
        pytest.skip("langchain-core not installed")

    set_approval_provider(None)
    tool = _SpyTool(name="gated", requires_approval=True)
    lc_tool = AgenticLangChainTool.from_v2_tool(tool)

    result = await lc_tool._arun(text="hi")

    assert tool.calls == []
    assert result.startswith("Error:")
    assert "no provider" in result.lower()


async def test_langchain_adapter_ungated_tool_unaffected() -> None:
    """An ungated wrapped tool executes normally even with no provider."""
    from agentic_v2.integrations.langchain import (
        LANGCHAIN_AVAILABLE,
        AgenticLangChainTool,
    )

    if not LANGCHAIN_AVAILABLE:  # pragma: no cover
        pytest.skip("langchain-core not installed")

    set_approval_provider(None)
    tool = _SpyTool(name="ungated", requires_approval=False)
    lc_tool = AgenticLangChainTool.from_v2_tool(tool)

    result = await lc_tool._arun(text="hi")

    assert tool.calls == [{"text": "hi"}]
    assert not result.startswith("Error:")


# ---------------------------------------------------------------------------
# Denied call emits exactly one TOOL_RESULT through _handle_tool_calls (HIGH-2)
# ---------------------------------------------------------------------------


async def test_denied_call_emits_single_tool_result_event() -> None:
    """A denied tool call yields exactly one TOOL_RESULT via _handle_tool_calls.

    Regression: ``_dispatch_tool`` previously emitted its own TOOL_RESULT on
    denial in addition to the canonical one emitted by ``_handle_tool_calls``,
    producing two events per denied call.
    """
    set_approval_provider(AutoDenyProvider())
    tool = _SpyTool(name="gated", requires_approval=True)

    agent = _ScriptedAgent([_final("done")])
    await agent.initialize()
    agent.bind_tool(tool)

    events: list[tuple[str, dict[str, Any]]] = []

    def _record(_agent: Any, event: Any, data: dict[str, Any]) -> None:
        events.append((event.value, data))

    agent.on_event(_record)

    await agent._handle_tool_calls(
        [_openai_tool_call("gated", {"text": "hi"}, "call-1")["tool_calls"][0]]
    )

    tool_result_events = [d for name, d in events if name == "tool_result"]
    assert len(tool_result_events) == 1
    assert tool.calls == []  # tool never executed
    # The denial metadata travels in the serialized result string.
    payload = json.loads(tool_result_events[0]["result"])
    assert payload["success"] is False
    assert payload["metadata"]["approval_decision"] == "denied"
    assert tool_result_events[0]["call_id"] == "call-1"


def test_approval_request_redacts_long_args() -> None:
    payload = "x" * 5000
    request = ApprovalRequest(
        tool_name="file_write",
        tool_args={"content": payload, "path": "/tmp/a"},
        call_id="c1",
        agent_or_step="writer",
    )
    text = str(request)
    assert payload not in text
    assert "redacted" in text
    assert "/tmp/a" in text  # short value not redacted
    assert "file_write" in text


async def test_approval_times_out_and_denies_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung provider must fail closed (DENIED) within the configured timeout.

    Without a bound, ``evaluate_tool_approval`` would await ``request_approval``
    forever, blocking the gated tool and consuming the step's whole timeout
    budget. With ``agentic_approval_timeout_seconds`` set, the gate denies on
    timeout instead of hanging.
    """
    import agentic_v2.settings as settings_mod

    monkeypatch.setenv("AGENTIC_APPROVAL_TIMEOUT_SECONDS", "0.05")
    settings_mod.get_settings.cache_clear()

    class _HangingProvider:
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            await asyncio.sleep(60)  # never resolves within the test's timeout
            return ApprovalDecision.APPROVED

    set_approval_provider(_HangingProvider())
    tool = _SpyTool(requires_approval=True)

    # Outer 5s bound so a regression (no timeout) fails fast instead of hanging.
    outcome = await asyncio.wait_for(
        evaluate_tool_approval(tool, tool.name, {"text": "hi"}, "call-1", None),
        timeout=5.0,
    )

    assert outcome.allowed is False
    assert outcome.decision is ApprovalDecision.DENIED
    assert "timed out" in (outcome.error_message or "")


async def test_approval_timeout_nonfinite_coerced_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-finite AGENTIC_APPROVAL_TIMEOUT_SECONDS (nan/inf) must not silently disable
    the gate (``nan > 0`` is False → unbounded wait); it is coerced back to the
    protective default instead."""
    import agentic_v2.settings as settings_mod

    for raw in ("nan", "inf"):
        monkeypatch.setenv("AGENTIC_APPROVAL_TIMEOUT_SECONDS", raw)
        settings_mod.get_settings.cache_clear()
        assert settings_mod.get_settings().agentic_approval_timeout_seconds == 1800.0


async def test_approval_disabled_timeout_allows_slow_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout <= 0 disables the bound: a provider that takes a moment still resolves
    (APPROVED), it is not denied by a timeout."""
    import agentic_v2.settings as settings_mod

    monkeypatch.setenv("AGENTIC_APPROVAL_TIMEOUT_SECONDS", "0")
    settings_mod.get_settings.cache_clear()

    class _SlowApprover:
        async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
            await asyncio.sleep(0.05)  # finite, but slower than any tiny bound
            return ApprovalDecision.APPROVED

    set_approval_provider(_SlowApprover())
    tool = _SpyTool(requires_approval=True)

    # Outer bound so a regression (0 wrongly treated as an instant timeout) fails
    # fast instead of the whole suite stalling.
    outcome = await asyncio.wait_for(
        evaluate_tool_approval(tool, tool.name, {"text": "hi"}, "call-d", None),
        timeout=5.0,
    )

    assert outcome.allowed is True
    assert outcome.decision is ApprovalDecision.APPROVED
