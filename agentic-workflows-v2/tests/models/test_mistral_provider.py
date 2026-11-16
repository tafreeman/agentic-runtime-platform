"""Tests for the Mistral La Plateforme provider (``mistral:`` ids).

Covers every registration point (a discovered id once fell through to Ollama
silently for another provider), the keyed ``GET /v1/models`` discovery, the
``ChatMistralAI`` builder, and the probe rows -- with all HTTP stubbed at
``httpx.get`` and every environment change made through ``monkeypatch``.

The listing fixture mirrors the shape the live API returned: ``type: "base"``
cards whose ``capabilities`` flags decide chat-ness, Labs models in the same
listing under a ``labs-`` prefix, and ``-latest`` aliases next to dated ids.
"""

from __future__ import annotations

import sys
from typing import Any

import httpx
import pytest

from agentic_v2.langchain.model_builders import build_mistral_model
from agentic_v2.langchain.model_utils import (
    PROVIDER_ENV_KEYS,
    is_provider_available,
    probe_available_providers,
    provider_prefix,
)
from agentic_v2.langchain.models import (
    _KNOWN_PREFIXES,
    _PREFIX_BUILDERS,
    _build_model_by_prefix,
    enumerate_known_models,
    get_chat_model,
)
from agentic_v2.models import cloud_discovery
from agentic_v2.models.cloud_discovery import (
    CloudModelInfo,
    discover_cloud_models,
    discover_mistral_models,
    mistral_base_is_documented,
    resolve_mistral_base_url,
)

_MODELS_URL = "https://api.mistral.ai/v1/models"
_DEFAULT_BASE = "https://api.mistral.ai/v1"
_TEST_KEY = "test-key"

_ENV_VARS = (
    "MISTRAL_API_KEY",
    "MISTRAL_BASE_URL",
    "MISTRAL_FREE_TIER",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OLLAMA_BASE_URL",
    "OLLAMA_API_KEY",
    "LMSTUDIO_HOST",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _ENV_VARS:
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
    """Serve ``routes`` from ``httpx.get``; record (url, headers, params)."""
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


def _card(model_id: str, **extra: Any) -> dict[str, Any]:
    """A ``/v1/models`` card; capability flags go in ``capabilities``."""
    capabilities = dict(extra.pop("caps", {}))
    return {
        "id": model_id,
        "object": "model",
        "type": "base",
        "max_context_length": 131072,
        "aliases": [],
        "capabilities": capabilities,
        **extra,
    }


_CHAT = {"completion_chat": True, "function_calling": True}
_CHAT_VISION = {**_CHAT, "vision": True}
_LABS_CAPS = {**_CHAT_VISION, "reasoning": True, "unified_resources": True}

_LISTING: list[dict[str, Any]] = [
    # Chat, aliases coexisting with dated ids -- each its own entry.
    _card("mistral-medium-latest", caps=_CHAT_VISION),
    _card("mistral-medium-2604", caps=_CHAT_VISION),
    _card("mistral-medium-3-5", caps=_CHAT_VISION),
    _card("mistral-medium-3.5", caps=_CHAT_VISION),
    _card("mistral-small-latest", caps=_CHAT),
    # Labs models: same listing, same endpoint, labs- prefix.
    _card("labs-leanstral-1-5", caps=_LABS_CAPS),
    _card("labs-leanstral-1-5-1", caps=_LABS_CAPS),
    # Chat-capable audio model stays.
    _card("voxtral-small-latest", caps={**_CHAT, "audio": True}),
    # A deprecated model the API still lists is still callable.
    _card(
        "ministral-8b-2410",
        caps={"completion_chat": True},
        deprecation="2026-12-01T00:00:00Z",
    ),
    # Not chat.
    _card("mistral-embed", caps={}),
    _card("codestral-embed-2505", caps={}),
    _card("mistral-moderation-2603", caps={"classification": True, "moderation": True}),
    _card(
        "mistral-ocr-latest",
        caps={**_CHAT_VISION, "ocr": True, "completion_chat": False},
    ),
    _card("voxtral-mini-transcribe", caps={"audio_transcription": True}),
    _card("voxtral-mini-tts", caps={"audio_speech": True}),
    # Retired fine-tune.
    _card("ft:mistral-small:old", caps=_CHAT, archived=True, type="fine-tuned"),
    # Same id twice: one entry.
    _card("mistral-small-latest", caps=_CHAT),
]

_EXPECTED_IDS = [
    "mistral:mistral-medium-latest",
    "mistral:mistral-medium-2604",
    "mistral:mistral-medium-3-5",
    "mistral:mistral-medium-3.5",
    "mistral:mistral-small-latest",
    "mistral:labs-leanstral-1-5",
    "mistral:labs-leanstral-1-5-1",
    "mistral:voxtral-small-latest",
    "mistral:ministral-8b-2410",
]


class TestRegistration:
    """mistral: must be routable and known, not an Ollama fall-through."""

    def test_provider_is_gated_on_its_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert PROVIDER_ENV_KEYS["mistral"] == ["MISTRAL_API_KEY"]
        assert is_provider_available("mistral") is False
        assert probe_available_providers()["mistral"] is False
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        assert is_provider_available("mistral") is True
        assert probe_available_providers()["mistral"] is True

    def test_empty_key_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "")
        assert is_provider_available("mistral") is False

    def test_prefix_is_registered(self) -> None:
        assert "mistral:" in _KNOWN_PREFIXES
        assert ("mistral:", build_mistral_model) in _PREFIX_BUILDERS

    def test_provider_prefix_of_a_labs_id(self) -> None:
        assert provider_prefix("mistral:labs-leanstral-1-5") == "mistral"


