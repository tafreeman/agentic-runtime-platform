"""Tests proving ``AGENTIC_TOKEN_BUDGET`` is wired into the model-call path.

Before this change, ``LLMClientWrapper.set_budget()`` existed and the
enforcement machinery it arms (``TokenBudget``, ``_check_prompt_budget``,
``TokenBudget.consume()``) was fully implemented and already exercised by
``complete()``/``complete_chat()`` -- but nothing in production ever called
``set_budget()`` on the client the engine actually uses
(``agentic_v2.models.client.get_client()``). The cap was live code with zero
production callers.

Covers:
  * ``get_client()`` installs a budget from ``Settings.agentic_token_budget``
    when configured, leaves it unset (``None``, unlimited) by default, and
    skips it entirely under ``AGENTIC_NO_LLM`` so placeholder/demo calls can
    never trip a spurious "budget exceeded".
  * End-to-end enforcement via ``complete_chat()`` -- its pre-flight
    ``_check_prompt_budget`` call is NOT gated by ``AGENTIC_EK_PROVIDER``, so
    this exercises the real production check directly against a stub
    backend: a call within budget proceeds and consumes tokens; a call that
    would exceed the budget is rejected with ``ValueError`` *before* the
    backend is ever called, and consumes nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentic_v2.models.backends_base import LLMBackend
from agentic_v2.models.cache_budget import ProcessWideTokenBudget, TokenBudget
from agentic_v2.models.client import LLMClientWrapper, get_client, reset_client
from agentic_v2.models.router import FallbackChain, ModelTier
from agentic_v2.models.smart_router import SmartModelRouter
from agentic_v2.settings import get_settings

pytestmark = [pytest.mark.unit]  # asyncio_mode = "auto" covers the async tests below

_MODEL = "openai:gpt-4o-mini"


class _StubChatBackend(LLMBackend):
    """Minimal backend returning a fixed chat response.

    Mirrors ``tests/models/test_client_token_metrics.py``'s
    ``_StubChatBackend`` pattern. Records call count so tests can assert a
    rejected budget check never reached the backend.
    """

    def __init__(self, content: str = "ok") -> None:
        self._content = content
        self.calls = 0

    async def complete(
        self, model: str, prompt: str, **kwargs: Any
    ) -> str:  # pragma: no cover — complete_chat is what's exercised here
        return self._content

    async def complete_chat(
        self, model: str, messages: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        self.calls += 1
        return {"content": self._content, "tool_calls": None}


def _router() -> SmartModelRouter:
    """Router pinned to one deterministic model on every non-zero tier."""
    router = SmartModelRouter()
    for tier in ModelTier:
        if tier == ModelTier.TIER_0:
            continue
        router.register_chain(tier, FallbackChain((_MODEL,), name="t"))
    return router


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reset the client singleton + settings cache around every test.

    Mirrors ``tests/models/test_no_llm_mode.py``'s isolation fixture: the
    root ``conftest._reset_llm_client`` also fires, but a test in this module
    that flips ``AGENTIC_TOKEN_BUDGET``/``AGENTIC_NO_LLM`` needs a guaranteed
    clean singleton + settings cache both before and after its own body.
    """
    get_settings.cache_clear()
    reset_client()
    yield
    get_settings.cache_clear()
    reset_client()


# ---------------------------------------------------------------------------
# get_client() wiring
# ---------------------------------------------------------------------------


