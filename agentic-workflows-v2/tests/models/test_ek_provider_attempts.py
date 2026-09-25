"""Physical-attempt reporting tests for ``SmartRouterProvider`` (study telemetry).

The optional ``attempt_callback`` receives one :class:`ProviderAttempt` per
*physical wire call* the routing/fallback loop makes — across non-HTTP
fallback hops and across streaming calls — so a study harness can attribute
outcomes to the model that actually served (or failed) them. Asserted
contract:

* exactly one record per real backend call, in dispatch order;
* candidates skipped by the bulkhead shed gate make no wire call and produce
  NO record (never fabricated);
* a totally exhausted tier produces no records at all;
* ``error_type`` carries the exception class name only (provider error text
  can echo credentials);
* an observer that raises is logged and swallowed — telemetry must never
  break routing.

Runs offline under ``AGENTIC_NO_LLM=1`` — no live keys, no network.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

# Skip only when the optional ``ek`` extra is absent; once executionkit imports,
# an ImportError below is a consumer break and must fail collection.
pytest.importorskip(
    "executionkit",
    reason="executionkit not installed (ADR-023 dependency); "
    "physical-attempt reporting suite skipped in this environment.",
)

from executionkit.errors import ProviderError
from executionkit.provider import LLMResponse

from agentic_v2.models.backends_base import LLMBackend
from agentic_v2.models.ek_provider import ProviderAttempt, SmartRouterProvider
from agentic_v2.models.router import FallbackChain, ModelTier
from agentic_v2.models.smart_router import SmartModelRouter
from agentic_v2.settings import get_settings


@pytest.fixture(autouse=True, scope="module")
def _force_no_llm_env() -> Any:
    """Set ``AGENTIC_NO_LLM=1`` for THIS module only (restored at teardown)."""
    mp = pytest.MonkeyPatch()
    mp.setenv("AGENTIC_NO_LLM", "1")
    get_settings.cache_clear()
    try:
        yield
    finally:
        mp.undo()
        get_settings.cache_clear()


_TIER = ModelTier.TIER_2
_MESSAGES = [{"role": "user", "content": "hi"}]
_CHAIN = ("openai:gpt-4o-mini", "anthropic:claude-3-5-haiku-20241022")


class _FakeBackend(LLMBackend):
    """Scripted chat backend; the streaming variant is layered below."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        raise NotImplementedError

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append({"model": model})
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _StreamBackend(_FakeBackend):
    """Adds a scripted ``complete_stream`` (chunks, then an optional raise)."""

    def __init__(self, chunks: list[str], error: Exception | None = None) -> None:
        super().__init__([])
        self._chunks = chunks
        self._error = error

    async def complete_stream(self, model: str, prompt: str, **kwargs: Any) -> Any:
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error


def _router_with(chain: tuple[str, ...]) -> SmartModelRouter:
    """A real router with a deterministic single-tier chain (no cross-tier)."""
    router = SmartModelRouter()
    router.register_chain(_TIER, FallbackChain(chain, name="test-chain"))
    return router


async def test_attempt_callback_reports_each_physical_attempt_in_order() -> None:
    """A non-HTTP failure falls through; BOTH wire attempts are reported."""
    router = _router_with(_CHAIN)
    backend = _FakeBackend(
        [
            TimeoutError("connection timeout"),
            {"content": "recovered", "tool_calls": None},
        ]
    )
    attempts: list[ProviderAttempt] = []
    provider = SmartRouterProvider(
        router, backend, _TIER, attempt_callback=attempts.append
    )

    response = await provider.complete(_MESSAGES)

    assert response.content == "recovered"
    assert [a.model for a in attempts] == list(_CHAIN)
    assert attempts[0].ok is False
    assert attempts[0].error_type == "TimeoutError"
    assert attempts[1].ok is True
    assert attempts[1].error_type is None
    assert all(a.latency_ms >= 0.0 for a in attempts)
    assert all(not a.streaming for a in attempts)


async def test_attempt_callback_reports_single_success_once() -> None:
    router = _router_with(("openai:gpt-4o-mini",))
    backend = _FakeBackend([{"content": "hi", "tool_calls": None}])
    attempts: list[ProviderAttempt] = []
    provider = SmartRouterProvider(
        router, backend, _TIER, attempt_callback=attempts.append
    )

    await provider.complete(_MESSAGES)

    assert len(attempts) == 1
    assert attempts[0].ok is True
    assert attempts[0].model == "openai:gpt-4o-mini"


