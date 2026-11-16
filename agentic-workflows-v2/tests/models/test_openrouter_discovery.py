"""Tests for full OpenRouter catalog discovery (TTL-cached; ADR-050)."""

from __future__ import annotations

import math
from typing import Any

import httpx
import pytest

from agentic_v2.models import cloud_discovery
from agentic_v2.models.cloud_discovery import (
    _OPENROUTER_STATIC_FALLBACK,
    CloudModelInfo,
    _per_call,
    _per_million,
    _reset_openrouter_discovery_cache,
    _write_openrouter_cache,
    discover_cloud_models,
    discover_openrouter_models,
    nvidia_base_is_documented,
    openai_base_is_nvidia,
    openrouter_base_is_documented,
    resolve_openai_base_url,
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
    "MISTRAL_API_KEY",
    "MISTRAL_BASE_URL",
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


def _priced(
    model_id: str,
    pricing: Any,
    output_modalities: list[str] | None = None,
) -> dict[str, Any]:
    entry = _entry(model_id, output_modalities or ["text"])
    if pricing is not None:
        entry["pricing"] = pricing
    return entry


_PRICED_CATALOG = _Resp(
    {
        "data": [
            _priced("a/free", {"prompt": "0", "completion": "0", "request": "0"}),
            _priced("a/paid", {"prompt": "0.000003", "completion": "0.000015"}),
            _priced("a/fee", {"prompt": "0", "completion": "0", "request": "0.01"}),
            _priced("a/dynamic", {"prompt": "-1", "completion": "-1"}),
            _priced("a/nopricing", None),
            _priced("a/garbage", {"prompt": "abc", "completion": {}, "request": "abc"}),
            _priced("a/numeric", {"prompt": 0, "completion": 0.000002}),
            _priced("a/free", {"prompt": "9", "completion": "9"}),
        ]
    }
)


def _by_id(models: list[CloudModelInfo]) -> dict[str, CloudModelInfo]:
    return {m.id.removeprefix("openrouter:"): m for m in models}


class TestPublishedPrices:
    """The catalog's pricing block rides along on each CloudModelInfo."""

    def test_free_model_keeps_zero_prices(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _PRICED_CATALOG})
        free = _by_id(discover_openrouter_models())["a/free"]
        assert (free.price_in, free.price_out, free.price_request) == (0.0, 0.0, 0.0)

    def test_duplicate_id_keeps_the_first_entry_prices(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _PRICED_CATALOG})
        models = discover_openrouter_models()
        assert [m.id for m in models].count("openrouter:a/free") == 1
        assert _by_id(models)["a/free"].price_in == 0.0

    def test_token_prices_are_per_million_without_float_noise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _PRICED_CATALOG})
        paid = _by_id(discover_openrouter_models())["a/paid"]
        assert (paid.price_in, paid.price_out) == (3.0, 15.0)
        assert paid.price_request is None

    def test_request_fee_is_kept_in_dollars_per_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _PRICED_CATALOG})
        fee = _by_id(discover_openrouter_models())["a/fee"]
        assert (fee.price_in, fee.price_out, fee.price_request) == (0.0, 0.0, 0.01)

    def test_dynamic_price_marker_stays_negative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _PRICED_CATALOG})
        dynamic = _by_id(discover_openrouter_models())["a/dynamic"]
        assert dynamic.price_in is not None and dynamic.price_in < 0
        assert dynamic.price_out is not None and dynamic.price_out < 0

    def test_missing_pricing_block_is_none_never_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _PRICED_CATALOG})
        bare = _by_id(discover_openrouter_models())["a/nopricing"]
        assert (bare.price_in, bare.price_out, bare.price_request) == (None, None, None)

    def test_unreadable_values_never_become_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _PRICED_CATALOG})
        garbage = _by_id(discover_openrouter_models())["a/garbage"]
        assert garbage.price_in is None
        assert garbage.price_out is None
        assert garbage.price_request is not None
        assert math.isnan(garbage.price_request)

    def test_numeric_json_values_are_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _PRICED_CATALOG})
        numeric = _by_id(discover_openrouter_models())["a/numeric"]
        assert (numeric.price_in, numeric.price_out) == (0.0, 2.0)

    def test_static_fallback_ids_carry_no_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _Resp(None, status=500)})
        fallback = discover_openrouter_models()
        assert [m.id for m in fallback] == _STATIC_PREFIXED
        assert any(m.id.endswith(":free") for m in fallback)
        assert all(
            (m.price_in, m.price_out, m.price_request) == (None, None, None)
            for m in fallback
        )

    def test_other_providers_carry_no_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        _route(
            monkeypatch,
            {
                "https://api.openai.com/v1/models": _Resp({"data": [{"id": "gpt-x"}]}),
                _OPENROUTER: _PRICED_CATALOG,
            },
        )
        openai = [m for m in discover_cloud_models() if m.id.startswith("openai:")]
        # Fields, not object equality: another test module reloads cloud_discovery,
        # so the class imported here may not be the one discovery instantiates.
        assert [(m.id, m.price_in, m.price_out, m.price_request) for m in openai] == [
            ("openai:gpt-x", None, None, None)
        ]


