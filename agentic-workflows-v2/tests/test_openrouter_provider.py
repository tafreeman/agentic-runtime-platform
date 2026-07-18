"""Tests for the first-class OpenRouter provider (LangChain path).

OpenRouter is an OpenAI-compatible aggregator: model ids keep their
``publisher/model`` form and free-tier ids append ``:free``, so a full app id
(``openrouter:meta-llama/llama-3.1-8b-instruct:free``) carries TWO colons.
These tests lock in the provider gate, the verbatim id round-trip through the
LangChain builder (only the first ``openrouter:`` prefix is stripped), and the
honest availability flag on discovery-merged catalog entries.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentic_v2.langchain import models as langchain_models
from agentic_v2.langchain.model_builders import build_openrouter_model
from agentic_v2.langchain.model_utils import (
    PROVIDER_ENV_KEYS,
    is_provider_available,
    provider_prefix,
)
from agentic_v2.langchain.models import (
    _KNOWN_PREFIXES,
    _PREFIX_BUILDERS,
    _build_model_by_prefix,
    enumerate_known_models,
)
from agentic_v2.models.cloud_discovery import CloudModelInfo

_FREE_ID = "openrouter:meta-llama/llama-3.1-8b-instruct:free"
_DEFAULT_BASE = "https://openrouter.ai/api/v1"


def _capture_chat_openai(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``ChatOpenAI`` with a kwargs recorder (no network, no client)."""
    langchain_openai = pytest.importorskip("langchain_openai")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        langchain_openai,
        "ChatOpenAI",
        lambda **kwargs: captured.update(kwargs) or object(),
    )
    return captured


class TestOpenRouterProviderGate:
    """Openrouter is a keyed provider gated on OPENROUTER_API_KEY."""

    def test_openrouter_in_provider_env_keys(self) -> None:
        assert PROVIDER_ENV_KEYS["openrouter"] == ["OPENROUTER_API_KEY"]

    def test_unavailable_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert is_provider_available("openrouter") is False

    def test_available_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        assert is_provider_available("openrouter") is True

    def test_provider_prefix_stops_at_first_colon(self) -> None:
        # Two-colon free-tier id: the provider is everything before colon #1.
        assert provider_prefix(_FREE_ID) == "openrouter"


class TestOpenRouterLangChainDispatch:
    """openrouter: must be a known prefix with a builder, not an Ollama name."""

    def test_openrouter_prefix_is_registered(self) -> None:
        assert "openrouter:" in _KNOWN_PREFIXES
        assert ("openrouter:", build_openrouter_model) in _PREFIX_BUILDERS

    def test_dispatch_strips_only_the_first_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _capture_chat_openai(monkeypatch)
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        model = _build_model_by_prefix(_FREE_ID, 0.0)

        assert model is not None
        # Only "openrouter:" is stripped; publisher and :free suffix survive.
        assert captured["model"] == "meta-llama/llama-3.1-8b-instruct:free"


class TestOpenRouterModelBuilder:
    """build_openrouter_model wires ChatOpenAI at the right host/key/headers."""

    def test_wires_base_url_key_header_and_verbatim_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _capture_chat_openai(monkeypatch)
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        build_openrouter_model("meta-llama/llama-3.1-8b-instruct:free", 0.3)

        # OpenRouter expects the full publisher/model[:free] id — verbatim.
        assert captured["model"] == "meta-llama/llama-3.1-8b-instruct:free"
        assert captured["base_url"] == _DEFAULT_BASE
        assert captured["api_key"] == "test-key"
        assert captured["temperature"] == 0.3
        assert captured["default_headers"] == {"X-Title": "agentic-runtime-platform"}

    def test_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("langchain_openai")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            build_openrouter_model("meta-llama/llama-3.1-8b-instruct:free", 0.0)

    def test_base_url_override_appends_v1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _capture_chat_openai(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://gateway.local:8080")

        build_openrouter_model("openai/gpt-4o-mini", 0.0)

        assert captured["base_url"] == "http://gateway.local:8080/v1"


class TestMergeCloudModelsAvailability:
    """_merge_cloud_models derives ``available`` from the provider key env.

    The OpenRouter catalog is public even without a key, so the availability
    flag is what tells the console inference credentials are missing. Keyed
    providers are unaffected in practice: a successful authenticated fetch
    implies the key env is set.
    """

    @staticmethod
    def _patch_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)  # LLM mode
        monkeypatch.setattr(langchain_models, "discover_ollama_models", lambda: [])
        monkeypatch.setattr(langchain_models, "discover_lmstudio_models", lambda: [])
        monkeypatch.setattr(langchain_models, "discover_onnx_models", lambda: [])
        monkeypatch.setattr(
            langchain_models,
            "discover_cloud_models",
            lambda: [CloudModelInfo(id=_FREE_ID)],
        )

    def test_fallback_entry_unavailable_without_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_discovery(monkeypatch)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        by_id = {m["id"]: m for m in enumerate_known_models()}

        entry = by_id.get(_FREE_ID)
        assert entry is not None
        assert entry["provider"] == "openrouter"
        assert entry["tier"] == 0
        assert entry["available"] is False

    def test_fallback_entry_available_with_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_discovery(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        by_id = {m["id"]: m for m in enumerate_known_models()}

        entry = by_id.get(_FREE_ID)
        assert entry is not None
        assert entry["available"] is True
