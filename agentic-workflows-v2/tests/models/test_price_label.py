"""Rule table for the pure price-label decision (ported from af-probes).

Every branch of :func:`rate_prices` and :func:`label_price`, with the core
principle pinned down: a missing price is never read as 0.
"""

from __future__ import annotations

import dataclasses
import math
from typing import get_args

import pytest

from agentic_v2.models.price_label import (
    SOURCE_DECLARATIONS,
    PriceFacts,
    PriceLabel,
    Prices,
    label_price,
    rate_prices,
)

_NAN = math.nan
_INF = math.inf

# The reason strings the probe route promises (the proper noun keeps its case).
_DOCUMENTED_REASONS = {
    "runs on this machine",
    "both prices are 0",
    "price above 0",
    "per-request price above 0",
    "free tier declared for nvidia",
    "free tier not confirmed",
    "cloud model via Ollama",
    "free tier declared for nvidia (via OPENAI_BASE_URL)",
    "price not published",
    "address differs from the documented one",
    "price is negative or not a number",
    "curated free endpoint",
}


class TestRatePrices:
    """af-probes' price rule applied to one set of published prices."""

    @pytest.mark.parametrize(
        ("prices", "expected"),
        [
            pytest.param(
                Prices(0.0, 0.0), ("free", "both prices are 0"), id="both-zero"
            ),
            pytest.param(
                Prices(0.0, 0.0, 0.0), ("free", "both prices are 0"), id="zero-fee"
            ),
            pytest.param(
                Prices(0.0, 0.0, None), ("free", "both prices are 0"), id="no-fee"
            ),
            pytest.param(
                Prices(0.0, 0.0, 0.01),
                ("paid", "per-request price above 0"),
                id="request-fee-makes-free-tokens-paid",
            ),
            pytest.param(Prices(0.2, 0.0), ("paid", "price above 0"), id="input-only"),
            pytest.param(Prices(0.0, 0.6), ("paid", "price above 0"), id="output-only"),
            pytest.param(Prices(0.2, 0.6), ("paid", "price above 0"), id="both-above"),
            pytest.param(
                Prices(0.2, None), ("paid", "price above 0"), id="paid-despite-gap"
            ),
            pytest.param(
                Prices(None, None), ("unknown", "price not published"), id="nothing"
            ),
            pytest.param(
                Prices(0.0, None),
                ("unknown", "price not published"),
                id="zero-and-missing-is-not-free",
            ),
            pytest.param(
                Prices(None, 0.0),
                ("unknown", "price not published"),
                id="missing-and-zero-is-not-free",
            ),
            pytest.param(
                Prices(None, None, 0.01),
                ("unknown", "price not published"),
                id="fee-alone-is-not-a-token-price",
            ),
        ],
    )
    def test_rule_table(self, prices: Prices, expected: tuple[PriceLabel, str]) -> None:
        assert rate_prices(prices) == expected

    @pytest.mark.parametrize(
        "prices",
        [
            pytest.param(Prices(-1.0, 0.0), id="negative-in"),
            pytest.param(Prices(0.0, -1.0), id="negative-out"),
            pytest.param(Prices(0.0, 0.0, -0.5), id="negative-fee"),
            pytest.param(Prices(_NAN, 0.0), id="nan-in"),
            pytest.param(Prices(0.0, _NAN), id="nan-out"),
            pytest.param(Prices(0.0, 0.0, _NAN), id="nan-fee-must-not-read-as-no-fee"),
            pytest.param(Prices(_INF, 0.0), id="inf-in"),
            pytest.param(Prices(0.0, -_INF), id="neg-inf-out"),
            pytest.param(Prices(0.2, -1.0), id="bad-beats-paid"),
        ],
    )
    def test_negative_or_non_finite_is_unknown(self, prices: Prices) -> None:
        assert rate_prices(prices) == ("unknown", "price is negative or not a number")


