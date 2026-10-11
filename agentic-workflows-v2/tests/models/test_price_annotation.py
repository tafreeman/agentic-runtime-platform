"""Tests for annotating probe rows with ``price_label`` / ``price_reason``.

The pure rule table lives in ``test_price_label.py``; here the environment,
registry and live-listing facts that feed it are exercised with every lookup
stubbed -- no network, no real Ollama / LM Studio.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agentic_v2.models import price_annotation
from agentic_v2.models.cloud_discovery import CloudModelInfo
from agentic_v2.models.model_registry import RegisteredModel, load_registry
from agentic_v2.models.price_annotation import annotate_price_labels

_ENV_VARS = (
    "OLLAMA_BASE_URL",
    "OLLAMA_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "LMSTUDIO_HOST",
    "OPENROUTER_BASE_URL",
    "NVIDIA_BASE_URL",
    "MISTRAL_BASE_URL",
    "MISTRAL_FREE_TIER",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Nothing in this module may reach a daemon: with a key set, an
    # undiscovered Ollama id is checked against the local tag list.
    monkeypatch.setattr(price_annotation, "is_served_locally", lambda name: False)


def _row(model_id: str, **extra: Any) -> dict[str, Any]:
    provider = model_id.split(":")[0]
    return {
        "id": model_id,
        "provider": provider,
        "tier": 0,
        "available": True,
        **extra,
    }


def _verdict(
    model: dict[str, Any],
    listing: list[CloudModelInfo] | None = None,
    local_names: frozenset[str] | None = None,
) -> tuple[str, str]:
    (annotated,) = annotate_price_labels(
        [model], listing or [], local_ollama_names=local_names
    )
    return annotated["price_label"], annotated["price_reason"]


def _use_registry(monkeypatch: pytest.MonkeyPatch, *entries: RegisteredModel) -> None:
    by_id = {entry.id: entry for entry in entries}
    monkeypatch.setattr(
        price_annotation, "load_registry", lambda: SimpleNamespace(by_id=lambda: by_id)
    )


class TestShapeAndPurity:
    def test_adds_exactly_two_fields_and_keeps_the_rest(self) -> None:
        source = _row("openai:gpt-x", running=True)
        (annotated,) = annotate_price_labels([source])

        assert annotated == {
            **source,
            "price_label": "unknown",
            "price_reason": "price not published",
        }

    def test_does_not_mutate_its_input(self) -> None:
        source = _row("openai:gpt-x")
        annotate_price_labels([source])
        assert "price_label" not in source
        assert "price_reason" not in source

    def test_keeps_order_and_length(self) -> None:
        rows = [_row("openai:a"), _row("ollama:b"), _row("lmstudio:c")]
        assert [m["id"] for m in annotate_price_labels(rows)] == [
            "openai:a",
            "ollama:b",
            "lmstudio:c",
        ]

    def test_empty_input(self) -> None:
        assert annotate_price_labels([]) == []


class TestOllama:
    def test_pulled_model_on_loopback_is_local(self) -> None:
        assert _verdict(_row("ollama:qwen3:8b", cloud=False)) == (
            "local",
            "runs on this machine",
        )

    def test_cloud_flag_is_unknown(self) -> None:
        assert _verdict(_row("ollama:gpt-oss:120b-cloud", cloud=True)) == (
            "unknown",
            "cloud model via Ollama",
        )

    def test_non_loopback_base_makes_every_ollama_model_cloud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box.lan:11434")
        assert _verdict(_row("ollama:qwen3:8b", cloud=False)) == (
            "unknown",
            "cloud model via Ollama",
        )

    def test_loopback_base_by_ip_stays_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        assert _verdict(_row("ollama:qwen3:8b"))[0] == "local"

    @pytest.mark.parametrize("name", ["glm-5.3:cloud", "gpt-oss:120b-cloud"])
    def test_undiscovered_cloud_suffix_is_cloud(self, name: str) -> None:
        # No "cloud" key: a tier-chain / registry id discovery never saw.
        assert _verdict(_row(f"ollama:{name}")) == (
            "unknown",
            "cloud model via Ollama",
        )

    def test_undiscovered_local_id_is_local(self) -> None:
        assert _verdict(_row("ollama:qwen3-coder:30b"))[0] == "local"

    def test_api_key_reroutes_an_undiscovered_unpulled_model_to_cloud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
        assert _verdict(_row("ollama:qwen3-coder:30b")) == (
            "unknown",
            "cloud model via Ollama",
        )

    def test_api_key_leaves_a_pulled_model_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(price_annotation, "is_served_locally", lambda name: True)
        assert _verdict(_row("ollama:qwen3-coder:30b"))[0] == "local"

    def test_api_key_does_not_re_ask_the_daemon_about_a_discovered_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

        def _boom(name: str) -> bool:
            raise AssertionError("discovered models carry their own cloud flag")

        monkeypatch.setattr(price_annotation, "is_served_locally", _boom)
        assert _verdict(_row("ollama:qwen3:8b", cloud=False))[0] == "local"

    @pytest.fixture
    def _daemon_tripwire(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An API key is set and any daemon lookup fails the test."""
        monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

        def _boom(name: str) -> bool:
            raise AssertionError("the discovery pass already named what is local")

        monkeypatch.setattr(price_annotation, "is_served_locally", _boom)

    @pytest.mark.usefixtures("_daemon_tripwire")
    @pytest.mark.parametrize(
        ("listed", "model_id"),
        [
            ("qwen3-coder:30b", "ollama:qwen3-coder:30b"),
            # A bare request name matches its ``:latest`` alias, any case.
            ("llama3:latest", "ollama:llama3"),
            ("Gemma4:31B", "ollama:gemma4:31b"),
        ],
    )
    def test_supplied_local_names_decide_without_asking_the_daemon(
        self, listed: str, model_id: str
    ) -> None:
        assert _verdict(_row(model_id), local_names=frozenset({listed})) == (
            "local",
            "runs on this machine",
        )

    @pytest.mark.usefixtures("_daemon_tripwire")
    @pytest.mark.parametrize(
        "local_names",
        [
            # Discovery found nothing, or the daemon was unreachable: both mean
            # "nothing is local" and neither may trigger a second probe.
            frozenset(),
            frozenset({"some-other-model:7b"}),
        ],
    )
    def test_supplied_names_without_the_model_reroute_it_to_cloud(
        self, local_names: frozenset[str]
    ) -> None:
        assert _verdict(_row("ollama:qwen3-coder:30b"), local_names=local_names) == (
            "unknown",
            "cloud model via Ollama",
        )

    def test_curated_ollama_price_does_not_override_cloud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="ollama:glm-5.3:cloud",
                provider="ollama",
                cost_lane="paid",
                price_in=1.4,
                price_out=4.4,
            ),
        )
        assert _verdict(_row("ollama:glm-5.3:cloud", cloud=True)) == (
            "unknown",
            "cloud model via Ollama",
        )


