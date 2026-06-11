"""ADR-023 Phase 6a/6c: step-layer EK delegation tests.

Companion to ``tests/models/test_ek_provider_wrapper.py`` (Phase 5b, the
``LLMClientWrapper`` seam). This module exercises the *step-layer* seam added in
Phase 6:

* **6a** — the inner plain-completion turn of an LLM-backed step
  (``engine.tool_execution.complete_chat_with_fallback``) routes through EK
  ``_TrackedProvider`` / ``checked_complete`` over a ``SmartRouterProvider`` when
  ``settings.agentic_ek_provider`` is ON.
* **6c** — structured JSON extraction routes through EK ``structured()``; the
  runtime ``ReviewStatus.normalize`` STILL runs at the DAG/gating layer
  afterward (asserted unchanged).

Critically, ``StepExecutor`` keeps ALL DAG-level lifecycle: ``should_run`` /
``when`` / ``unless``, ``RetryConfig`` / backoff, ``loop_until``, pre/post/error
hooks, and verification block/report escalation all behave identically with the
flag ON. Budget precedence (ACCEPTED) is asserted: ``TokenBudget`` raises on the
token-sum cap. Flag-OFF is byte-for-byte the legacy path.

All tests run offline under ``AGENTIC_NO_LLM=1`` with a mocked router/backend —
no live keys, no network.
"""

from __future__ import annotations

from typing import Any

import pytest

try:
    from executionkit.cost import CostTracker
    from executionkit.provider import BudgetExhaustedError

    from agentic_v2.contracts import ReviewStatus, StepStatus
    from agentic_v2.engine.context import ExecutionContext
    from agentic_v2.engine.ek_step_delegation import (
        BudgetEnforcingProvider,
        complete_turn_via_ek,
        structured_via_ek,
    )
    from agentic_v2.engine.step import (
        RetryConfig,
        RetryStrategy,
        StepDefinition,
        StepExecutor,
    )
    from agentic_v2.engine.tool_execution import complete_chat_with_fallback
    from agentic_v2.models.backends_base import LLMBackend
    from agentic_v2.models.client import LLMClientWrapper, TokenBudget
    from agentic_v2.models.router import FallbackChain, ModelTier
    from agentic_v2.models.smart_router import SmartModelRouter
    from agentic_v2.settings import get_settings