class TestPlacement:
    """Where the call goes settles the label before any price is consulted."""

    def test_this_machine_is_local(self) -> None:
        facts = PriceFacts(provider="ollama", placement="this_machine")
        assert label_price(facts) == ("local", "runs on this machine")

    def test_this_machine_ignores_a_stray_price(self) -> None:
        facts = PriceFacts(
            provider="ollama", placement="this_machine", live=Prices(5.0, 5.0)
        )
        assert label_price(facts) == ("local", "runs on this machine")

    def test_ollama_cloud_is_unknown_even_with_a_free_price(self) -> None:
        facts = PriceFacts(
            provider="ollama", placement="ollama_cloud", curated=Prices(0.0, 0.0)
        )
        assert label_price(facts) == ("unknown", "cloud model via Ollama")

    def test_unverified_address_is_unknown_even_with_a_free_price(self) -> None:
        facts = PriceFacts(
            provider="openrouter",
            placement="unverified_address",
            live=Prices(0.0, 0.0),
            curated_lane="free",
        )
        assert label_price(facts) == (
            "unknown",
            "address differs from the documented one",
        )

    def test_unverified_address_beats_a_source_declaration(self) -> None:
        facts = PriceFacts(provider="nvidia", placement="unverified_address")
        assert label_price(facts)[0] == "unknown"


class TestNvidiaViaOpenai:
    """``openai:`` pointed at NVIDIA's documented origin is NVIDIA's free tier."""

    def test_is_nvidias_declared_free_tier(self) -> None:
        facts = PriceFacts(provider="openai", placement="nvidia_via_openai")
        assert label_price(facts) == (
            "free",
            "free tier declared for nvidia (via OPENAI_BASE_URL)",
        )

    def test_beats_a_price_recorded_for_real_openai(self) -> None:
        facts = PriceFacts(
            provider="openai",
            placement="nvidia_via_openai",
            live=Prices(2.5, 10.0),
            curated=Prices(2.5, 10.0),
            curated_lane="paid",
        )
        assert label_price(facts)[0] == "free"

    def test_plain_openai_is_still_unknown(self) -> None:
        assert label_price(PriceFacts(provider="openai")) == (
            "unknown",
            "price not published",
        )


class TestPriceSources:
    """A live published price, then the curated one, then lane and declaration."""

    def test_live_free(self) -> None:
        facts = PriceFacts(provider="openrouter", live=Prices(0.0, 0.0, 0.0))
        assert label_price(facts) == ("free", "both prices are 0")

    def test_live_paid(self) -> None:
        facts = PriceFacts(provider="openrouter", live=Prices(3.0, 15.0))
        assert label_price(facts) == ("paid", "price above 0")

    def test_live_request_fee(self) -> None:
        facts = PriceFacts(provider="openrouter", live=Prices(0.0, 0.0, 0.02))
        assert label_price(facts) == ("paid", "per-request price above 0")

    def test_live_beats_curated(self) -> None:
        facts = PriceFacts(
            provider="openrouter",
            live=Prices(2.0, 8.0),
            curated=Prices(0.0, 0.0),
            curated_lane="free",
        )
        assert label_price(facts) == ("paid", "price above 0")

    def test_unpublished_live_price_falls_through_to_curated(self) -> None:
        facts = PriceFacts(
            provider="openrouter", live=Prices(None, None), curated=Prices(0.0, 0.0)
        )
        assert label_price(facts) == ("free", "both prices are 0")

    def test_bad_live_price_does_not_fall_through_to_curated(self) -> None:
        facts = PriceFacts(
            provider="openrouter", live=Prices(-1.0, -1.0), curated=Prices(0.0, 0.0)
        )
        assert label_price(facts) == ("unknown", "price is negative or not a number")

    def test_curated_paid(self) -> None:
        facts = PriceFacts(provider="ollama", curated=Prices(0.22, 0.66))
        assert label_price(facts) == ("paid", "price above 0")

    def test_curated_free_prices(self) -> None:
        facts = PriceFacts(provider="nvidia", curated=Prices(0.0, 0.0))
        assert label_price(facts) == ("free", "both prices are 0")

    def test_curated_price_beats_source_declaration(self) -> None:
        facts = PriceFacts(provider="nvidia", curated=Prices(1.0, 2.0))
        assert label_price(facts) == ("paid", "price above 0")

    def test_curated_free_lane_without_prices(self) -> None:
        facts = PriceFacts(provider="openrouter", curated_lane="free")
        assert label_price(facts) == ("free", "curated free endpoint")

    def test_curated_local_lane_without_prices(self) -> None:
        facts = PriceFacts(provider="lemonade", curated_lane="local")
        assert label_price(facts) == ("local", "runs on this machine")

    def test_curated_paid_lane_is_a_routing_default_not_a_price(self) -> None:
        facts = PriceFacts(provider="anthropic", curated_lane="paid")
        assert label_price(facts) == ("unknown", "price not published")

    def test_curated_price_beats_curated_lane(self) -> None:
        facts = PriceFacts(
            provider="openrouter", curated=Prices(1.0, 1.0), curated_lane="free"
        )
        assert label_price(facts) == ("paid", "price above 0")

    def test_nvidia_declared_free_tier(self) -> None:
        facts = PriceFacts(provider="nvidia")
        assert label_price(facts) == ("free", "free tier declared for nvidia")

    def test_gemini_free_tier_is_not_confirmed(self) -> None:
        facts = PriceFacts(provider="gemini")
        assert label_price(facts) == ("unknown", "free tier not confirmed")

    def test_gemini_curated_paid_lane_stays_unconfirmed(self) -> None:
        facts = PriceFacts(provider="gemini", curated_lane="paid")
        assert label_price(facts) == ("unknown", "free tier not confirmed")

    def test_default_is_unknown_not_published(self) -> None:
        assert label_price(PriceFacts(provider="openai")) == (
            "unknown",
            "price not published",
        )