class TestOtherLocalProviders:
    def test_lmstudio_default_host_is_local(self) -> None:
        assert _verdict(_row("lmstudio:gemma-3-12b-it")) == (
            "local",
            "runs on this machine",
        )

    @pytest.mark.parametrize(
        "host",
        [
            "http://localhost:1234",
            "http://127.0.0.1:1234/v1",
            "localhost:1234",
            "[::1]:1234",
        ],
    )
    def test_lmstudio_loopback_host_is_local(
        self, monkeypatch: pytest.MonkeyPatch, host: str
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", host)
        assert _verdict(_row("lmstudio:gemma-3-12b-it"))[0] == "local"

    @pytest.mark.parametrize("host", ["http://studio.lan:1234", "192.168.1.9:1234"])
    def test_lmstudio_remote_host_is_not_claimed_local(
        self, monkeypatch: pytest.MonkeyPatch, host: str
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", host)
        assert _verdict(_row("lmstudio:gemma-3-12b-it")) == (
            "unknown",
            "address differs from the documented one",
        )

    @pytest.mark.parametrize(
        "model_id", ["onnx:Microsoft/qwen3-14b-generic-cpu-2/v2", "local:phi"]
    )
    def test_onnx_is_local(self, model_id: str) -> None:
        assert _verdict(_row(model_id)) == ("local", "runs on this machine")


class TestOpenRouterLivePrices:
    _ID = "openrouter:vendor/model"

    def _live(self, **prices: float | None) -> list[CloudModelInfo]:
        return [CloudModelInfo(id=self._ID, **prices)]

    def test_both_prices_zero_is_free(self) -> None:
        live = self._live(price_in=0.0, price_out=0.0, price_request=0.0)
        assert _verdict(_row(self._ID), live) == ("free", "both prices are 0")

    def test_token_price_is_paid(self) -> None:
        live = self._live(price_in=3.0, price_out=15.0)
        assert _verdict(_row(self._ID), live) == ("paid", "price above 0")

    def test_request_fee_is_paid(self) -> None:
        live = self._live(price_in=0.0, price_out=0.0, price_request=0.01)
        assert _verdict(_row(self._ID), live) == ("paid", "per-request price above 0")

    def test_dynamic_price_marker_is_unknown(self) -> None:
        live = self._live(price_in=-1_000_000.0, price_out=-1_000_000.0)
        assert _verdict(_row(self._ID), live) == (
            "unknown",
            "price is negative or not a number",
        )

    def test_listing_without_prices_is_not_published(self) -> None:
        assert _verdict(_row(self._ID), self._live()) == (
            "unknown",
            "price not published",
        )

    def test_free_suffix_is_not_read_as_a_price(self) -> None:
        model_id = "openrouter:qwen/qwen3-14b:free"
        live = [CloudModelInfo(id=model_id)]
        assert _verdict(_row(model_id), live) == ("unknown", "price not published")

    def test_id_missing_from_listing_is_not_published(self) -> None:
        assert _verdict(_row(self._ID), [CloudModelInfo(id="openrouter:other")]) == (
            "unknown",
            "price not published",
        )

    def test_gateway_base_url_distrusts_the_published_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_BASE_URL", "http://gateway.local:8080")
        live = self._live(price_in=0.0, price_out=0.0)
        assert _verdict(_row(self._ID), live) == (
            "unknown",
            "address differs from the documented one",
        )

    def test_explicit_documented_base_url_is_still_trusted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/")
        live = self._live(price_in=0.0, price_out=0.0)
        assert _verdict(_row(self._ID), live)[0] == "free"

    def test_live_price_wins_over_curated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id=self._ID,
                provider="openrouter",
                cost_lane="free",
                price_in=0.0,
                price_out=0.0,
            ),
        )
        live = self._live(price_in=1.0, price_out=2.0)
        assert _verdict(_row(self._ID), live) == ("paid", "price above 0")


