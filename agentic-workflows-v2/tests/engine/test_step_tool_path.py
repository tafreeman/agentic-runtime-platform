"""ADR-023 Phase 6b: step-layer tool-path selection tests.

Companion to ``tests/engine/test_step_ek_delegation.py`` (Phase 6a/6c, the
plain-completion + structured seams). This module exercises the *tool-loop*
seam added in Phase 6b:

* **DEFAULT path (flag ON, no opt-out)** — an LLM-backed step's multi-turn
  tool-use loop is driven by EK ``react_loop`` over the
  ``BudgetEnforcingProvider(SmartRouterProvider(...))`` stack
  (``engine.ek_step_delegation.run_tool_loop_via_ek``). A 2-round tool
  conversation is driven end-to-end.
* **``tool_path: native`` opt-out** — the step keeps the bespoke
  ``engine.tool_execution.run_tool_calls`` loop UNCHANGED, even with the flag
  ON. Single-owner: a step uses ``react_loop`` OR ``run_tool_calls``, never both.
* **supports_tools honoured** — a Gemini route (``supports_tools=False``) makes
  ``react_loop`` REFUSE (raise ``TypeError``) rather than silently dropping
  tools.
* **Flag OFF** — the legacy ``run_tool_calls`` loop runs byte-for-byte; the EK
  react_loop path is never taken.
* **Runtime Tool -> EK Tool wrapping** — ``wrap_runtime_tool`` produces a frozen
  EK ``Tool`` whose ``execute`` serializes the runtime ``ToolResult`` with the
  native compact-JSON contract.

All tests run offline under ``AGENTIC_NO_LLM=1`` with a mocked router/backend
and mocked tools — no live keys, no network. Reliability-relevant assertions
run with the flag ON.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

try:
    from agentic_v2.engine.ek_step_delegation import (
        run_tool_loop_via_ek,
        wrap_runtime_tool,
    )
    from agentic_v2.models.backends_base import LLMBackend
    from agentic_v2.models.client import LLMClientWrapper, TokenBudget
    from agentic_v2.models.router import FallbackChain, ModelTier
    from agentic_v2.models.smart_router import SmartModelRouter
    from agentic_v2.settings import get_settings
    from agentic_v2.tools.base import ToolResult
except ImportError:  # pragma: no cover — guarded for isolated environments
    pytest.skip(
        "executionkit not installed "
        "(ADR-023 dependency); Phase 6b tool-path suite skipped.",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True, scope="module")
def _force_no_llm_env() -> Any:
    """Set ``AGENTIC_NO_LLM=1`` for THIS module only.

    Uses a module-scoped ``MonkeyPatch`` so the variable is restored at module
    teardown instead of leaking into the rest of the pytest session. The prior
    module-scope ``os.environ.setdefault`` leaked the flag session-wide, which
    made order-dependent tests elsewhere fail (e.g.
    ``tests/test_agent_resolver.py::TestMakeLlmStep::test_llm_unavailable_returns_placeholder``).
    ``get_settings`` is ``lru_cache``-d, so the cache is cleared on both entry
    and exit to force a re-read of the env (mirrors the ``ek_flag_*`` fixtures).
    """
    mp = pytest.MonkeyPatch()
    mp.setenv("AGENTIC_NO_LLM", "1")
    get_settings.cache_clear()
    try:
        yield
    finally:
        mp.undo()
        get_settings.cache_clear()


_TIER = ModelTier.TIER_2
_MODEL = "openai:gpt-4o-mini"
_GEMINI_MODEL = "gemini:gemini-2.0-flash"
_USAGE = {"prompt_tokens": 11, "completion_tokens": 7}  # total 18


# ---------------------------------------------------------------------------
# Fixtures / doubles
# ---------------------------------------------------------------------------


@pytest.fixture
def ek_flag_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Turn the EK tool-loop hot path ON for one test (cache-aware)."""
    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def ek_flag_off(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Force the EK tool-loop hot path OFF (legacy run_tool_calls loop)."""
    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeBackend(LLMBackend):
    """Backend whose ``complete_chat`` is scripted per call."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.chat_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        self.text_calls.append({"model": model, "prompt": prompt})
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step if isinstance(step, str) else str(step.get("content", ""))

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.chat_calls.append(
            {"model": model, "messages": list(messages), "tools": tools}
        )
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _router_single_tier(chain: tuple[str, ...]) -> SmartModelRouter:
    """A router pinned to ``chain`` on every (non-TIER_0) tier."""
    router = SmartModelRouter()
    for tier in ModelTier:
        if tier == ModelTier.TIER_0:
            continue
        router.register_chain(tier, FallbackChain(chain, name="test-chain"))
    return router


def _wrapper(router: SmartModelRouter, backend: LLMBackend) -> LLMClientWrapper:
    return LLMClientWrapper(backend=backend, router=router, enable_cache=False)


def _tool_call_answer(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    """Canonical OpenAI assistant response that requests one tool call."""
    return {
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
        "finish_reason": "tool_calls",
        "usage": _USAGE,
        "model": _MODEL,
    }


def _final_answer(content: str) -> dict[str, Any]:
    return {
        "content": content,
        "tool_calls": None,
        "finish_reason": "stop",
        "usage": _USAGE,
        "model": _MODEL,
    }


class _EchoTool:
    """Minimal runtime tool: returns its ``text`` arg as a ToolResult.data."""

    def __init__(self) -> None:
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

    def validate_parameters(self, **kwargs: Any) -> tuple[bool, str | None]:
        if "text" not in kwargs:
            return False, "Required parameter 'text' is missing"
        return True, None

    async def execute(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            success=True,
            data={"echoed": kwargs.get("text")},
            tool_name="echo",
        )


def _echo_contracts(tool: _EchoTool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build (tool_schemas, bound_tools) the way build_tool_contracts would."""
    schema = {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to echo"}
                },
                "required": ["text"],
            },
        },
    }
    return [schema], {tool.name: tool}


# ===========================================================================
# Runtime Tool -> EK Tool wrapping (unit)
# ===========================================================================


def test_wrap_runtime_tool_builds_ek_tool_value_type() -> None:
    """wrap_runtime_tool produces a frozen EK Tool with name/desc/params."""
    from executionkit.types import Tool as EKTool

    tool = _EchoTool()
    params = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    ek_tool = wrap_runtime_tool(tool, params)

    assert isinstance(ek_tool, EKTool)
    assert ek_tool.name == "echo"
    assert ek_tool.description == "Echo back the provided text."
    # The JSON schema is carried through verbatim (no reimplementation).
    schema = ek_tool.to_schema()
    assert schema["function"]["parameters"]["required"] == ["text"]
    assert "text" in schema["function"]["parameters"]["properties"]


async def test_wrap_runtime_tool_execute_serializes_tool_result() -> None:
    """The EK Tool.execute returns the native compact-JSON ToolResult contract."""
    tool = _EchoTool()
    ek_tool = wrap_runtime_tool(
        tool, {"type": "object", "properties": {"text": {"type": "string"}}}
    )

    observation = await ek_tool.execute(text="hi")

    assert tool.calls == [{"text": "hi"}]
    payload = json.loads(observation)
    # serialize_tool_result contract: success + data + tool_name keys present.
    assert payload["success"] is True
    assert payload["data"] == {"echoed": "hi"}
    assert payload["tool_name"] == "echo"


# ===========================================================================
# DEFAULT path: react_loop drives a 2-round tool conversation (flag ON)
# ===========================================================================


async def test_react_loop_drives_two_round_tool_conversation(ek_flag_on: None) -> None:
    """Flag ON, no opt-out: react_loop runs round-1 tool call then round-2 final."""
    router = _router_single_tier((_MODEL,))
    # Round 1: model asks to call echo. Round 2: model returns the final answer.
    backend = _FakeBackend(
        [
            _tool_call_answer("echo", {"text": "ping"}, "call-1"),
            _final_answer("the tool said ping"),
        ]
    )
    tool = _EchoTool()
    tool_schemas, bound_tools = _echo_contracts(tool)

    final_text, model_used, tokens_used, tool_calls_made = await run_tool_loop_via_ek(
        router=router,
        backend=backend,
        tier=_TIER,
        prompt="use the echo tool",
        tool_schemas=tool_schemas,
        bound_tools=bound_tools,
        max_tokens=256,
        budget=None,
    )

    # Two LLM rounds, one tool executed, final content surfaced.
    assert len(backend.chat_calls) == 2
    assert tool.calls == [{"text": "ping"}]
    assert tool_calls_made == 1
    assert final_text == "the tool said ping"
    assert model_used == _MODEL
    # Tokens accrued across BOTH rounds (18 + 18) via the EK pattern ledger.
    assert tokens_used == 36
    # The second round received the tool observation in the thread.
    round2_messages = backend.chat_calls[1]["messages"]
    assert any(m.get("role") == "tool" for m in round2_messages)
    # record_success fired once per physical round (no double-cost).
    stats = router.model_stats[_MODEL]
    assert stats.success_count == 2
    assert stats.failure_count == 0


async def test_react_loop_refuses_tools_on_gemini_route(ek_flag_on: None) -> None:
    """supports_tools honoured: a Gemini route makes react_loop REFUSE (raise)."""
    router = _router_single_tier((_GEMINI_MODEL,))
    backend = _FakeBackend([])  # never reached — refusal happens before any call
    tool = _EchoTool()
    tool_schemas, bound_tools = _echo_contracts(tool)

    with pytest.raises(TypeError):
        await run_tool_loop_via_ek(
            router=router,
            backend=backend,
            tier=_TIER,
            prompt="use the echo tool",
            tool_schemas=tool_schemas,
            bound_tools=bound_tools,
            max_tokens=256,
            budget=None,
        )

    # REFUSED, not silently dropped: no provider call was made.
    assert backend.chat_calls == []
    assert tool.calls == []


async def test_react_loop_enforces_token_budget_first(ek_flag_on: None) -> None:
    """Budget precedence: TokenBudget owns the token-sum ceiling mid-loop."""
    from executionkit.provider import BudgetExhaustedError

    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend([_tool_call_answer("echo", {"text": "x"}, "c1")])
    tool = _EchoTool()
    tool_schemas, bound_tools = _echo_contracts(tool)
    budget = TokenBudget(max_tokens=5)  # 18-token round blows the cap

    with pytest.raises(BudgetExhaustedError):
        await run_tool_loop_via_ek(
            router=router,
            backend=backend,
            tier=_TIER,
            prompt="use echo",
            tool_schemas=tool_schemas,
            bound_tools=bound_tools,
            max_tokens=256,
            budget=budget,
        )


# ===========================================================================
# Step-level selection: native opt-out, default, and flag-off
# ===========================================================================


def _make_step_func(
    monkeypatch: pytest.MonkeyPatch,
    *,
    router: SmartModelRouter,
    backend: LLMBackend,
    tool: _EchoTool,
    tool_path: str | None,
) -> Any:
    """Build the LLM step func with get_client + build_tool_contracts mocked."""
    import agentic_v2.engine.agent_resolver as ar

    wrapper = _wrapper(router, backend)
    monkeypatch.setattr(
        "agentic_v2.models.client.get_client", lambda auto_configure=False: wrapper
    )
    tool_schemas, bound_tools = _echo_contracts(tool)
    monkeypatch.setattr(
        ar,
        "build_tool_contracts",
        lambda _tier, _enabled, _choice="auto": (
            tool_schemas,
            bound_tools,
            _choice,
        ),
    )
    # Keep prompt assembly trivial / deterministic.
    monkeypatch.setattr(ar, "build_system_prompt", lambda **_kw: "do the task")
    monkeypatch.setattr(ar, "load_agent_system_prompt", lambda *_a, **_k: "persona")

    return ar._make_llm_step(
        agent_name="tier2_coder",
        description="desc",
        tier=_TIER,
        tool_path=tool_path,
    )


async def test_tool_path_native_uses_run_tool_calls_not_react_loop(
    ek_flag_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag ON + tool_path='native': the bespoke run_tool_calls loop drives it."""
    import agentic_v2.engine.agent_resolver as ar
    from agentic_v2.engine.context import ExecutionContext

    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend(
        [
            _tool_call_answer("echo", {"text": "native"}, "n1"),
            _final_answer("native done"),
        ]
    )
    tool = _EchoTool()

    # Spy: react_loop delegation must NOT be invoked for a native step.
    called = {"ek": False}

    async def _boom(**_kw: Any) -> Any:
        called["ek"] = True
        raise AssertionError("react_loop must not run for tool_path: native")

    monkeypatch.setattr(ar, "run_tool_calls", ar.run_tool_calls)  # keep real native
    import agentic_v2.engine.ek_step_delegation as ek

    monkeypatch.setattr(ek, "run_tool_loop_via_ek", _boom)

    func = _make_step_func(
        monkeypatch, router=router, backend=backend, tool=tool, tool_path="native"
    )
    result = await func(ExecutionContext())

    assert called["ek"] is False
    # The native loop executed the tool and reached the final answer.
    assert tool.calls == [{"text": "native"}]
    assert result["_meta"]["tool_calls"] == 1
    assert len(backend.chat_calls) == 2


async def test_default_path_uses_react_loop_with_flag_on(
    ek_flag_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag ON + no opt-out: the step's tool loop is driven by react_loop."""
    import agentic_v2.engine.ek_step_delegation as ek
    from agentic_v2.engine.context import ExecutionContext

    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend(
        [
            _tool_call_answer("echo", {"text": "go"}, "d1"),
            _final_answer("default done"),
        ]
    )
    tool = _EchoTool()

    seen = {"ek": False}
    real = ek.run_tool_loop_via_ek

    async def _spy(**kw: Any) -> Any:
        seen["ek"] = True
        return await real(**kw)

    monkeypatch.setattr(ek, "run_tool_loop_via_ek", _spy)

    func = _make_step_func(
        monkeypatch, router=router, backend=backend, tool=tool, tool_path=None
    )
    result = await func(ExecutionContext())

    assert seen["ek"] is True
    assert tool.calls == [{"text": "go"}]
    assert result["_meta"]["tool_calls"] == 1
    assert result["_meta"]["model_used"] == _MODEL


async def test_flag_off_uses_native_loop_not_react_loop(
    ek_flag_off: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag OFF: legacy run_tool_calls loop runs; react_loop is never taken."""
    import agentic_v2.engine.ek_step_delegation as ek
    from agentic_v2.engine.context import ExecutionContext

    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend(
        [
            _tool_call_answer("echo", {"text": "legacy"}, "l1"),
            _final_answer("legacy done"),
        ]
    )
    tool = _EchoTool()

    called = {"ek": False}

    async def _boom(**_kw: Any) -> Any:
        called["ek"] = True
        raise AssertionError("react_loop must not run when the flag is off")

    monkeypatch.setattr(ek, "run_tool_loop_via_ek", _boom)

    func = _make_step_func(
        monkeypatch, router=router, backend=backend, tool=tool, tool_path=None
    )
    result = await func(ExecutionContext())

    assert called["ek"] is False
    assert tool.calls == [{"text": "legacy"}]
    assert result["_meta"]["tool_calls"] == 1
    assert len(backend.chat_calls) == 2
