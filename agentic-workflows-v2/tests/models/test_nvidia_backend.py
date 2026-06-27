"""Tests for the NVIDIA NIM runtime backend (PR #132 review follow-up).

PR #132 added NVIDIA NIM *discovery* but no runtime backend, so a discovered
``nvidia:`` id silently fell through to Ollama (LangChain ``get_chat_model``) or
the OpenAI default (native ``MultiBackend``) at inference — advertised but not
runnable. These tests lock in that a discovered id now resolves to NVIDIA on
both engines, keeps its ``publisher/model`` form, and honors the cloud-vs-on-prem
key rule (cloud requires ``NVIDIA_API_KEY``; a self-hosted NIM does not).
"""

from __future__ import annotations

from typing import Any

import pytest

from agentic_v2.langchain.model_builders import build_nvidia_model
from agentic_v2.langchain.models import _KNOWN_PREFIXES, _PREFIX_BUILDERS
from agentic_v2.models.backends import (
    PREFIX_MAP,
    NvidiaBackend,
    auto_configure_backend,
)

_CLOUD_BASE = "https://integrate.api.nvidia.com/v1"


class TestNvidiaLangChainDispatch:
    """The bug itself: nvidia: must be a known prefix with a builder, not Ollama."""

    def test_nvidia_prefix_is_registered(self) -> None:
        assert "nvidia:" in _KNOWN_PREFIXES
        assert ("nvidia:", build_nvidia_model) in _PREFIX_BUILDERS


class TestNvidiaModelBuilder:
    """build_nvidia_model wires ChatOpenAI at the right host/key/model."""

    @staticmethod
    def _capture_chat_openai(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        langchain_openai = pytest.importorskip("langchain_openai")
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            langchain_openai,
            "ChatOpenAI",
            lambda **kwargs: captured.update(kwargs) or object(),
        )
        return captured

    def test_cloud_keeps_publisher_segment_and_uses_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture_chat_openai(monkeypatch)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xyz")

        build_nvidia_model("meta/llama-3.3-70b-instruct", 0.3)

        # NIM expects the full publisher/model id — the segment must NOT be stripped.
        assert captured["model"] == "meta/llama-3.3-70b-instruct"
        assert captured["base_url"] == _CLOUD_BASE
        assert captured["api_key"] == "nvapi-xyz"
        assert captured["temperature"] == 0.3

    def test_on_prem_without_key_uses_placeholder_and_appends_v1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture_chat_openai(monkeypatch)
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")

        build_nvidia_model("meta/llama-3.1-8b-instruct", 0.0)

        assert captured["base_url"] == "http://nim.local:8000/v1"
        assert captured["api_key"]  # non-empty placeholder local NIM ignores
        assert captured["model"] == "meta/llama-3.1-8b-instruct"

    def test_cloud_without_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("langchain_openai")
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)

        with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
            build_nvidia_model("meta/llama-3.3-70b-instruct", 0.0)


class TestNvidiaNativeBackend:
    """The native MultiBackend path resolves nvidia: too."""

    def test_prefix_map_routes_nvidia(self) -> None:
        assert PREFIX_MAP["nvidia:"] == "nvidia"

    def test_cloud_defaults_and_strips_only_provider_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        backend = NvidiaBackend(api_key="nvapi-xyz")
        # Only the nvidia: prefix is stripped on the wire, never the publisher.
        assert backend._provider_prefix == "nvidia:"
        assert backend.base_url == _CLOUD_BASE

    def test_on_prem_without_key_uses_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")
        backend = NvidiaBackend(api_key="")
        assert backend.base_url == "http://nim.local:8000/v1"
        assert backend.api_key  # non-empty placeholder

    def test_cloud_without_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
            NvidiaBackend(api_key="")

    def test_auto_configure_registers_nvidia_when_keyed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xyz")
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        backend = auto_configure_backend()
        assert "nvidia" in backend.backends  # type: ignore[attr-defined]
