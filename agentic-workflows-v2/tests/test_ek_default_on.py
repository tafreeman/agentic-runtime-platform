"""ADR-023 P7 — default-cutover assertions (default-on REVERTED 2026-05-31).

These tests pin the Phase 7 state:

1. With no env override, ``get_settings().agentic_ek_provider`` is ``False``.
   P7 briefly flipped this to ``True`` but it was reverted the same day:
   default-on exposed an ``AGENTIC_EK_PROVIDER``/``get_settings`` lru_cache
   test-isolation leak and a hang in the EK-default path (tracked in
   ADR-023-migration-notes). The EK path remains fully functional opt-in via
   ``AGENTIC_EK_PROVIDER=1``; default-on resumes once both blockers are fixed.
2. ``complete_stream`` and ``count_tokens`` stay OUT of the EK kernel seam
   but remain reachable on the underlying ``LLMBackend`` ABC. The kernel
   seam itself is ``complete(messages) -> LLMResponse`` only
   (ADR-023 decision #7, accepted).

All assertions are static (settings + ABC introspection): no live keys,
no httpx, no router dispatch. Run under ``AGENTIC_NO_LLM=1``.
"""

from __future__ import annotations

import inspect

from agentic_v2.models.backends_base import LLMBackend


def test_ek_provider_default_off_without_env_override(monkeypatch):
    """No env override -> agentic_ek_provider defaults to False (P7 reverted).

    Default-on was reverted on 2026-05-31 pending the test-isolation leak and
    EK-default hang fixes; flip this back to ``is True`` when default-on resumes.
    """
    monkeypatch.delenv("AGENTIC_EK_PROVIDER", raising=False)

    import agentic_v2.settings as settings_mod

    # NOTE: do NOT importlib.reload(settings_mod) here. Reloading rebinds the
    # module's get_settings to a brand-new lru_cache while other modules (and
    # the conftest autouse cache-reset) still hold the original reference —
    # a split-brain that made client.py read the EK flag through a cache no
    # test could clear, breaking tests/models/test_ek_provider_wrapper.py in
    # full-suite order. cache_clear() + monkeypatch already force a fresh read.
    settings_mod.get_settings.cache_clear()

    try:
        assert settings_mod.get_settings().agentic_ek_provider is False
    finally:
        settings_mod.get_settings.cache_clear()


def test_ek_provider_env_can_still_force_legacy_off(monkeypatch):
    """AGENTIC_EK_PROVIDER=0 still forces the legacy branch (rollback path)."""
    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "0")

    import agentic_v2.settings as settings_mod

    # See note above: no importlib.reload — cache_clear() + monkeypatch are
    # sufficient and reloading creates a split-brain get_settings cache.
    settings_mod.get_settings.cache_clear()

    try:
        assert settings_mod.get_settings().agentic_ek_provider is False
    finally:
        # Restore the cached singleton for downstream tests.
        settings_mod.get_settings.cache_clear()


def test_complete_stream_remains_reachable_on_backend_abc():
    """Streaming stays OUT of the kernel but reachable on the LLMBackend ABC."""
    assert hasattr(LLMBackend, "complete_stream")
    assert callable(LLMBackend.complete_stream)
    # complete_stream is an async-generator-producing coroutine signature
    # carried by the ABC, not by the EK kernel seam.
    sig = inspect.signature(LLMBackend.complete_stream)
    assert "model" in sig.parameters
    assert "prompt" in sig.parameters


def test_count_tokens_remains_reachable_on_backend_abc():
    """Per-provider count_tokens stays OUT of the kernel but on the ABC."""
    assert hasattr(LLMBackend, "count_tokens")
    assert callable(LLMBackend.count_tokens)
    sig = inspect.signature(LLMBackend.count_tokens)
    assert "text" in sig.parameters
    assert "model" in sig.parameters


def test_kernel_seam_complete_signature_is_messages_to_response():
    """The kernel seam is complete(...) only; complete_chat carries messages.

    The runtime ABC exposes both the legacy text ``complete`` and the
    EK-seam ``complete_chat`` (messages -> response dict). Streaming and
    count_tokens are present on the ABC but are explicitly not part of the
    EK kernel seam (ADR-023 decision #7).
    """
    assert hasattr(LLMBackend, "complete")
    assert hasattr(LLMBackend, "complete_chat")

    chat_sig = inspect.signature(LLMBackend.complete_chat)
    assert "messages" in chat_sig.parameters