class TestDiscovery:
    def test_keeps_exactly_the_chat_models_in_listing_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"object": "list", "data": _LISTING})})

        assert [m.id for m in discover_mistral_models()] == _EXPECTED_IDS

    def test_labs_models_are_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        ids = {m.id for m in discover_mistral_models()}
        assert {"mistral:labs-leanstral-1-5", "mistral:labs-leanstral-1-5-1"} <= ids

    @pytest.mark.parametrize(
        "excluded",
        [
            "mistral-embed",
            "codestral-embed-2505",
            "mistral-moderation-2603",
            "mistral-ocr-latest",
            "voxtral-mini-transcribe",
            "voxtral-mini-tts",
            "ft:mistral-small:old",
        ],
    )
    def test_non_chat_and_archived_models_are_excluded(
        self, monkeypatch: pytest.MonkeyPatch, excluded: str
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        assert f"mistral:{excluded}" not in {m.id for m in discover_mistral_models()}

    def test_deprecated_but_listed_model_is_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        assert "mistral:ministral-8b-2410" in {m.id for m in discover_mistral_models()}

    def test_aliases_are_never_collapsed_and_duplicates_never_repeat(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        ids = [m.id for m in discover_mistral_models()]
        assert len(ids) == len(set(ids))
        assert {
            "mistral:mistral-medium-latest",
            "mistral:mistral-medium-2604",
            "mistral:mistral-medium-3-5",
            "mistral:mistral-medium-3.5",
        } <= set(ids)

    def test_chat_flag_must_be_literally_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        cards = [
            _card("a-true", caps={"completion_chat": True}),
            _card("b-string", caps={"completion_chat": "true"}),
            _card("c-one", caps={"completion_chat": 1}),
            _card("d-false", caps={"completion_chat": False}),
            {"id": "e-no-capabilities"},
            {"id": "f-bad-capabilities", "capabilities": ["completion_chat"]},
        ]
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": cards})})

        assert [m.id for m in discover_mistral_models()] == ["mistral:a-true"]

    def test_malformed_entries_are_skipped_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        cards: list[Any] = [
            "not-a-dict",
            None,
            {"capabilities": {"completion_chat": True}},
            {"id": 7, "capabilities": {"completion_chat": True}},
            {"id": "", "capabilities": {"completion_chat": True}},
            _card("ok", caps={"completion_chat": True}),
        ]
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": cards})})

        assert [m.id for m in discover_mistral_models()] == ["mistral:ok"]

    def test_bare_array_payload_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The API reference shows both a {"data": [...]} wrapper and a bare array.
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp(_LISTING)})

        assert [m.id for m in discover_mistral_models()] == _EXPECTED_IDS

    def test_published_prices_are_none_never_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        assert all(
            (m.price_in, m.price_out, m.price_request) == (None, None, None)
            for m in discover_mistral_models()
        )