class TestCuratedRegistry:
    def test_curated_free_prices(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="openrouter:cohere/x:free",
                provider="openrouter",
                cost_lane="free",
                price_in=0.0,
                price_out=0.0,
            ),
        )
        assert _verdict(_row("openrouter:cohere/x:free")) == (
            "free",
            "both prices are 0",
        )

    def test_curated_paid_prices(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="openai:gpt-x", provider="openai", price_in=0.15, price_out=0.6
            ),
        )
        assert _verdict(_row("openai:gpt-x")) == ("paid", "price above 0")

    def test_one_curated_price_missing_is_unknown_not_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="openai:gpt-x", provider="openai", price_in=0.0, price_out=None
            ),
        )
        assert _verdict(_row("openai:gpt-x")) == ("unknown", "price not published")

    def test_curated_free_lane_without_prices(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(id="openai:gpt-x", provider="openai", cost_lane="free"),
        )
        assert _verdict(_row("openai:gpt-x")) == ("free", "curated free endpoint")

    def test_curated_paid_lane_without_prices_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(id="anthropic:c", provider="anthropic", cost_lane="paid"),
        )
        assert _verdict(_row("anthropic:c")) == ("unknown", "price not published")

    def test_uncurated_id_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_registry(monkeypatch)
        assert _verdict(_row("openai:gpt-new")) == ("unknown", "price not published")


