"""Startup guard: refuse to boot with rate limiting silently absent.

Covers :func:`agentic_v2.server.app._enforce_rate_limiting_available`, the
fail-fast check that prevents the server from starting with zero rate limiting
when ``slowapi`` is not installed (which would expose unauthenticated
LLM-budget exhaustion).

These tests patch the module-level ``_SLOWAPI_AVAILABLE`` flag so they run
deterministically whether or not ``slowapi`` is actually installed — they do
*not* ``importorskip`` it, because the missing-slowapi path is exactly what is
under test.
"""

from __future__ import annotations

import pytest

from agentic_v2.server import app as app_module
from agentic_v2.server.app import _enforce_rate_limiting_available


class TestRateLimitingStartupGuard:
    """``_enforce_rate_limiting_available`` fails closed unless overridden."""

    def test_raises_when_slowapi_unavailable_and_no_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing slowapi with no opt-out aborts startup with a clear error."""
        monkeypatch.setattr(app_module, "_SLOWAPI_AVAILABLE", False)
        monkeypatch.setattr(app_module, "_RATE_LIMIT_DISABLED", False)
        monkeypatch.delenv("AGENTIC_DISABLE_RATE_LIMITING", raising=False)

        with pytest.raises(RuntimeError, match="slowapi is required for rate limiting"):
            _enforce_rate_limiting_available()

    def test_does_not_raise_with_disable_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AGENTIC_DISABLE_RATE_LIMITING=1 lets the server start without slowapi."""
        monkeypatch.setattr(app_module, "_SLOWAPI_AVAILABLE", False)
        monkeypatch.setattr(app_module, "_RATE_LIMIT_DISABLED", False)
        monkeypatch.setenv("AGENTIC_DISABLE_RATE_LIMITING", "1")

        # Must not raise.
        _enforce_rate_limiting_available()

    def test_does_not_raise_with_legacy_disable_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The existing AGENTIC_RATE_LIMIT_DISABLED override is also honored."""
        monkeypatch.setattr(app_module, "_SLOWAPI_AVAILABLE", False)
        monkeypatch.setattr(app_module, "_RATE_LIMIT_DISABLED", True)
        monkeypatch.delenv("AGENTIC_DISABLE_RATE_LIMITING", raising=False)

        # Must not raise.
        _enforce_rate_limiting_available()

    def test_does_not_raise_when_slowapi_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With slowapi present the guard is a no-op regardless of env vars."""
        monkeypatch.setattr(app_module, "_SLOWAPI_AVAILABLE", True)
        monkeypatch.delenv("AGENTIC_DISABLE_RATE_LIMITING", raising=False)

        # Must not raise even though no override is set.
        _enforce_rate_limiting_available()