class TestCapabilities:
    """Chat cards' flags become probe tags in the KNOWN_MODEL_CAPABILITIES
    vocabulary."""

    @staticmethod
    def _by_id(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[str, ...]]:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})
        return {m.id: m.capabilities for m in discover_mistral_models()}

    def test_flags_map_to_tags_in_a_stable_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        caps = self._by_id(monkeypatch)

        assert caps["mistral:mistral-small-latest"] == ("tools",)
        assert caps["mistral:mistral-medium-latest"] == ("tools", "vision")
        assert caps["mistral:labs-leanstral-1-5"] == ("tools", "vision", "reasoning")
        assert caps["mistral:voxtral-small-latest"] == ("tools", "audio")

    def test_a_chat_model_with_no_mapped_flag_has_no_tags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._by_id(monkeypatch)["mistral:ministral-8b-2410"] == ()

    def test_flags_without_a_tag_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        card = _card(
            "m",
            caps={
                "completion_chat": True,
                "completion_fim": True,
                "fine_tuning": True,
                "classification": True,
                "unified_resources": True,
            },
        )
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": [card]})})

        assert [m.capabilities for m in discover_mistral_models()] == [()]

    def test_only_a_literal_true_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        card = _card(
            "m",
            caps={
                "completion_chat": True,
                "function_calling": "true",
                "vision": 1,
                "reasoning": False,
                "audio": None,
            },
        )
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": [card]})})

        assert [m.capabilities for m in discover_mistral_models()] == [()]

    def test_every_tag_is_one_the_ui_offers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_v2.ui_settings import KNOWN_MODEL_CAPABILITIES

        emitted = {tag for tags in self._by_id(monkeypatch).values() for tag in tags}
        assert emitted == {"tools", "vision", "reasoning", "audio"}
        assert emitted <= set(KNOWN_MODEL_CAPABILITIES)

    def test_other_providers_publish_no_capabilities(self) -> None:
        assert CloudModelInfo(id="openai:gpt-x").capabilities == ()


class TestKeyedAndHeaderAuth:
    def test_no_key_makes_no_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        assert discover_mistral_models() == []
        assert calls == []

    def test_empty_key_makes_no_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "")
        calls = _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        assert discover_mistral_models() == []
        assert calls == []

    def test_key_travels_only_as_a_bearer_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "sentinel-key-123")
        calls = _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        discover_mistral_models()

        ((url, headers, params),) = calls
        assert url == _MODELS_URL
        assert headers == {"Authorization": "Bearer sentinel-key-123"}
        assert params == {}
        assert "sentinel-key-123" not in url


class TestFailureIsEmpty:
    @pytest.mark.parametrize(
        "response",
        [
            pytest.param(_Resp(None, status=500), id="http-500"),
            pytest.param(_Resp(None, status=401), id="rejected-key"),
            pytest.param(_Resp(None), id="null-body"),
            pytest.param(_Resp("oops"), id="string-body"),
            pytest.param(_Resp({"data": "oops"}), id="data-not-a-list"),
            pytest.param(_Resp({"data": []}), id="empty-listing"),
            pytest.param(_Resp({"message": "unauthorized"}), id="error-object"),
        ],
    )
    def test_bad_response_yields_no_models(
        self, monkeypatch: pytest.MonkeyPatch, response: _Resp
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: response})

        assert discover_mistral_models() == []

    def test_transport_failure_yields_no_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {})  # every GET raises ConnectError

        assert discover_mistral_models() == []