class TestPriceCache:
    """Prices survive the TTL cache; a cache written before prices existed loads."""

    def test_cache_hit_returns_the_same_prices(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pricing = {"prompt": "0.000003", "completion": "0.000015", "request": "0.5"}
        payload = _Resp({"data": [_priced("a/paid", pricing)]})
        calls = _route(monkeypatch, {_OPENROUTER: payload})

        first = discover_openrouter_models()
        second = discover_openrouter_models()

        assert len(calls) == 1
        assert first == second
        assert (second[0].price_in, second[0].price_out, second[0].price_request) == (
            3.0,
            15.0,
            0.5,
        )

    def test_stale_cache_served_after_failed_refetch_keeps_prices(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_OPENROUTER: _PRICED_CATALOG})
        live = _by_id(discover_openrouter_models())

        monkeypatch.setattr(cloud_discovery, "_OPENROUTER_CACHE_TTL_SECONDS", 0.0)
        _route(monkeypatch, {})
        stale = _by_id(discover_openrouter_models())

        assert stale["a/paid"] == live["a/paid"]
        assert stale["a/fee"] == live["a/fee"]
        assert stale["a/free"] == live["a/free"]

    def test_entries_cached_without_price_fields_still_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        legacy = [
            cloud_discovery.CloudModelInfo(id="openrouter:a/old")
        ]  # the pre-price shape
        _write_openrouter_cache(legacy)
        calls = _route(monkeypatch, {})

        loaded = discover_openrouter_models()

        assert calls == []  # served from cache
        assert loaded == legacy
        assert (loaded[0].price_in, loaded[0].price_out, loaded[0].price_request) == (
            None,
            None,
            None,
        )

    def test_legacy_stale_entry_is_reused_when_refetch_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_openrouter_cache([cloud_discovery.CloudModelInfo(id="openrouter:a/old")])
        monkeypatch.setattr(cloud_discovery, "_OPENROUTER_CACHE_TTL_SECONDS", 0.0)
        _route(monkeypatch, {})

        assert [m.id for m in discover_openrouter_models()] == ["openrouter:a/old"]


