"""Free / paid / local / unknown price labels for model-probe rows.

Ported from the ``af-probes`` package (``af_probes.rules.label`` and the
``free = ...`` source declarations in its ``providers.toml``) -- ported, not
imported: ARP keeps no dependency on that package.

The one principle carried over: **a missing price is never read as 0.** A model
is ``"free"`` only when a price says so (both token prices exactly 0 and no
per-request fee) or a source declaration says so; absence of a price is
``"unknown"``. Likewise a price is believed only from the address it was
documented at, and an Ollama cloud model is never "local".

This module is pure: no environment, network or registry access. The caller
gathers :class:`PriceFacts` (see :mod:`agentic_v2.models.price_annotation`) and
:func:`label_price` returns ``(label, reason)``. Order of the decision:

1. ``placement`` -- runs on this machine -> ``local``; Ollama cloud -> unknown;
   an endpoint that is not the documented one -> unknown; ``openai:`` aliased
   to NVIDIA's documented origin -> NVIDIA's declared free tier (the prices
   curated for real OpenAI do not apply there, so they never outrank it) --
   unless the entry is explicitly curated ``paid`` and no price speaks, see 4.
2. A live published price (``facts.live``), then the curated registry price
   (``facts.curated``), both through :func:`rate_prices`.
3. An explicit curated ``cost_lane`` of ``free`` / ``local``.
4. An explicit curated ``paid`` lane beats every provider-wide declaration that
   would say ``free`` -- NVIDIA's, the ``openai:``-to-NVIDIA alias's (when no
   price speaks), and the operator's opt-in -- with "curated as paid". A
   registry entry deliberately marked paid is a decision about that model; the
   provider-wide declaration is only a default. (A declaration that says
   ``unknown``, Gemini's, is left alone: a paid lane is a routing default, not a
   price, and cannot confirm the free tier is off.)
5. A per-source declaration (:data:`SOURCE_DECLARATIONS`), or -- for a provider in
   :data:`OPT_IN_FREE_TIER_PROVIDERS` -- the operator's own free-tier declaration
   (``PriceFacts.free_tier_declared``, read from the environment by the caller).
6. Otherwise unknown, "price not published".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

PriceLabel = Literal["local", "free", "paid", "unknown"]
CuratedLane = Literal["local", "free", "paid"]

# Where a model's calls go. "unverified_address" covers both an on-machine
# provider pointed at a non-loopback host and a hosted provider whose base URL
# is not the documented one -- in either case no price or locality claim holds.
# "nvidia_via_openai" is the ``openai:`` provider pointed at NVIDIA's documented
# origin: those models are NVIDIA's, whatever the id says.
Placement = Literal[
    "this_machine", "ollama_cloud", "unverified_address", "nvidia_via_openai", "hosted"
]

REASON_LOCAL = "runs on this machine"
REASON_OLLAMA_CLOUD = "cloud model via Ollama"
REASON_ADDRESS = "address differs from the documented one"
REASON_BOTH_ZERO = "both prices are 0"
REASON_PRICE_ABOVE_ZERO = "price above 0"
REASON_REQUEST_FEE = "per-request price above 0"
REASON_BAD_PRICE = "price is negative or not a number"
REASON_NOT_PUBLISHED = "price not published"
REASON_CURATED_FREE = "curated free endpoint"
REASON_CURATED_PAID = "curated as paid"
REASON_NVIDIA_FREE_TIER = "free tier declared for nvidia"
REASON_FREE_TIER_UNCONFIRMED = "free tier not confirmed"
REASON_GEMINI_UNCONFIRMED = REASON_FREE_TIER_UNCONFIRMED
REASON_NVIDIA_VIA_OPENAI = "free tier declared for nvidia (via OPENAI_BASE_URL)"

# Whole-source declarations (providers.toml ``free = "tier"`` / ``"unconfirmed"``).
# NVIDIA's hosted API is a declared free tier. Gemini's free tier applies only
# while billing is off for the key's project, which cannot be seen from here,
# so it stays unknown rather than free.
SOURCE_DECLARATIONS: dict[str, tuple[PriceLabel, str]] = {
    "nvidia": ("free", REASON_NVIDIA_FREE_TIER),
    "gemini": ("unknown", REASON_GEMINI_UNCONFIRMED),
    "mistral": ("unknown", REASON_FREE_TIER_UNCONFIRMED),
}

# Providers whose free tier is a property of the *account*, which no API
# listing can reveal. Unknown by default (the entry in SOURCE_DECLARATIONS); the
# operator can declare the tier (``PriceFacts.free_tier_declared``), which turns
# the label to free with a reason saying whose declaration it is.
OPT_IN_FREE_TIER_PROVIDERS: frozenset[str] = frozenset({"mistral"})


@dataclass(frozen=True)
class Prices:
    """What a source published for one model; ``None`` means not published.

    Token prices share one unit (the caller's choice -- USD per million tokens
    for both the curated registry and OpenRouter's catalog); only their sign and
    zero-ness matter to the rule. ``price_request`` is a flat per-call fee.
    """

    price_in: float | None = None
    price_out: float | None = None
    price_request: float | None = None


@dataclass(frozen=True)
class PriceFacts:
    """Everything the rule needs about one model, gathered by the caller."""

    provider: str
    placement: Placement = "hosted"
    live: Prices | None = None
    curated: Prices | None = None
    curated_lane: CuratedLane | None = None
    free_tier_declared: bool = False


def rate_prices(prices: Prices) -> tuple[PriceLabel, str]:
    """Label a set of published prices (af-probes' price rule, verbatim).

    Any negative or non-finite price -> unknown. Any token price above 0
    -> paid. Both token prices exactly 0 -> paid if a per-request fee is
    above 0, otherwise free. Anything else (a token price missing) ->
    unknown.
    """
    tokens = (prices.price_in, prices.price_out)
    if any(
        p is not None and (p < 0 or not math.isfinite(p))
        for p in (*tokens, prices.price_request)
    ):
        return "unknown", REASON_BAD_PRICE
    if any(p is not None and p > 0 for p in tokens):
        return "paid", REASON_PRICE_ABOVE_ZERO
    if all(p == 0 for p in tokens):
        if prices.price_request:
            return "paid", REASON_REQUEST_FEE
        return "free", REASON_BOTH_ZERO
    return "unknown", REASON_NOT_PUBLISHED


def _priced_verdict(prices: Prices | None) -> tuple[PriceLabel, str] | None:
    """``rate_prices`` unless it found nothing to go on (so the next source can
    speak)."""
    if prices is None:
        return None
    verdict = rate_prices(prices)
    return None if verdict == ("unknown", REASON_NOT_PUBLISHED) else verdict


def _price_speaks(facts: PriceFacts) -> bool:
    """Whether a live or curated price gives a verdict for this model."""
    return any(
        _priced_verdict(prices) is not None for prices in (facts.live, facts.curated)
    )


def _provider_declaration(facts: PriceFacts) -> tuple[PriceLabel, str] | None:
    """The provider-wide declaration that applies to this model, if any."""
    if facts.free_tier_declared and facts.provider in OPT_IN_FREE_TIER_PROVIDERS:
        return "free", f"free tier declared for {facts.provider}"
    return SOURCE_DECLARATIONS.get(facts.provider)


def _nvidia_alias_verdict(facts: PriceFacts) -> tuple[PriceLabel, str]:
    """``openai:`` aimed at NVIDIA: its free tier, unless curated explicitly paid.

    The prices curated for real OpenAI never outrank the alias, but an explicit
    ``paid`` lane with no price to speak still does.
    """
    if facts.curated_lane == "paid" and not _price_speaks(facts):
        return "paid", REASON_CURATED_PAID
    return SOURCE_DECLARATIONS["nvidia"][0], REASON_NVIDIA_VIA_OPENAI


def label_price(facts: PriceFacts) -> tuple[PriceLabel, str]:
    """Return ``(label, reason)`` for one model; a missing price is never 0."""
    if facts.placement == "this_machine":
        return "local", REASON_LOCAL
    if facts.placement == "ollama_cloud":
        return "unknown", REASON_OLLAMA_CLOUD
    if facts.placement == "unverified_address":
        return "unknown", REASON_ADDRESS
    if facts.placement == "nvidia_via_openai":
        return _nvidia_alias_verdict(facts)
    for prices in (facts.live, facts.curated):
        verdict = _priced_verdict(prices)
        if verdict is not None:
            return verdict
    if facts.curated_lane == "free":
        return "free", REASON_CURATED_FREE
    if facts.curated_lane == "local":
        return "local", REASON_LOCAL
    declared = _provider_declaration(facts)
    if declared is None:
        return "unknown", REASON_NOT_PUBLISHED
    if declared[0] == "free" and facts.curated_lane == "paid":
        return "paid", REASON_CURATED_PAID
    return declared


__all__ = [
    "OPT_IN_FREE_TIER_PROVIDERS",
    "SOURCE_DECLARATIONS",
    "CuratedLane",
    "Placement",
    "PriceFacts",
    "PriceLabel",
    "Prices",
    "label_price",
    "rate_prices",
]