except ImportError:  # pragma: no cover — guarded for isolated environments
    pytest.skip(
        "executionkit not installed "
        "(ADR-023 dependency); Phase 6 step-delegation suite skipped.",
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
_USAGE = {"prompt_tokens": 11, "completion_tokens": 7}  # total 18


# ---------------------------------------------------------------------------
# Fixtures / doubles
# ---------------------------------------------------------------------------


@pytest.fixture
def ek_flag_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Turn the EK delegation hot path ON for one test (cache-aware)."""
    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def ek_flag_off(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Force the EK delegation hot path OFF (legacy fallback loop)."""
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


def _answer(content: str, **extra: Any) -> dict[str, Any]:
    return {
        "content": content,
        "tool_calls": None,
        "finish_reason": "stop",
        "usage": _USAGE,
        "model": _MODEL,
        **extra,
    }


# ===========================================================================
# 6a — plain completion flows through EK
# ===========================================================================


async def test_6a_plain_completion_flows_through_ek_chat_path(
    ek_flag_on: None,
) -> None:
    """Flag ON: complete_chat_with_fallback delegates to the EK chat path."""
    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend([_answer("hello")])
    wrapper = _wrapper(router, backend)

    response, model_used, tokens = await complete_chat_with_fallback(
        client=wrapper,
        tier=_TIER,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=256,
        tools=None,
    )

    # The EK chat path was used; the legacy text path was NOT touched.
    assert backend.text_calls == []
    assert len(backend.chat_calls) == 1
    # Canonical dict contract preserved (content/tokens) for downstream parsing.
    assert response["content"] == "hello"
    assert model_used == _MODEL
    assert tokens == 18  # real usage, not estimate
    # record_success fired exactly once (no double-cost).
    stats = router.model_stats[_MODEL]
    assert stats.success_count == 1
    assert stats.failure_count == 0


async def test_6a_tracked_provider_shares_one_cost_tracker(
    ek_flag_on: None,
) -> None:
    """The shared CostTracker accrues the call (llm_calls dimension)."""
    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend([_answer("ok")])
    tracker = CostTracker()

    response_dict, model_used, tokens = await complete_turn_via_ek(
        router=router,
        backend=backend,
        tier=_TIER,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=128,
        tools=None,
        budget=None,
        tracker=tracker,
        metadata={},
    )

    assert response_dict["content"] == "ok"
    assert tokens == 18
    # EK two-phase recording landed exactly one call + the real tokens.
    usage = tracker.to_usage()
    assert usage.llm_calls == 1
    assert usage.input_tokens + usage.output_tokens == 18


async def test_6a_budget_exhausted_raises_on_token_cap(ek_flag_on: None) -> None:
    """Budget precedence: TokenBudget owns the token-sum ceiling and raises."""
    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend([_answer("answer")])  # 18 tokens > cap 5
    budget = TokenBudget(max_tokens=5)

    with pytest.raises(BudgetExhaustedError):
        await complete_turn_via_ek(
            router=router,
            backend=backend,
            tier=_TIER,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=128,
            tools=None,
            budget=budget,
            tracker=CostTracker(),
            metadata={},
        )


async def test_6a_budget_enforcing_provider_delegates_supports_tools() -> None:
    """F-04: the budget wrapper delegates capability, never hardcodes it."""
    from agentic_v2.models.ek_provider import SmartRouterProvider

    # A Gemini route reports supports_tools=False; the wrapper must mirror it.
    router = _router_single_tier(("gemini:gemini-2.0-flash",))
    backend = _FakeBackend([])
    provider = BudgetEnforcingProvider(
        SmartRouterProvider(router, backend, _TIER), budget=None
    )
    assert provider.supports_tools is False


# ===========================================================================
# 6c — structured/JSON extraction flows through EK structured()
# ===========================================================================


async def test_6c_structured_extraction_flows_through_ek(ek_flag_on: None) -> None:
    """Flag ON: structured_via_ek parses JSON via EK extract_json (fenced)."""
    router = _router_single_tier((_MODEL,))
    # extract_json must salvage JSON from a markdown fence (3-strategy).
    backend = _FakeBackend(
        [_answer('```json\n{"overall_status": "approved", "score": 9}\n```')]
    )
    tracker = CostTracker()

    value, tokens = await structured_via_ek(
        router=router,
        backend=backend,
        tier=_TIER,
        prompt="review the code",
        budget=None,
        tracker=tracker,
        max_tokens=512,
    )

    assert isinstance(value, dict)
    assert value["overall_status"] == "approved"
    assert value["score"] == 9
    assert tokens == 18
    assert tracker.to_usage().llm_calls == 1


async def test_6c_review_status_normalize_still_runs_after_ek(
    ek_flag_on: None,
) -> None:
    """6c: runtime ReviewStatus.normalize STILL runs at the gating layer.

    EK structured() does NOT normalize; the lowercase 'approved' it returns is
    coerced to the canonical enum only by the runtime normalizer (DAG layer).
    """
    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend([_answer('{"overall_status": "approved"}')])

    value, _ = await structured_via_ek(
        router=router,
        backend=backend,
        tier=_TIER,
        prompt="review",
        budget=None,
        tracker=CostTracker(),
        max_tokens=256,
    )

    # EK returned the raw lowercase string (no normalization in the pattern).
    assert value["overall_status"] == "approved"
    # The DAG/gating-layer normalizer is what canonicalizes it.
    assert ReviewStatus.normalize(value["overall_status"]) is ReviewStatus.APPROVED


async def test_6c_structured_budget_exhausted_raises(ek_flag_on: None) -> None:
    """Budget precedence applies to the structured path too."""
    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend([_answer('{"x": 1}')])
    budget = TokenBudget(max_tokens=5)

    with pytest.raises(BudgetExhaustedError):
        await structured_via_ek(
            router=router,
            backend=backend,
            tier=_TIER,
            prompt="emit json",
            budget=budget,
            tracker=CostTracker(),
            max_tokens=256,
        )


# ===========================================================================
# DAG lifecycle preserved with the flag ON (StepExecutor untouched)
# ===========================================================================


async def _ek_backed_step(
    router: SmartModelRouter, backend: LLMBackend, content: str
) -> Any:
    """Build a StepDefinition whose func drives the EK delegation path."""

    async def _func(ctx: ExecutionContext) -> dict[str, Any]:
        wrapper = _wrapper(router, backend)
        response, model_used, tokens = await complete_chat_with_fallback(
            client=wrapper,
            tier=_TIER,
            messages=[{"role": "user", "content": "go"}],
            max_tokens=128,
            tools=None,
        )
        return {
            "answer": response["content"],
            "_meta": {"model_used": model_used, "tokens_used": tokens},
        }

    _ = content
    return _func


async def test_lifecycle_success_maps_meta_with_flag_on(ek_flag_on: None) -> None:
    """A successful EK-backed step still has _meta lifted into StepResult."""
    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend([_answer("done")])
    func = await _ek_backed_step(router, backend, "done")
    step_def = StepDefinition(name="ek_step", func=func, tier=ModelTier.TIER_2)

    result = await StepExecutor().execute(step_def, ExecutionContext())

    assert result.status is StepStatus.SUCCESS
    assert result.output_data["answer"] == "done"
    # StepExecutor lifted _meta -> model_used + metadata.tokens_used.
    assert result.model_used == _MODEL
    assert result.metadata["tokens_used"] == 18


async def test_lifecycle_should_run_when_unless_with_flag_on(
    ek_flag_on: None,
) -> None:
    """should_run / when / unless gating is identical with the flag ON."""
    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend([_answer("x"), _answer("y")])
    func = await _ek_backed_step(router, backend, "x")

    # when -> False: SKIPPED, no provider call.
    skipped = StepDefinition(
        name="when_false", func=func, when=lambda _ctx: False, tier=ModelTier.TIER_2
    )
    r1 = await StepExecutor().execute(skipped, ExecutionContext())
    assert r1.status is StepStatus.SKIPPED
    assert backend.chat_calls == []

    # unless -> True: SKIPPED, no provider call.
    unless_true = StepDefinition(
        name="unless_true",
        func=func,
        unless=lambda _ctx: True,
        tier=ModelTier.TIER_2,
    )
    r2 = await StepExecutor().execute(unless_true, ExecutionContext())
    assert r2.status is StepStatus.SKIPPED
    assert backend.chat_calls == []


async def test_lifecycle_retry_backoff_with_flag_on(
    ek_flag_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RetryConfig/backoff still drives re-execution on a transient failure."""
    # First func invocation raises, second succeeds. The DAG retry loop (NOT
    # EK) is what re-runs the func; assert it retried and ultimately succeeded.
    calls = {"n": 0}

    async def _flaky(ctx: ExecutionContext) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return {"answer": "ok"}

    import asyncio as _asyncio

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(_asyncio, "sleep", _no_sleep)

    step_def = StepDefinition(
        name="retry_step",
        func=_flaky,
        retry=RetryConfig(
            max_retries=2, strategy=RetryStrategy.FIXED, base_delay_seconds=0.0
        ),
        tier=ModelTier.TIER_2,
    )
    result = await StepExecutor().execute(step_def, ExecutionContext())

    assert result.status is StepStatus.SUCCESS
    assert calls["n"] == 2
    assert result.retry_count == 1


async def test_lifecycle_error_hooks_fire_on_failure_with_flag_on(
    ek_flag_on: None,
) -> None:
    """error hooks fire and the error maps onto StepResult on terminal failure."""
    fired: list[str] = []

    async def _err_hook(ctx: ExecutionContext, sd: Any) -> None:
        fired.append(sd.name)

    async def _always_fail(ctx: ExecutionContext) -> dict[str, Any]:
        raise ValueError("boom")

    step_def = StepDefinition(
        name="fail_step",
        func=_always_fail,
        retry=RetryConfig(max_retries=0),
        error_hooks=[_err_hook],
        tier=ModelTier.TIER_2,
    )
    result = await StepExecutor().execute(step_def, ExecutionContext())

    assert result.status is StepStatus.FAILED
    assert result.error_type == "ValueError"
    assert "boom" in (result.error or "")
    assert fired == ["fail_step"]


async def test_lifecycle_loop_until_with_flag_on(ek_flag_on: None) -> None:
    """loop_until re-executes the step body until the expression is satisfied."""
    iterations = {"n": 0}

    async def _looper(ctx: ExecutionContext) -> dict[str, Any]:
        iterations["n"] += 1
        return {"ready": iterations["n"] >= 2}

    step_def = StepDefinition(
        name="loop_step",
        func=_looper,
        loop_until="${steps.loop_step.outputs.ready} == True",
        loop_max=5,
        output_mapping={"ready": "ready"},
        tier=ModelTier.TIER_2,
    )
    result = await StepExecutor().execute(step_def, ExecutionContext())

    assert result.status is StepStatus.SUCCESS
    assert iterations["n"] >= 2
    assert result.metadata.get("loop_iteration", 1) >= 2


async def test_lifecycle_verification_block_fails_step_with_flag_on(
    ek_flag_on: None,
) -> None:
    """verification escalation='block' marks the step FAILED (unchanged)."""
    from agentic_v2.contracts.verification import VerificationPolicy

    async def _ok(ctx: ExecutionContext) -> dict[str, Any]:
        return {"answer": "ok"}

    # A command that exits non-zero so the gate FAILS; 'block' must fail the step.
    policy = VerificationPolicy(
        enabled=True,
        verification_commands=("python -c \"import sys; sys.exit(1)\"",),
        escalation_strategy="block",
    )
    step_def = StepDefinition(
        name="verify_block", func=_ok, verify=policy, tier=ModelTier.TIER_2
    )
    result = await StepExecutor().execute(step_def, ExecutionContext())

    assert result.status is StepStatus.FAILED
    assert "Verification failed" in (result.error or "")


async def test_lifecycle_verification_report_continues_with_flag_on(
    ek_flag_on: None,
) -> None:
    """verification escalation='report' logs but does NOT fail the step."""
    from agentic_v2.contracts.verification import VerificationPolicy

    async def _ok(ctx: ExecutionContext) -> dict[str, Any]:
        return {"answer": "ok"}

    policy = VerificationPolicy(
        enabled=True,
        verification_commands=("python -c \"import sys; sys.exit(1)\"",),
        escalation_strategy="report",
    )
    step_def = StepDefinition(
        name="verify_report", func=_ok, verify=policy, tier=ModelTier.TIER_2
    )
    result = await StepExecutor().execute(step_def, ExecutionContext())

    assert result.status is StepStatus.SUCCESS
    assert result.metadata["verification_status"] == "failed"


# ===========================================================================
# Flag-OFF: legacy path unchanged
# ===========================================================================


async def test_flag_off_uses_legacy_fallback_loop(ek_flag_off: None) -> None:
    """Flag OFF: complete_chat_with_fallback runs the legacy loop byte-for-byte."""
    router = _router_single_tier((_MODEL,))
    backend = _FakeBackend([_answer("legacy")])
    wrapper = _wrapper(router, backend)

    response, model_used, tokens = await complete_chat_with_fallback(
        client=wrapper,
        tier=_TIER,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=256,
        tools=None,
    )

    # Legacy loop calls complete_chat directly and extracts usage tokens.
    assert response["content"] == "legacy"
    assert model_used == _MODEL
    assert tokens == 18
    assert len(backend.chat_calls) == 1
    # Legacy path consumed the runtime budget directly (no EK tracker involved).
    stats = router.model_stats[_MODEL]
    assert stats.success_count == 1


# ---------------------------------------------------------------------------
# CRITICAL-2: wrap_runtime_tool consults the approval gate before execution.
#
# Isolated unit test of wrap_runtime_tool's inner _execute — does NOT exercise
# the EK react_loop or the hanging EK provider test file.
# ---------------------------------------------------------------------------


class _GatedSpyTool:
    """Minimal runtime-tool stub: requires approval and records executions."""

    name = "gated_runtime_tool"
    description = "Records calls; requires approval."
    requires_approval = True

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any):
        from agentic_v2.tools.base import ToolResult

        self.calls.append(dict(kwargs))
        return ToolResult(success=True, data={"echo": kwargs}, tool_name=self.name)


async def test_wrap_runtime_tool_denied_never_executes() -> None:
    """A gated tool wrapped via wrap_runtime_tool is never executed under deny."""
    import json as _json

    from agentic_v2.engine.ek_step_delegation import wrap_runtime_tool
    from agentic_v2.governance.approval import (
        AutoDenyProvider,
        set_approval_provider,
    )

    set_approval_provider(AutoDenyProvider())
    try:
        tool = _GatedSpyTool()
        ek_tool = wrap_runtime_tool(tool, {"type": "object"})

        observation = await ek_tool.execute(text="hi")

        assert tool.calls == []  # execute NEVER reached
        payload = _json.loads(observation)
        assert payload["success"] is False
        assert "approval" in payload["error"].lower()
        assert payload["metadata"]["approval_decision"] == "denied"
    finally:
        set_approval_provider(None)


async def test_wrap_runtime_tool_no_provider_fails_closed() -> None:
    """No provider registered → gated tool fails closed and never executes."""
    import json as _json

    from agentic_v2.engine.ek_step_delegation import wrap_runtime_tool
    from agentic_v2.governance.approval import set_approval_provider

    set_approval_provider(None)
    tool = _GatedSpyTool()
    ek_tool = wrap_runtime_tool(tool, {"type": "object"})

    observation = await ek_tool.execute(text="hi")

    assert tool.calls == []
    payload = _json.loads(observation)
    assert payload["success"] is False
    assert "no provider" in payload["error"].lower()
