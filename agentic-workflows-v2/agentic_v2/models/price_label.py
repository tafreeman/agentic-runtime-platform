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
   to NVIDIA's documented origin -> NVIDIA's declared free tier.
2. A live published price (``facts.live``), then the curated registry price
   (``facts.curated``), both through :func:`rate_prices`.
3. An explicit curated ``cost_lane`` of ``free`` / ``local`` (a curated
   ``paid`` lane is a fail-closed routing default, not a price, so it says
   nothing here).
4. A per-source declaration (:data:`SOURCE_DECLARATIONS`).
5. Otherwise unknown, "price not published".
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
REASON_NVIDIA_FREE_TIER = "free tier declared for nvidia"
REASON_GEMINI_UNCONFIRMED = "free tier not confirmed"
REASON_NVIDIA_VIA_OPENAI = "free tier declared for nvidia (via OPENAI_BASE_URL)"

# Whole-source declarations (providers.toml ``free = "tier"`` / ``"unconfirmed"``).
# NVIDIA's hosted API is a declared free tier. Gemini's free tier applies only
# while billing is off for the key's project, which cannot be seen from here,
# so it stays unknown rather than free.
SOURCE_DECLARATIONS: dict[str, tuple[PriceLabel, str]] = {
    "nvidia": ("free", REASON_NVIDIA_FREE_TIER),
    "gemini": ("unknown", REASON_GEMINI_UNCONFIRMED),
}


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


def rate_prices(prices: Prices) -> tuple[PriceLabel, str]:
    """Label a set of published prices (af-probes' price rule, verbatim).

    Any negative or non-finite price -> unknown. Any token price above 0 ->
    paid. Both token prices exactly 0 -> paid if a per-request fee is above 0,
    otherwise free. Anything else (a token price missing) -> unknown.
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
    """``rate_prices`` unless it found nothing to go on (so the next source can speak)."""
    if prices is None:
        return None
    verdict = rate_prices(prices)
    return None if verdict == ("unknown", REASON_NOT_PUBLISHED) else verdict


def label_price(facts: PriceFacts) -> tuple[PriceLabel, str]:
    """Return ``(label, reason)`` for one model; a missing price is never 0."""
    if facts.placement == "this_machine":
        return "local", REASON_LOCAL
    if facts.placement == "ollama_cloud":
        return "unknown", REASON_OLLAMA_CLOUD
    if facts.placement == "unverified_address":
        return "unknown", REASON_ADDRESS
    if facts.placement == "nvidia_via_openai":
        return SOURCE_DECLARATIONS["nvidia"][0], REASON_NVIDIA_VIA_OPENAI
    for prices in (facts.live, facts.curated):
        verdict = _priced_verdict(prices)
        if verdict is not None:
            return verdict
    if facts.curated_lane == "free":
        return "free", REASON_CURATED_FREE
    if facts.curated_lane == "local":
        return "local", REASON_LOCAL
    declared = SOURCE_DECLARATIONS.get(facts.provider)
    if declared is not None:
        return declared
    return "unknown", REASON_NOT_PUBLISHED


__all__ = [
    "SOURCE_DECLARATIONS",
    "CuratedLane",
    "Placement",
    "PriceFacts",
    "PriceLabel",
    "Prices",
    "label_price",
    "rate_prices",
]