class TestPriceParsers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0", 0.0),
            ("0.000003", 3.0),
            (" 0.0000001 ", 0.1),
            (0, 0.0),
            (0.000002, 2.0),
            ("-1", -1_000_000.0),
        ],
    )
    def test_per_million_reads_finite_numbers(self, raw: Any, expected: float) -> None:
        assert _per_million(raw) == expected

    @pytest.mark.parametrize(
        "raw", [None, "", "abc", "NaN", "Infinity", True, False, [], {}, "1e999999999"]
    )
    def test_per_million_never_turns_junk_into_a_price(self, raw: Any) -> None:
        assert _per_million(raw) is None

    @pytest.mark.parametrize(
        ("raw", "expected"), [("0", 0.0), ("0.01", 0.01), (1, 1.0)]
    )
    def test_per_call_reads_numbers(self, raw: Any, expected: float) -> None:
        assert _per_call(raw) == expected

    def test_per_call_absent_is_none(self) -> None:
        assert _per_call(None) is None

    @pytest.mark.parametrize("raw", ["", "abc", True, [], {}])
    def test_per_call_unreadable_is_nan_not_no_fee(self, raw: Any) -> None:
        result = _per_call(raw)
        assert result is not None
        assert math.isnan(result)


class TestDocumentedOrigin:
    def test_default_base_is_documented(self) -> None:
        assert openrouter_base_is_documented() is True
        assert nvidia_base_is_documented() is True

    @pytest.mark.parametrize(
        "base",
        [
            "https://openrouter.ai/api/v1/",
            "https://OpenRouter.ai/api/v1",
            "https://openrouter.ai:443/api/v1",
            "https://openrouter.ai",
        ],
    )
    def test_equivalent_spellings_of_the_documented_origin(
        self, monkeypatch: pytest.MonkeyPatch, base: str
    ) -> None:
        monkeypatch.setenv("OPENROUTER_BASE_URL", base)
        assert openrouter_base_is_documented() is True

    @pytest.mark.parametrize(
        "base",
        [
            "http://gateway.local:8080",
            "http://openrouter.ai/api/v1",
            "https://openrouter.ai:8443/api/v1",
            "https://openrouter.ai.evil.example/api/v1",
        ],
    )
    def test_any_other_origin_is_not_documented(
        self, monkeypatch: pytest.MonkeyPatch, base: str
    ) -> None:
        monkeypatch.setenv("OPENROUTER_BASE_URL", base)
        assert openrouter_base_is_documented() is False

    def test_on_prem_nim_is_not_the_documented_nvidia_origin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")
        assert nvidia_base_is_documented() is False


class TestOpenaiBase:
    def test_default_base_is_openai_not_nvidia(self) -> None:
        assert resolve_openai_base_url() == "https://api.openai.com/v1"
        assert openai_base_is_nvidia() is False

    def test_resolution_order_and_trailing_slash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_BASE", "http://b.local/v1/")
        assert resolve_openai_base_url() == "http://b.local/v1"
        monkeypatch.setenv("OPENAI_BASE_URL", "http://a.local/v1")
        assert resolve_openai_base_url() == "http://a.local/v1"

    def test_models_probe_still_targets_the_resolved_base(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")
        calls = _route(
            monkeypatch,
            {"https://integrate.api.nvidia.com/v1/models": _Resp({"data": []})},
        )
        cloud_discovery.discover_openai_models()
        assert [c[0] for c in calls] == ["https://integrate.api.nvidia.com/v1/models"]

    @pytest.mark.parametrize(
        ("base", "expected"),
        [
            ("https://integrate.api.nvidia.com/v1", True),
            ("https://integrate.api.nvidia.com", True),
            ("https://integrate.api.nvidia.com/v1/", True),
            ("http://integrate.api.nvidia.com/v1", False),
            ("https://integrate.api.nvidia.com:8443/v1", False),
            ("https://integrate.api.nvidia.com.evil.example/v1", False),
            ("https://api.openai.com/v1", False),
            ("http://localhost:4000", False),
            ("garbage", False),
        ],
    )
    def test_origin_comparison(
        self, monkeypatch: pytest.MonkeyPatch, base: str, expected: bool
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", base)
        assert openai_base_is_nvidia() is expected

    def test_on_prem_nim_override_does_not_move_the_documented_origin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://nim.local:8000/v1")
        assert openai_base_is_nvidia() is False