async def test_attempt_callback_records_nothing_when_no_wire_call_happens() -> None:
    """An exhausted tier raises before any backend call: zero records.

    Mirrors ``test_no_model_available_raises_provider_error`` in
    ``tests/models/test_ek_provider.py``: every tier's chain carries the same
    single model, marked unavailable, so under ``AGENTIC_NO_LLM=1`` the router
    returns ``None`` (no degraded placeholder) and the provider raises before
    touching the backend.
    """
    router = SmartModelRouter()
    for tier in ModelTier:
        if tier == ModelTier.TIER_0:
            continue
        router.register_chain(tier, FallbackChain(("openai:gpt-4o-mini",)))
    router.mark_unavailable("openai:gpt-4o-mini")
    backend = _FakeBackend([])
    attempts: list[ProviderAttempt] = []
    provider = SmartRouterProvider(
        router, backend, _TIER, attempt_callback=attempts.append
    )

    with pytest.raises(ProviderError):
        await provider.complete(_MESSAGES)

    assert backend.calls == []
    assert attempts == []


async def test_attempt_callback_observer_fault_does_not_break_routing() -> None:
    router = _router_with(("openai:gpt-4o-mini",))
    backend = _FakeBackend([{"content": "hi", "tool_calls": None}])

    def _broken(_attempt: ProviderAttempt) -> None:
        raise ValueError("observer bug")

    provider = SmartRouterProvider(router, backend, _TIER, attempt_callback=_broken)
    response = await provider.complete(_MESSAGES)
    assert response.content == "hi"


async def test_attempt_callback_reports_streaming_attempts() -> None:
    """Success and mid-stream failure each produce exactly one streaming record."""
    router = _router_with(("openai:gpt-4o-mini",))

    ok_backend = _StreamBackend(["he", "llo"])
    ok_attempts: list[ProviderAttempt] = []
    provider = SmartRouterProvider(
        router, ok_backend, _TIER, attempt_callback=ok_attempts.append
    )
    sink: list[LLMResponse] = []
    deltas = [delta async for delta in provider.stream(_MESSAGES, usage_sink=sink)]

    assert "".join(deltas) == "hello"
    assert len(ok_attempts) == 1
    assert ok_attempts[0].ok is True
    assert ok_attempts[0].streaming is True
    assert ok_attempts[0].model == "openai:gpt-4o-mini"
    # The stream shim reports the served model via raw, never a token count.
    assert sink[0].raw == {"model": "openai:gpt-4o-mini"}

    fail_backend = _StreamBackend(["partial"], error=RuntimeError("stream died"))
    fail_attempts: list[ProviderAttempt] = []
    failing = SmartRouterProvider(
        router, fail_backend, _TIER, attempt_callback=fail_attempts.append
    )
    with pytest.raises(RuntimeError):
        _ = [delta async for delta in failing.stream(_MESSAGES)]

    assert len(fail_attempts) == 1
    assert fail_attempts[0].ok is False
    assert fail_attempts[0].error_type == "RuntimeError"
    assert fail_attempts[0].streaming is True


class _HangingBackend(_FakeBackend):
    """Starts a wire call (or a stream, after one chunk) that never finishes."""

    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append({"model": model})
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def complete_stream(self, model: str, prompt: str, **kwargs: Any) -> Any:
        yield "partial"
        self.started.set()
        await asyncio.Event().wait()


async def test_attempt_callback_reports_a_cancelled_call() -> None:
    """A cancelled wire call is still a physical attempt and gets one record."""
    router = _router_with(("openai:gpt-4o-mini",))
    backend = _HangingBackend()
    attempts: list[ProviderAttempt] = []
    provider = SmartRouterProvider(
        router, backend, _TIER, attempt_callback=attempts.append
    )

    call = asyncio.create_task(provider.complete(_MESSAGES))
    await backend.started.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call

    assert [(a.model, a.ok, a.error_type) for a in attempts] == [
        ("openai:gpt-4o-mini", False, "CancelledError")
    ]
    assert attempts[0].streaming is False


async def test_attempt_callback_reports_a_stream_closed_early() -> None:
    router = _router_with(("openai:gpt-4o-mini",))
    attempts: list[ProviderAttempt] = []
    provider = SmartRouterProvider(
        router, _StreamBackend(["he", "llo"]), _TIER, attempt_callback=attempts.append
    )

    stream = provider.stream(_MESSAGES)
    assert await anext(stream) == "he"
    await stream.aclose()

    assert [(a.ok, a.error_type, a.streaming) for a in attempts] == [
        (False, "GeneratorExit", True)
    ]


async def test_attempt_callback_reports_a_cancelled_stream() -> None:
    router = _router_with(("openai:gpt-4o-mini",))
    backend = _HangingBackend()
    attempts: list[ProviderAttempt] = []
    provider = SmartRouterProvider(
        router, backend, _TIER, attempt_callback=attempts.append
    )

    async def consume() -> None:
        async for _delta in provider.stream(_MESSAGES):
            pass

    task = asyncio.create_task(consume())
    await backend.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [(a.ok, a.error_type, a.streaming) for a in attempts] == [
        (False, "CancelledError", True)
    ]
