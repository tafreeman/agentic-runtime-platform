"""Tests for full OpenRouter catalog discovery (TTL-cached; ADR-050)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentic_v2.models import cloud_discovery
from agentic_v2.models.cloud_discovery import (
    _OPENROUTER_STATIC_FALLBACK,
    _reset_openrouter_discovery_cache,
    discover_cloud_models,
    discover_openrouter_models,
    resolve_openrouter_base_url,
)

_OPENROUTER = "https://openrouter.ai/api/v1/models"
_STATIC_PREFIXED = [f"openrouter:{name}" for name in _OPENROUTER_STATIC_FALLBACK]

_ALL_KEYS = (
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
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
) -> list[tuple[str, dict[str, str], dict[str, str]]]:
    """Install a URL router and record URL, headers, and query params."""
    calls: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def _fake_get(
        url: str, headers: Any = None, params: Any = None, timeout: Any = None
    ) -> _Resp:
        calls.append((url, headers or {}, params or {}))
        response = routes.get(url)
        if response is None:
            raise httpx.ConnectError("connection refused")
        return response

    monkeypatch.setattr(cloud_discovery.httpx, "get", _fake_get)
    return calls


def _entry(model_id: str, output_modalities: list[str] | None = None) -> dict[str, Any]:
    architecture: dict[str, Any] = {"input_modalities": ["text"]}
    if output_modalities is not None:
        architecture["output_modalities"] = output_modalities
    return {"id": model_id, "architecture": architecture}


_CATALOG = _Resp(
    {
        "data": [
            _entry("qwen/qwen3-14b:free", ["text"]),
            _entry("meta-llama/llama-3.1-8b-instruct:free", ["text"]),
            _entry("openai/gpt-4o-mini", ["text"]),
            _entry("anthropic/claude-sonnet-4", ["text"]),
            _entry("nousresearch/hermes-3-llama-3.1-405b", ["text"]),
            _entry("qwen/qwen3-embedding-8b", ["text"]),
            _entry("openai/gpt-4o-audio-preview", ["audio"]),
            _entry("openai/gpt-image-and-text", ["text", "image"]),
            _entry("openai/gpt-4o-mini", ["text"]),
        ]
    }
)

_CATALOG_IDS = [
    "openrouter:anthropic/claude-sonnet-4",
    "openrouter:meta-llama/llama-3.1-8b-instruct:free",
    "openrouter:nousresearch/hermes-3-llama-3.1-405b",
    "openrouter:openai/gpt-4o-mini",
    "openrouter:openai/gpt-image-and-text",
    "openrouter:qwen/qwen3-14b:free",
]


class TestLiveCatalog:
    def test_keyless_request_fetches_public_full_catalog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _route(monkeypatch, {_OPENROUTER: _CATALOG})

        assert [m.id for m in discover_openrouter_models()] == _CATALOG_IDS
        assert calls == [
            (_OPENROUTER, {}, {"output_modalities": "all"}),
        ]

    def test_configured_key_is_sent_as_bearer_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        calls = _route(monkeypatch, {_OPENROUTER: _CATALOG})

        assert [m.id for m in discover_openrouter_models()] == _CATALOG_IDS
        assert calls[0][1]["Authorization"] == "Bearer test-key"
        assert calls[0][2] == {"output_modalities": "all"}

    def test_keeps_every_chat_compatible_model_without_caps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model_ids = [f"publisher/model-{index:03d}" for index in range(75)]
        payload = _Resp(
            {"data": [_entry(model_id, ["text"]) for model_id in model_ids]}
        )
        _route(monkeypatch, {_OPENROUTER: payload})

        assert [m.id for m in discover_openrouter_models()] == [
            f"openrouter:{model_id}" for model_id in model_ids
        ]

    def test_base_url_override_probed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://gateway.local:8080")
        url = "http://gateway.local:8080/v1/models"
        calls = _route(monkeypatch, {url: _CATALOG})

        assert [m.id for m in discover_openrouter_models()] == _CATALOG_IDS
        assert calls[0][0] == url

    def test_empty_live_listing_falls_back_and_is_not_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _route(monkeypatch, {_OPENROUTER: _Resp({"data": []})})

        assert [m.id for m in discover_openrouter_models()] == _STATIC_PREFIXED
        assert [m.id for m in discover_openrouter_models()] == _STATIC_PREFIXED
        assert len(calls) == 2


class TestFailureFallbacks:
    def test_fetch_failure_without_cache_falls_back_to_static(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _Resp(None, status=500)})
        assert [m.id for m in discover_openrouter_models()] == _STATIC_PREFIXED

    def test_fetch_failure_reuses_last_live_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _CATALOG})
        assert [m.id for m in discover_openrouter_models()] == _CATALOG_IDS

        monkeypatch.setattr(cloud_discovery, "_OPENROUTER_CACHE_TTL_SECONDS", 0.0)
        _route(monkeypatch, {})
        assert [m.id for m in discover_openrouter_models()] == _CATALOG_IDS


class TestTtlCache:
    def test_second_call_within_ttl_skips_http(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _route(monkeypatch, {_OPENROUTER: _CATALOG})

        first = [m.id for m in discover_openrouter_models()]
        second = [m.id for m in discover_openrouter_models()]

        assert first == second == _CATALOG_IDS
        assert len(calls) == 1

    def test_reset_forces_refetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _route(monkeypatch, {_OPENROUTER: _CATALOG})

        discover_openrouter_models()
        _reset_openrouter_discovery_cache()
        discover_openrouter_models()

        assert len(calls) == 2


class TestAggregateAndBaseUrl:
    def test_discover_cloud_models_includes_keyless_openrouter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _route(monkeypatch, {_OPENROUTER: _CATALOG})
        assert [m.id for m in discover_cloud_models()] == _CATALOG_IDS
        assert calls[0][0] == _OPENROUTER

    def test_resolve_base_url_default_and_normalization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert resolve_openrouter_base_url() == "https://openrouter.ai/api/v1"
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://gateway.local:8080/v1/")
        assert resolve_openrouter_base_url() == "http://gateway.local:8080/v1"
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://gateway.local:8080")
        assert resolve_openrouter_base_url() == "http://gateway.local:8080/v1"
