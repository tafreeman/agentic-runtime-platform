"""Tests for the OpenRouter runtime backend (native-engine parity).

Mirrors the NVIDIA backend suite: a discovered ``openrouter:`` id must resolve
to the OpenRouter backend on the native ``MultiBackend`` path, keep its
``publisher/model[:free]`` form (only the provider prefix is stripped), and be
registered by auto-configuration exactly when ``OPENROUTER_API_KEY`` is set —
OpenRouter has no keyless self-hosted mode, unlike NIM.
"""

from __future__ import annotations

import pytest

from agentic_v2.models.backends import (
    PREFIX_MAP,
    OpenRouterBackend,
    auto_configure_backend,
    get_backend,
)

_DEFAULT_BASE = "https://openrouter.ai/api/v1"


class TestOpenRouterNativeBackend:
    """The native MultiBackend path resolves openrouter: correctly."""

    def test_prefix_map_routes_openrouter(self) -> None:
        assert PREFIX_MAP["openrouter:"] == "openrouter"

    def test_defaults_and_strips_only_provider_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
        backend = OpenRouterBackend(api_key="test-key")
        # Only openrouter: is stripped on the wire — publisher and :free stay.
        assert backend._provider_prefix == "openrouter:"
        assert backend.base_url == _DEFAULT_BASE

    def test_base_url_override_appends_v1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://gateway.local:8080")
        backend = OpenRouterBackend(api_key="test-key")
        assert backend.base_url == "http://gateway.local:8080/v1"

    def test_reads_env_key_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
        backend = OpenRouterBackend()
        assert backend.api_key == "test-key"

    def test_without_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            OpenRouterBackend(api_key="")


class TestOpenRouterFactoryWiring:
    """get_backend / auto_configure_backend construct and register the backend."""

    def test_get_backend_constructs_openrouter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
        backend = get_backend("openrouter")
        assert isinstance(backend, OpenRouterBackend)
        assert backend.api_key == "test-key"

    def test_auto_configure_registers_openrouter_when_keyed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        backend = auto_configure_backend()
        assert "openrouter" in backend.backends  # type: ignore[attr-defined]

    def test_auto_configure_skips_openrouter_without_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        backend = auto_configure_backend()
        assert "openrouter" not in backend.backends  # type: ignore[attr-defined]