class TestBaseUrl:
    def test_default_and_normalisation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert resolve_mistral_base_url() == _DEFAULT_BASE
        monkeypatch.setenv("MISTRAL_BASE_URL", "http://gateway.local:8080/v1/")
        assert resolve_mistral_base_url() == "http://gateway.local:8080/v1"
        monkeypatch.setenv("MISTRAL_BASE_URL", "http://gateway.local:8080")
        assert resolve_mistral_base_url() == "http://gateway.local:8080/v1"

    def test_override_is_the_probed_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("MISTRAL_BASE_URL", "http://gateway.local:8080")
        url = "http://gateway.local:8080/v1/models"
        calls = _route(monkeypatch, {url: _Resp({"data": _LISTING})})

        assert [m.id for m in discover_mistral_models()] == _EXPECTED_IDS
        assert calls[0][0] == url

    @pytest.mark.parametrize(
        "base",
        [
            "https://api.mistral.ai/v1/",
            "https://API.mistral.ai/v1",
            "https://api.mistral.ai:443/v1",
            "https://api.mistral.ai",
        ],
    )
    def test_equivalent_spellings_are_the_documented_origin(
        self, monkeypatch: pytest.MonkeyPatch, base: str
    ) -> None:
        monkeypatch.setenv("MISTRAL_BASE_URL", base)
        assert mistral_base_is_documented() is True

    @pytest.mark.parametrize(
        "base",
        [
            "http://gateway.local:8080",
            "http://api.mistral.ai/v1",
            "https://api.mistral.ai:8443/v1",
            "https://api.mistral.ai.evil.example/v1",
        ],
    )
    def test_any_other_origin_is_not_documented(
        self, monkeypatch: pytest.MonkeyPatch, base: str
    ) -> None:
        monkeypatch.setenv("MISTRAL_BASE_URL", base)
        assert mistral_base_is_documented() is False

    def test_default_base_is_documented(self) -> None:
        assert mistral_base_is_documented() is True


