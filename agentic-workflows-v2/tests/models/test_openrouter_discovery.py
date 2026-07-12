"""Tests for OpenRouter catalog discovery (curated, TTL-cached; ADR-050).

All HTTP is mocked at ``httpx.get`` with a per-URL router (the
``test_cloud_discovery`` pattern). Covers the keyless static fallback (zero
network calls), live-catalog curation (free + flagship buckets, caps, text
filter), auth headers, fetch-failure fallbacks, and the TTL cache this probe
deliberately adds on top of ADR-039's cache-free baseline.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentic_v2.models import cloud_discovery
from agentic_v2.models.cloud_discovery import (
    _OPENROUTER_FLAGSHIP_CAP,
    _OPENROUTER_FREE_CAP,
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
) -> list[tuple[str, dict[str, str]]]:
    """Install a ``httpx.get`` serving ``routes``; record (url, headers)."""
    calls: list[tuple[str, dict[str, str]]] = []

    def _fake_get(
        url: str, headers: Any = None, params: Any = None, timeout: Any = None
    ) -> _Resp:
        calls.append((url, headers or {}))
        resp = routes.get(url)
        if resp is None:
            raise httpx.ConnectError("connection refused")
        return resp

    monkeypatch.setattr(cloud_discovery.httpx, "get", _fake_get)
    return calls


def _entry(model_id: str, output_modalities: list[str] | None = None) -> dict[str, Any]:
    """A minimal OpenRouter ``/models`` catalog entry."""
    architecture: dict[str, Any] = {
        "input_modalities": ["text"],
        "tokenizer": "Other",
    }
    if output_modalities is not None:
        architecture["output_modalities"] = output_modalities
    return {
        "id": model_id,
        "name": model_id,
        "context_length": 131072,
        "architecture": architecture,
        "pricing": {"prompt": "0", "completion": "0"},
        "supported_parameters": ["temperature", "tools"],
    }


_CATALOG = _Resp(
    {
        "data": [
            # Free-tier ids (kept; sorted, listed first).
            _entry("qwen/qwen3-14b:free", ["text"]),
            _entry("meta-llama/llama-3.1-8b-instruct:free", ["text"]),
            # Flagship-family ids (kept; sorted, after the free bucket).
            _entry("openai/gpt-4o-mini", ["text"]),
            _entry("anthropic/claude-sonnet-4", ["text"]),
            # Embeddings id — blocked by the shared non-chat blocklist even
            # though it matches the qwen flagship-family prefix.
            _entry("qwen/qwen3-embedding-8b", ["text"]),
            # Non-text output — matches "openai/gpt-4o" but must be dropped.
            _entry("openai/gpt-4o-audio-preview", ["audio"]),
            # Neither free nor flagship-family — curated out.
            _entry("nousresearch/hermes-3-llama-3.1-405b", ["text"]),
        ]
    }
)

_CATALOG_IDS = [
    "openrouter:meta-llama/llama-3.1-8b-instruct:free",
    "openrouter:qwen/qwen3-14b:free",
    # Flagship picks follow _OPENROUTER_FLAGSHIP_PREFIXES declaration order
    # (family-fair round-robin), not global alphabetical order.
    "openrouter:openai/gpt-4o-mini",
    "openrouter:anthropic/claude-sonnet-4",
]


class TestKeylessFallback:
    def test_no_key_returns_static_fallback_without_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _route(monkeypatch, {})
        result = [m.id for m in discover_openrouter_models()]
        assert result == _STATIC_PREFIXED
        assert calls == []  # no key -> zero network calls

    def test_static_fallback_is_never_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _route(monkeypatch, {_OPENROUTER: _CATALOG})
        assert [m.id for m in discover_openrouter_models()] == _STATIC_PREFIXED
        assert calls == []
        # A later keyed call must fetch live, not read the fallback from cache.
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        assert [m.id for m in discover_openrouter_models()] == _CATALOG_IDS
        assert len(calls) == 1


class TestLiveCatalog:
    def test_curates_free_and_flagship_with_auth_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        calls = _route(monkeypatch, {_OPENROUTER: _CATALOG})

        result = [m.id for m in discover_openrouter_models()]

        # Free ids first (sorted), then flagship (family-fair round-robin);
        # embeddings, non-text-output, and non-curated ids are all dropped.
        assert result == _CATALOG_IDS
        assert calls[0][0] == _OPENROUTER
        assert calls[0][1]["Authorization"] == "Bearer test-key"

    def test_flagship_cap_is_family_fair(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One prolific publisher must not consume every flagship slot.

        The live catalog carries 15+ ``anthropic/claude*`` ids; a global
        alphabetical cap would starve every other family. Slots are filled
        round-robin across families (declaration order), newest-ish
        (reverse-sorted) first.
        """
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        free = [f"pub/free-model-{i:03d}:free" for i in range(30)]
        families = ("openai/gpt-4o-var", "anthropic/claude-var", "x-ai/grok-var")
        flagship = [f"{fam}-{i:03d}" for fam in families for i in range(10)]
        payload = _Resp({"data": [_entry(mid, ["text"]) for mid in free + flagship]})
        _route(monkeypatch, {_OPENROUTER: payload})

        result = [m.id for m in discover_openrouter_models()]

        expected = [f"openrouter:{m}" for m in sorted(free)[:_OPENROUTER_FREE_CAP]]
        # Round-robin ranks: each family's reverse-sorted ids, one per family
        # per rank, families in _OPENROUTER_FLAGSHIP_PREFIXES declaration
        # order (openai/gpt-4o before anthropic/claude before x-ai/grok).
        expected += [
            f"openrouter:{fam}-{9 - rank:03d}"
            for rank in range(_OPENROUTER_FLAGSHIP_CAP // len(families))
            for fam in families
        ]
        assert result == expected
        assert len(result) == _OPENROUTER_FREE_CAP + _OPENROUTER_FLAGSHIP_CAP
        flagship_picks = result[_OPENROUTER_FREE_CAP:]
        for fam in families:
            assert any(f"openrouter:{fam}" in pick for pick in flagship_picks)

    def test_single_family_flagship_still_capped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        flagship = [f"anthropic/claude-var-{i:03d}" for i in range(20)]
        payload = _Resp({"data": [_entry(mid, ["text"]) for mid in flagship]})
        _route(monkeypatch, {_OPENROUTER: payload})

        result = [m.id for m in discover_openrouter_models()]

        expected = [
            f"openrouter:{m}"
            for m in sorted(flagship, reverse=True)[:_OPENROUTER_FLAGSHIP_CAP]
        ]
        assert result == expected

    def test_empty_curation_falls_back_and_is_not_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 200 catalog with nothing curatable must not beat the fallback.

        e.g. OPENROUTER_BASE_URL pointing at a self-hosted gateway whose model
        list matches no ``:free``/flagship pattern — serving (and caching) an
        empty listing would be strictly worse than the static fallback.
        """
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        payload = _Resp({"data": [_entry("mycorp/internal-model", ["text"])]})
        calls = _route(monkeypatch, {_OPENROUTER: payload})

        assert [m.id for m in discover_openrouter_models()] == _STATIC_PREFIXED
        # Not cached as a live result: the next call re-fetches.
        assert [m.id for m in discover_openrouter_models()] == _STATIC_PREFIXED
        assert len(calls) == 2

    def test_base_url_override_probed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://gateway.local:8080")
        calls = _route(monkeypatch, {"http://gateway.local:8080/v1/models": _CATALOG})
        assert [m.id for m in discover_openrouter_models()] == _CATALOG_IDS
        assert calls[0][0] == "http://gateway.local:8080/v1/models"


class TestFailureFallbacks:
    def test_fetch_failure_without_cache_falls_back_to_static(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        _route(monkeypatch, {_OPENROUTER: _Resp(None, status=500)})
        assert [m.id for m in discover_openrouter_models()] == _STATIC_PREFIXED

    def test_fetch_failure_reuses_last_live_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        _route(monkeypatch, {_OPENROUTER: _CATALOG})
        assert [m.id for m in discover_openrouter_models()] == _CATALOG_IDS

        # Expire the TTL so the next call re-fetches, and make that fail:
        # the stale live listing must win over the static fallback.
        monkeypatch.setattr(cloud_discovery, "_OPENROUTER_CACHE_TTL_SECONDS", 0.0)
        _route(monkeypatch, {})
        assert [m.id for m in discover_openrouter_models()] == _CATALOG_IDS


class TestTtlCache:
    def test_second_call_within_ttl_skips_http(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        calls = _route(monkeypatch, {_OPENROUTER: _CATALOG})

        first = [m.id for m in discover_openrouter_models()]
        second = [m.id for m in discover_openrouter_models()]

        assert first == second == _CATALOG_IDS
        assert len(calls) == 1  # served from the TTL cache

    def test_reset_forces_refetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        calls = _route(monkeypatch, {_OPENROUTER: _CATALOG})

        discover_openrouter_models()
        _reset_openrouter_discovery_cache()
        discover_openrouter_models()

        assert len(calls) == 2


class TestAggregateAndBaseUrl:
    def test_discover_cloud_models_includes_openrouter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        _route(monkeypatch, {_OPENROUTER: _CATALOG})
        # Only openrouter is keyed; the other probes contribute nothing.
        assert [m.id for m in discover_cloud_models()] == _CATALOG_IDS

    def test_aggregate_carries_static_fallback_when_keyless(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _route(monkeypatch, {})
        assert [m.id for m in discover_cloud_models()] == _STATIC_PREFIXED
        assert calls == []

    def test_resolve_base_url_default_and_normalization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shared resolver guarantees a single trailing /v1 segment."""
        assert resolve_openrouter_base_url() == "https://openrouter.ai/api/v1"
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://gateway.local:8080/v1/")
        assert resolve_openrouter_base_url() == "http://gateway.local:8080/v1"
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://gateway.local:8080")
        assert resolve_openrouter_base_url() == "http://gateway.local:8080/v1"