class TestGetClientBudgetWiring:
    """``get_client()`` arms a ``TokenBudget`` from Settings, or doesn't."""

    def test_no_budget_configured_leaves_client_unbounded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unset AGENTIC_TOKEN_BUDGET: no budget installed (prior, unlimited
        behavior -- this wiring must not change the default)."""
        monkeypatch.delenv("AGENTIC_TOKEN_BUDGET", raising=False)
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        get_settings.cache_clear()
        reset_client()

        client = get_client(auto_configure=False)

        assert client.budget is None

    def test_configured_budget_is_installed_on_the_shared_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AGENTIC_TOKEN_BUDGET=N arms TokenBudget(max_tokens=N) on the
        singleton get_client() returns."""
        monkeypatch.setenv("AGENTIC_TOKEN_BUDGET", "12345")
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        get_settings.cache_clear()
        reset_client()

        client = get_client(auto_configure=False)

        assert client.budget is not None
        assert isinstance(client.budget, ProcessWideTokenBudget), (
            "the shared client must arm the always-accumulating process-wide "
            "budget, not set_budget()'s per-run reservation TokenBudget"
        )
        assert client.budget.max_tokens == 12345
        assert client.budget.used_tokens == 0

    def test_budget_skipped_under_no_llm_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A configured budget must NOT arm under AGENTIC_NO_LLM: placeholder
        calls are cost-free and must never trip 'budget exceeded' in CI/demos."""
        monkeypatch.setenv("AGENTIC_TOKEN_BUDGET", "1")
        monkeypatch.setenv("AGENTIC_NO_LLM", "1")
        get_settings.cache_clear()
        reset_client()

        client = get_client(auto_configure=False)

        assert client.budget is None


# ---------------------------------------------------------------------------
# End-to-end enforcement via complete_chat()
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    """Proves a configured budget is actually enforced, not just recorded.

    Uses ``complete_chat()`` directly against a stub ``LLMBackend`` (not
    ``get_client()``'s singleton) so the assertion is independent of the
    ``AGENTIC_EK_PROVIDER`` flag split on the text ``complete()`` path --
    ``complete_chat``'s pre-flight ``_check_prompt_budget`` call is the one
    path it always takes.
    """

    async def test_call_within_budget_proceeds_and_consumes_tokens(self) -> None:
        backend = _StubChatBackend()
        client = LLMClientWrapper(backend=backend, router=_router(), enable_cache=False)
        # Trivially large relative to one short message -- no need to predict
        # the exact token estimate to know this affords it.
        client.set_budget(max_tokens=1_000_000)

        content, model_used, tokens_used = await client.complete_chat(
            messages=[{"role": "user", "content": "hi"}],
            tier=ModelTier.TIER_2,
            use_cache=False,
        )

        assert content["content"] == "ok"
        assert model_used == _MODEL
        assert backend.calls == 1
        assert tokens_used > 0
        assert client.budget is not None
        assert client.budget.used_tokens == tokens_used
        assert client.budget.used_tokens <= client.budget.max_tokens

    async def test_call_exceeding_budget_is_rejected_before_dispatch(self) -> None:
        backend = _StubChatBackend()
        client = LLMClientWrapper(backend=backend, router=_router(), enable_cache=False)
        # Trivially small relative to any real prompt -- no need to predict
        # the exact token estimate to know this can never afford it.
        client.set_budget(max_tokens=1)

        with pytest.raises(ValueError, match="Budget exceeded"):
            await client.complete_chat(
                messages=[{"role": "user", "content": "hi"}],
                tier=ModelTier.TIER_2,
                use_cache=False,
            )

        assert backend.calls == 0, (
            "the pre-flight budget check must reject before the backend is "
            "ever dispatched"
        )
        assert client.budget is not None
        assert client.budget.used_tokens == 0, (
            "a rejected call must not consume any of the budget"
        )


class TestProcessWideTokenBudgetAccumulates:
    """The process-wide budget records every charge, including overruns.

    Regression for the bypass the review found: the post-dispatch accounting
    paths call ``consume`` with tokens already spent and ignore its return. A
    plain reservation ``TokenBudget`` drops an over-cap charge without recording
    it, leaving ``used_tokens`` below reality so the next pre-flight
    ``can_afford`` under-counts and the cap is bypassable. The process-wide
    budget instead accumulates, exhausting the cap as a real circuit breaker.
    """

    def test_overrun_is_recorded_and_exhausts_the_cap(self) -> None:
        budget = ProcessWideTokenBudget(max_tokens=100)

        assert budget.consume(60) is True
        assert budget.used_tokens == 60

        # A charge that overshoots the remaining 40 is already spent upstream:
        # it must be recorded (not dropped) and report the cap as breached.
        assert budget.consume(90) is False
        assert budget.used_tokens == 150, (
            "the overrun must be accumulated, not silently dropped"
        )
        # The pre-flight gate now blocks the next call outright — no bypass.
        assert budget.can_afford(1) is False
        assert budget.remaining == 0

    def test_plain_reservation_budget_drops_the_overrun(self) -> None:
        """Contrast that motivates the subclass: the reservation model declines
        and does NOT record an over-cap charge — the bypassable behaviour."""
        reservation = TokenBudget(max_tokens=100)
        assert reservation.consume(60) is True
        assert reservation.consume(90) is False
        assert reservation.used_tokens == 60