class TestMissingPriceIsNeverFree:
    """The core principle, checked across every provider and every gap."""

    _GAPS = [
        pytest.param(None, None, id="no-prices"),
        pytest.param(Prices(None, None), None, id="empty-live"),
        pytest.param(Prices(0.0, None), None, id="live-half-zero"),
        pytest.param(None, Prices(None, 0.0), id="curated-half-zero"),
        pytest.param(Prices(None, None, 0.0), Prices(None, None), id="fee-only"),
    ]

    @pytest.mark.parametrize(("live", "curated"), _GAPS)
    @pytest.mark.parametrize(
        "provider",
        ["openai", "anthropic", "gh", "openrouter", "digitalocean", "azure", "gemini"],
    )
    def test_gap_never_yields_free(
        self, provider: str, live: Prices | None, curated: Prices | None
    ) -> None:
        label, _ = label_price(
            PriceFacts(provider=provider, live=live, curated=curated)
        )
        assert label == "unknown"

    def test_only_a_declared_source_can_be_free_without_a_price(self) -> None:
        free_sources = {
            provider
            for provider, (label, _) in SOURCE_DECLARATIONS.items()
            if label == "free"
        }
        assert free_sources == {"nvidia"}


class TestShape:
    def test_every_verdict_uses_the_documented_vocabulary(self) -> None:
        vocabulary = set(get_args(PriceLabel))
        assert vocabulary == {"local", "free", "paid", "unknown"}
        cases = [
            PriceFacts(provider="x"),
            PriceFacts(provider="x", placement="this_machine"),
            PriceFacts(provider="x", placement="ollama_cloud"),
            PriceFacts(provider="x", placement="unverified_address"),
            PriceFacts(provider="x", placement="nvidia_via_openai"),
            PriceFacts(provider="x", live=Prices(0.0, 0.0)),
            PriceFacts(provider="x", live=Prices(1.0, 1.0)),
            PriceFacts(provider="x", curated_lane="free"),
            PriceFacts(provider="nvidia"),
        ]
        for facts in cases:
            label, reason = label_price(facts)
            assert label in vocabulary
            assert reason in _DOCUMENTED_REASONS

    def test_facts_and_prices_are_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            Prices(0.0, 0.0).price_in = 1.0  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            PriceFacts(provider="x").provider = "y"  # type: ignore[misc]