class TestAggregate:
    def test_keyed_mistral_joins_the_cloud_sweep(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        ids = [m.id for m in discover_cloud_models()]
        assert [i for i in ids if i.startswith("mistral:")] == _EXPECTED_IDS

    def test_unkeyed_mistral_is_not_probed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        discover_cloud_models()

        assert _MODELS_URL not in {url for url, _, _ in calls}


class TestBuilder:
    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        langchain_mistralai = pytest.importorskip("langchain_mistralai")
        captured: dict[str, Any] = {}

        class _StubChatMistralAI:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        monkeypatch.setattr(langchain_mistralai, "ChatMistralAI", _StubChatMistralAI)
        return captured

    def test_wires_model_key_endpoint_and_temperature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", _TEST_KEY)

        build_mistral_model("mistral-medium-latest", 0.3)

        assert captured["model"] == "mistral-medium-latest"
        assert captured["api_key"] == _TEST_KEY
        assert captured["base_url"] == _DEFAULT_BASE
        assert captured["temperature"] == 0.3
        assert set(captured) == {"model", "api_key", "base_url", "temperature"}

    def test_dispatch_strips_the_prefix_and_keeps_a_labs_id_verbatim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

        model = _build_model_by_prefix("mistral:labs-leanstral-1-5", 0.0)

        assert model is not None
        assert captured["model"] == "labs-leanstral-1-5"

    def test_get_chat_model_routes_mistral_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture(monkeypatch)
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

        get_chat_model("mistral:mistral-small-latest", 0.1)

        assert captured["model"] == "mistral-small-latest"
        assert captured["temperature"] == 0.1

    def test_base_url_override_is_passed_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("MISTRAL_BASE_URL", "http://gateway.local:8080")

        build_mistral_model("mistral-small-latest", 0.0)

        assert captured["base_url"] == "http://gateway.local:8080/v1"

    def test_missing_key_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._capture(monkeypatch)

        with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
            build_mistral_model("mistral-small-latest", 0.0)

    def test_empty_key_is_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._capture(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", "")

        with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
            build_mistral_model("mistral-small-latest", 0.0)

    def test_missing_package_raises_import_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setitem(sys.modules, "langchain_mistralai", None)

        with pytest.raises(ImportError, match="langchain-mistralai"):
            build_mistral_model("mistral-small-latest", 0.0)

    def test_builds_a_real_chat_mistralai_without_touching_the_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        langchain_mistralai = pytest.importorskip("langchain_mistralai")
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

        def _no_network(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("building the model must not make a request")

        monkeypatch.setattr(httpx.Client, "send", _no_network)
        monkeypatch.setattr(httpx.AsyncClient, "send", _no_network)

        model = build_mistral_model("labs-leanstral-1-5", 0.3)

        assert isinstance(model, langchain_mistralai.ChatMistralAI)
        assert model.model == "labs-leanstral-1-5"
        assert model.mistral_api_key is not None
        assert model.mistral_api_key.get_secret_value() == "test-key"
        assert model.endpoint == _DEFAULT_BASE
        assert model.temperature == 0.3
        assert "test-key" not in repr(model)


class TestProbeRows:
    """enumerate_known_models surfaces keyed Mistral models with a price label."""

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        monkeypatch.setattr(
            "agentic_v2.langchain.models.discover_lmstudio_models", lambda: []
        )
        monkeypatch.setattr(
            "agentic_v2.langchain.models.discover_onnx_models", lambda: []
        )
        monkeypatch.setattr(
            "agentic_v2.langchain.models.discover_ollama_models", lambda: []
        )
        monkeypatch.setattr(
            "agentic_v2.models.price_annotation.is_served_locally", lambda name: False
        )

    @staticmethod
    def _mistral_rows() -> dict[str, dict[str, Any]]:
        return {
            m["id"]: m for m in enumerate_known_models() if m["provider"] == "mistral"
        }

    def test_keyed_models_are_listed_tier_0_and_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        rows = self._mistral_rows()

        assert list(rows) == sorted(_EXPECTED_IDS)
        assert all(row["tier"] == 0 for row in rows.values())
        assert all(row["available"] is True for row in rows.values())

    def test_without_the_key_no_mistral_rows_appear(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        assert self._mistral_rows() == {}

    def test_no_llm_mode_makes_no_listing_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTIC_NO_LLM", "1")
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        calls = _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        assert self._mistral_rows() == {}
        assert calls == []

    def test_label_is_unknown_free_tier_not_confirmed_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        rows = self._mistral_rows()

        assert rows
        assert {(row["price_label"], row["price_reason"]) for row in rows.values()} == {
            ("unknown", "free tier not confirmed")
        }

    def test_declared_free_tier_labels_every_mistral_model_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("MISTRAL_FREE_TIER", "true")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        rows = self._mistral_rows()

        assert rows
        assert {(row["price_label"], row["price_reason"]) for row in rows.values()} == {
            ("free", "free tier declared for mistral")
        }

    def test_rows_carry_the_listings_capabilities(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        _route(monkeypatch, {_MODELS_URL: _Resp({"data": _LISTING})})

        rows = self._mistral_rows()

        assert rows["mistral:labs-leanstral-1-5"]["capabilities"] == [
            "tools",
            "vision",
            "reasoning",
        ]
        assert rows["mistral:voxtral-small-latest"]["capabilities"] == [
            "tools",
            "audio",
        ]
        # A chat model with no mapped flag has no key rather than an empty list.
        assert "capabilities" not in rows["mistral:ministral-8b-2410"]

    def test_rows_of_providers_without_capabilities_stay_unchanged(self) -> None:
        listing = [CloudModelInfo(id="openai:gpt-4o-2099-mega")]
        by_id = {m["id"]: m for m in enumerate_known_models(cloud_listing=listing)}

        assert "capabilities" not in by_id["openai:gpt-4o-2099-mega"]

    def test_declaration_does_not_relabel_other_providers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_FREE_TIER", "1")
        listing = [CloudModelInfo(id="openai:gpt-4o-2099-mega")]

        by_id = {m["id"]: m for m in enumerate_known_models(cloud_listing=listing)}

        assert by_id["openai:gpt-4o-2099-mega"]["price_label"] == "unknown"
