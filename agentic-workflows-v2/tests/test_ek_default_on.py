"""ADR-023 — default-cutover assertions (default-on ACTIVE).

These tests pin the default-on state:

1. With no env override, ``get_settings().agentic_ek_provider`` is ``True``.
   Default-on is now active: the two blockers that forced the 2026-05-31
   revert are fixed — the ``AGENTIC_EK_PROVIDER``/``get_settings`` lru_cache
   test-isolation leak (bracketed by the conftest provider-cache reset) and the
   hang in the EK-default path (the EK branch dispatches in an undecorated
   ``complete()`` wrapper before the ``retry_with_jitter`` boundary). The
   legacy rollback path stays reachable via ``AGENTIC_EK_PROVIDER=0``.
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


def test_ek_provider_default_on_without_env_override(monkeypatch):
    """No env override -> agentic_ek_provider defaults to True (default-on).

    Default-on is active: the test-isolation leak and EK-default hang that
    forced the 2026-05-31 revert are both fixed.
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
        assert settings_mod.get_settings().agentic_ek_provider is True
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


def test_ek_provider_unrecognized_value_falls_back_to_default(monkeypatch):
    """An unrecognized AGENTIC_EK_PROVIDER value coerces to the default, not a crash.

    Regression: the before-validator referenced ``cls._EK_PROVIDER_DEFAULT``,
    but that default is a MODULE-level constant, not a class attribute — so an
    env typo (or an explicit ``None``) raised ``AttributeError`` while building
    ``Settings()`` instead of logging a warning and falling back. The validator
    must resolve the bare module global ``_EK_PROVIDER_DEFAULT``.
    """
    from agentic_v2.settings import _EK_PROVIDER_DEFAULT, Settings

    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "not-a-bool")
    assert Settings().agentic_ek_provider is _EK_PROVIDER_DEFAULT

    # Direct validator calls for the two fallback inputs (None + unknown str).
    assert Settings._coerce_ek_provider_flag(None) is _EK_PROVIDER_DEFAULT
    assert Settings._coerce_ek_provider_flag("garbage") is _EK_PROVIDER_DEFAULT

    # A real false-literal still forces the legacy path off.
    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "0")
    assert Settings().agentic_ek_provider is False


def test_ek_tool_loop_defers_to_native_when_executionkit_absent(monkeypatch):
    """EK-on without the optional executionkit package degrades to native.

    Regression: ek_step_delegation imports executionkit at module load, so when
    the package is absent (e.g. the no-extras CI test env) the EK tool loop
    raised ImportError into the placeholder fallback — making engine steps emit
    'No module named executionkit' placeholder output and breaking deterministic
    workflow tests. The gate must fall back to the native loop instead.
    """
    import importlib.util as iu

    from agentic_v2.engine import agent_resolver as ar
    from agentic_v2.settings import get_settings

    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "1")
    get_settings.cache_clear()
    orig_find_spec = iu.find_spec
    monkeypatch.setattr(
        iu,
        "find_spec",
        lambda name, *a, **k: None
        if name == "executionkit"
        else orig_find_spec(name, *a, **k),
    )
    ar._executionkit_available.cache_clear()
    try:
        assert ar._executionkit_available() is False
        # Flag on + tools present, but executionkit absent -> native owns the loop.
        assert ar._should_use_ek_tool_loop({"some_tool": object()}, None) is False
    finally:
        ar._executionkit_available.cache_clear()
        get_settings.cache_clear()


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