class TestOpenaiAliasForNvidia:
    """On a machine where OPENAI_BASE_URL is NVIDIA's API, ``openai:`` is NVIDIA."""

    _VIA = "free tier declared for nvidia (via OPENAI_BASE_URL)"
    _NVIDIA = "https://integrate.api.nvidia.com/v1"

    def test_documented_nvidia_origin_is_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", self._NVIDIA)
        assert _verdict(_row("openai:meta/llama-3.1-8b-instruct")) == (
            "free",
            self._VIA,
        )

    @pytest.mark.parametrize(
        "base",
        [
            "https://integrate.api.nvidia.com/v1/",
            "https://integrate.api.nvidia.com",
            "https://INTEGRATE.api.nvidia.com:443/v1",
        ],
    )
    def test_equivalent_spellings_of_the_origin(
        self, monkeypatch: pytest.MonkeyPatch, base: str
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", base)
        assert _verdict(_row("openai:some/model"))[0] == "free"

    def test_openai_api_base_alias_variable_counts_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_BASE", self._NVIDIA)
        assert _verdict(_row("openai:some/model")) == ("free", self._VIA)

    def test_openai_base_url_wins_over_openai_api_base(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example/v1")
        monkeypatch.setenv("OPENAI_API_BASE", self._NVIDIA)
        assert _verdict(_row("openai:some/model"))[0] == "unknown"

    @pytest.mark.parametrize(
        "base",
        [
            "https://my-resource.openai.azure.com/openai",
            "http://localhost:4000",
            "https://proxy.example/v1",
            "http://integrate.api.nvidia.com/v1",
            "https://integrate.api.nvidia.com:8443/v1",
            "https://integrate.api.nvidia.com.evil.example/v1",
            "https://api.nvidia.com/v1",
            "not a url",
        ],
    )
    def test_any_other_base_url_stays_unknown(
        self, monkeypatch: pytest.MonkeyPatch, base: str
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", base)
        assert _verdict(_row("openai:some/model")) == (
            "unknown",
            "price not published",
        )

    def test_default_openai_stays_unknown(self) -> None:
        assert _verdict(_row("openai:gpt-4o-mini")) == (
            "unknown",
            "price not published",
        )

    def test_beats_a_price_curated_for_real_openai(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", self._NVIDIA)
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="openai:gpt-4o-mini",
                provider="openai",
                cost_lane="paid",
                price_in=0.15,
                price_out=0.6,
            ),
        )
        assert _verdict(_row("openai:gpt-4o-mini")) == ("free", self._VIA)

    def test_only_the_openai_provider_is_aliased(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", self._NVIDIA)
        assert _verdict(_row("anthropic:claude-x"))[0] == "unknown"
        assert _verdict(_row("gh:openai/gpt-4o"))[0] == "unknown"

    def test_on_prem_nim_setting_does_not_change_the_documented_origin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", self._NVIDIA)
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")
        assert _verdict(_row("openai:some/model"))[0] == "free"

    def test_the_base_url_never_appears_in_the_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Built from parts so no credential-shaped literal sits in the source.
        fake_credential = "hunter" + "2"
        base_with_credentials = (
            f"https://user:{fake_credential}@integrate.api.nvidia.com/v1"
        )
        monkeypatch.setenv("OPENAI_BASE_URL", base_with_credentials)
        (row,) = annotate_price_labels([_row("openai:some/model")])
        assert fake_credential not in repr(row)
        assert "nvidia.com" not in repr(row)


class TestSourceDeclarations:
    def test_nvidia_free_tier_is_declared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(monkeypatch)
        assert _verdict(_row("nvidia:meta/llama-3.1-8b-instruct")) == (
            "free",
            "free tier declared for nvidia",
        )

    def test_nvidia_curated_price_beats_the_declaration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="nvidia:big/model", provider="nvidia", price_in=1.0, price_out=2.0
            ),
        )
        assert _verdict(_row("nvidia:big/model")) == ("paid", "price above 0")

    def test_on_prem_nim_is_not_the_hosted_free_tier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")
        assert _verdict(_row("nvidia:meta/llama-3.1-8b-instruct")) == (
            "unknown",
            "address differs from the documented one",
        )

    def test_gemini_is_unconfirmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_registry(monkeypatch)
        assert _verdict(_row("gemini:gemini-2.5-flash")) == (
            "unknown",
            "free tier not confirmed",
        )


class TestMistralFreeTierSwitch:
    """``MISTRAL_FREE_TIER`` is an opt-in declaration, off by default."""

    _ID = "mistral:mistral-medium-latest"
    _LABS = "mistral:labs-leanstral-1-5"

    def test_unset_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_registry(monkeypatch)
        assert _verdict(_row(self._ID)) == ("unknown", "free tier not confirmed")

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", " True ", "yes", "on"])
    def test_truthy_declares_every_mistral_model_free(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        _use_registry(monkeypatch)
        monkeypatch.setenv("MISTRAL_FREE_TIER", value)
        for model_id in (self._ID, self._LABS):
            assert _verdict(_row(model_id)) == (
                "free",
                "free tier declared for mistral",
            )

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
    def test_anything_else_stays_unknown(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        _use_registry(monkeypatch)
        monkeypatch.setenv("MISTRAL_FREE_TIER", value)
        assert _verdict(_row(self._ID)) == ("unknown", "free tier not confirmed")

    def test_declaration_does_not_leak_to_other_providers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(monkeypatch)
        monkeypatch.setenv("MISTRAL_FREE_TIER", "1")
        assert _verdict(_row("openai:gpt-x")) == ("unknown", "price not published")
        assert _verdict(_row("gemini:gemini-2.5-flash")) == (
            "unknown",
            "free tier not confirmed",
        )

    def test_gateway_base_url_voids_the_declaration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(monkeypatch)
        monkeypatch.setenv("MISTRAL_FREE_TIER", "1")
        monkeypatch.setenv("MISTRAL_BASE_URL", "http://gateway.local:8080")
        assert _verdict(_row(self._ID)) == (
            "unknown",
            "address differs from the documented one",
        )

    def test_explicit_documented_base_url_keeps_the_declaration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(monkeypatch)
        monkeypatch.setenv("MISTRAL_FREE_TIER", "1")
        monkeypatch.setenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1/")
        assert _verdict(_row(self._ID))[0] == "free"

    def test_a_curated_price_beats_the_declaration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id=self._ID, provider="mistral", price_in=0.4, price_out=2.0
            ),
        )
        monkeypatch.setenv("MISTRAL_FREE_TIER", "1")
        assert _verdict(_row(self._ID)) == ("paid", "price above 0")


class TestCuratedPaidBeatsDeclarations:
    """Registry entries marked ``cost_lane: paid`` are not shown as free."""

    _PAID = ("paid", "curated as paid")

    def test_nvidia_entry_curated_paid_is_paid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="nvidia:meta/llama-3.1-8b-instruct",
                provider="nvidia",
                cost_lane="paid",
            ),
        )
        assert _verdict(_row("nvidia:meta/llama-3.1-8b-instruct")) == self._PAID

    def test_uncurated_nvidia_id_is_still_the_declared_free_tier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(monkeypatch)
        assert _verdict(_row("nvidia:meta/llama-3.1-8b-instruct")) == (
            "free",
            "free tier declared for nvidia",
        )

    def test_openai_alias_entry_curated_paid_is_paid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="openai:deepseek-ai/deepseek-v4-flash",
                provider="openai",
                cost_lane="paid",
            ),
        )
        assert _verdict(_row("openai:deepseek-ai/deepseek-v4-flash")) == self._PAID

    def test_openai_alias_entry_with_no_curation_is_still_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")
        _use_registry(monkeypatch)
        assert _verdict(_row("openai:some/model"))[0] == "free"

    def test_mistral_opt_in_entry_curated_paid_is_paid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_FREE_TIER", "1")
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="mistral:mistral-large-latest", provider="mistral", cost_lane="paid"
            ),
        )
        assert _verdict(_row("mistral:mistral-large-latest")) == self._PAID
        # A model the registry says nothing about keeps the operator's declaration.
        assert _verdict(_row("mistral:labs-leanstral-1-5"))[0] == "free"

    def test_curated_price_still_decides_before_the_paid_lane(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_registry(
            monkeypatch,
            RegisteredModel(
                id="nvidia:big/model",
                provider="nvidia",
                cost_lane="paid",
                price_in=1.0,
                price_out=2.0,
            ),
        )
        assert _verdict(_row("nvidia:big/model")) == ("paid", "price above 0")


class TestAgainstTheRealRegistry:
    """Invariants over the shipped model_registry.yaml, whatever it curates."""

    def test_a_missing_price_is_never_labelled_free(self) -> None:
        for entry in load_registry().models:
            if entry.price_in is not None or entry.price_out is not None:
                continue
            if entry.cost_lane in ("free", "local") or entry.provider in (
                "nvidia",
                "ollama",
            ):
                continue  # these are labelled by an explicit lane or declaration
            row = _row(entry.id, provider=entry.provider)
            assert _verdict(row)[0] != "free", entry.id

    def test_an_explicit_paid_lane_is_never_labelled_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MISTRAL_FREE_TIER", "1")
        paid = [e for e in load_registry().models if e.cost_lane == "paid"]
        assert paid
        for entry in paid:
            if entry.price_in is not None or entry.price_out is not None:
                continue
            row = _row(entry.id, provider=entry.provider)
            assert _verdict(row)[0] != "free", entry.id

    def test_curated_paid_nvidia_ids_in_the_shipped_registry_read_paid(self) -> None:
        nvidia_paid = [
            e
            for e in load_registry().models
            if e.provider == "nvidia"
            and e.cost_lane == "paid"
            and e.price_in is None
            and e.price_out is None
        ]
        assert nvidia_paid
        for entry in nvidia_paid:
            row = _row(entry.id, provider=entry.provider)
            assert _verdict(row) == ("paid", "curated as paid"), entry.id

    def test_every_registry_entry_gets_a_label(self) -> None:
        for entry in load_registry().models:
            label, reason = _verdict(_row(entry.id, provider=entry.provider))
            assert label in {"local", "free", "paid", "unknown"}, entry.id
            assert reason, entry.id
