"""Tests for live cloud-provider model discovery (ADR-039).

All HTTP is mocked at ``httpx.get`` with a per-URL router. Covers keyed happy
paths, the no-key short-circuit (no network call), chat filtering, schema
quirks (Gemini ``models/`` prefix + ``generateContent`` gate, GitHub top-level
array), and best-effort failure handling.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentic_v2.models import cloud_discovery
from agentic_v2.models.cloud_discovery import (
    discover_anthropic_models,
    discover_cloud_models,
    discover_gemini_models,
    discover_github_models,
    discover_nvidia_models,
    discover_openai_models,
    resolve_nvidia_base_url,
)

_OPENAI = "https://api.openai.com/v1/models"
_ANTHROPIC = "https://api.anthropic.com/v1/models"
_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models"
_GITHUB = "https://models.github.ai/catalog/models"

_NVIDIA = "https://integrate.api.nvidia.com/v1/models"

_ALL_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_ORG_ID",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _ALL_KEYS:
        monkeypatch.delenv(var, raising=False)


class _Resp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")

    def json(self) -> Any:
        return self._payload


def _route(
    monkeypatch: pytest.MonkeyPatch, routes: dict[str, _Resp]
) -> list[tuple[str, dict[str, str]]]:
    """Install a ``httpx.get`` serving ``routes``; record (url, headers)."""
    calls: list[tuple[str, dict[str, str]]] = []

    def _fake_get(
        url: str, headers: Any = None, params: Any = None, timeout: Any = None
    ):
        calls.append((url, headers or {}))
        resp = routes.get(url)
        if resp is None:
            raise httpx.ConnectError("connection refused")
        return resp

    monkeypatch.setattr(cloud_discovery.httpx, "get", _fake_get)
    return calls


class TestOpenAI:
    def test_lists_chat_models_and_filters_non_chat(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        calls = _route(
            monkeypatch,
            {
                _OPENAI: _Resp(
                    {
                        "data": [
                            {"id": "gpt-4o"},
                            {"id": "o3-mini"},
                            {"id": "text-embedding-3-large"},
                            {"id": "whisper-1"},
                            {"id": "dall-e-3"},
                        ]
                    }
                )
            },
        )
        result = [m.id for m in discover_openai_models()]
        assert result == ["openai:gpt-4o", "openai:o3-mini"]
        # Bearer auth sent.
        assert calls[0][1]["Authorization"] == "Bearer sk-test"

    def test_no_key_makes_no_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _route(monkeypatch, {})
        assert discover_openai_models() == []
        assert calls == []

    def test_base_url_override_appends_v1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:4000")
        calls = _route(
            monkeypatch,
            {"http://localhost:4000/v1/models": _Resp({"data": [{"id": "gpt-4o"}]})},
        )
        assert [m.id for m in discover_openai_models()] == ["openai:gpt-4o"]
        assert calls[0][0] == "http://localhost:4000/v1/models"


class TestAnthropic:
    def test_lists_models_with_version_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        calls = _route(
            monkeypatch,
            {
                _ANTHROPIC: _Resp(
                    {"data": [{"id": "claude-sonnet-4-6"}, {"id": "claude-opus-4-5"}]}
                )
            },
        )
        result = [m.id for m in discover_anthropic_models()]
        assert result == ["anthropic:claude-sonnet-4-6", "anthropic:claude-opus-4-5"]
        assert calls[0][1]["x-api-key"] == "sk-ant"
        assert calls[0][1]["anthropic-version"]

    def test_server_error_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        _route(monkeypatch, {_ANTHROPIC: _Resp(None, status=401)})
        assert discover_anthropic_models() == []


class TestGemini:
    def test_filters_to_generate_content_and_strips_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "g-key")
        _route(
            monkeypatch,
            {
                _GEMINI: _Resp(
                    {
                        "models": [
                            {
                                "name": "models/gemini-2.5-flash",
                                "supportedGenerationMethods": ["generateContent"],
                            },
                            {
                                "name": "models/text-embedding-004",
                                "supportedGenerationMethods": ["embedContent"],
                            },
                            {
                                "name": "models/gemini-3-pro",
                                "supportedGenerationMethods": [
                                    "generateContent",
                                    "countTokens",
                                ],
                            },
                        ]
                    }
                )
            },
        )
        result = [m.id for m in discover_gemini_models()]
        # Embedding model (no generateContent) dropped; "models/" prefix stripped.
        assert result == ["gemini:gemini-2.5-flash", "gemini:gemini-3-pro"]

    def test_google_api_key_also_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "g-key")
        _route(
            monkeypatch,
            {
                _GEMINI: _Resp(
                    {
                        "models": [
                            {
                                "name": "models/gemini-2.5-flash",
                                "supportedGenerationMethods": ["generateContent"],
                            }
                        ]
                    }
                )
            },
        )
        assert [m.id for m in discover_gemini_models()] == ["gemini:gemini-2.5-flash"]


class TestGitHub:
    def test_lists_catalog_array_keeping_publisher_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
        calls = _route(
            monkeypatch,
            {
                _GITHUB: _Resp(
                    [
                        {"id": "openai/gpt-4.1"},
                        {"id": "meta/Llama-4-Scout-17B"},
                        {"id": "cohere/embed-v3-english"},
                    ]
                )
            },
        )
        result = [m.id for m in discover_github_models()]
        # publisher/model id preserved; embedding filtered.
        assert result == ["gh:openai/gpt-4.1", "gh:meta/Llama-4-Scout-17B"]
        assert calls[0][1]["Authorization"] == "Bearer ghp_x"


class TestNVIDIA:
    def test_lists_chat_models_and_filters_non_chat(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        calls = _route(
            monkeypatch,
            {
                _NVIDIA: _Resp(
                    {
                        "data": [
                            {"id": "meta/llama-3.1-70b-instruct"},
                            {"id": "nvidia/nemotron-mini-4b-instruct"},
                            {"id": "nvidia/nv-embed-v1"},  # embedding → filtered
                            {
                                "id": "nvidia/llama-3.2-nv-rerankqa-1b-v1"
                            },  # rerank → filtered
                        ]
                    }
                )
            },
        )
        result = [m.id for m in discover_nvidia_models()]
        assert result == [
            "nvidia:meta/llama-3.1-70b-instruct",
            "nvidia:nvidia/nemotron-mini-4b-instruct",
        ]
        assert calls[0][1]["Authorization"] == "Bearer nvapi-test"

    def test_no_key_makes_no_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _route(monkeypatch, {})
        assert discover_nvidia_models() == []
        assert calls == []

    def test_base_url_override_for_on_prem_nim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """NVIDIA_BASE_URL lets on-prem NIM deployments be probed."""
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000/v1")
        calls = _route(
            monkeypatch,
            {
                "http://nim.local:8000/v1/models": _Resp(
                    {"data": [{"id": "meta/llama-3.1-8b-instruct"}]}
                )
            },
        )
        assert [m.id for m in discover_nvidia_models()] == [
            "nvidia:meta/llama-3.1-8b-instruct"
        ]
        assert calls[0][0] == "http://nim.local:8000/v1/models"

    def test_base_url_without_v1_suffix_gets_v1_appended(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A NVIDIA_BASE_URL missing /v1 must still hit /v1/models (Gemini review
        #132)."""
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")
        calls = _route(
            monkeypatch,
            {
                "http://nim.local:8000/v1/models": _Resp(
                    {"data": [{"id": "meta/llama-3.1-8b-instruct"}]}
                )
            },
        )
        assert [m.id for m in discover_nvidia_models()] == [
            "nvidia:meta/llama-3.1-8b-instruct"
        ]
        assert calls[0][0] == "http://nim.local:8000/v1/models"

    def test_server_error_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        _route(monkeypatch, {_NVIDIA: _Resp(None, status=401)})
        assert discover_nvidia_models() == []

    def test_resolve_base_url_default_and_normalization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shared resolver guarantees a single trailing /v1 segment."""
        assert resolve_nvidia_base_url() == "https://integrate.api.nvidia.com/v1"
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000/v1/")
        assert resolve_nvidia_base_url() == "http://nim.local:8000/v1"
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")
        assert resolve_nvidia_base_url() == "http://nim.local:8000/v1"


class TestAggregate:
    def test_only_keyed_providers_probed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
        calls = _route(
            monkeypatch,
            {
                _OPENAI: _Resp({"data": [{"id": "gpt-4o"}]}),
                _GITHUB: _Resp([{"id": "openai/gpt-4.1"}]),
            },
        )
        result = sorted(m.id for m in discover_cloud_models())
        assert result == ["gh:openai/gpt-4.1", "openai:gpt-4o"]
        # Anthropic + Gemini have no key → never called.
        probed = {url for url, _ in calls}
        assert probed == {_OPENAI, _GITHUB}

    def test_no_keys_returns_empty_without_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _route(monkeypatch, {})
        assert discover_cloud_models() == []
        assert calls == []
