"""Annotate model-probe rows with ``price_label`` / ``price_reason``.

The impure half of the price-label feature: it reads what ARP knows about each
model -- the environment (where Ollama / LM Studio / the hosted APIs point), the
curated registry, and the live cloud listing -- and hands it to the pure rule in
:mod:`agentic_v2.models.price_label`, which is ported from ``af-probes``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .cloud_discovery import (
    CloudModelInfo,
    nvidia_base_is_documented,
    openai_base_is_nvidia,
    openrouter_base_is_documented,
)
from .local_discovery import _LMSTUDIO_HOST_ENV
from .model_registry import (
    RegisteredModel,
    is_loopback_url,
    load_registry,
    ollama_base_is_loopback,
)
from .ollama_discovery import _CLOUD_SUFFIXES, ENV_API_KEY, is_served_locally
from .price_label import Placement, PriceFacts, Prices, label_price

# Providers whose weights always run on this machine and have no address to check.
_ALWAYS_ON_MACHINE = frozenset({"local", "onnx"})

# Hosted providers whose base URL can be overridden and whose price or free-tier
# claim only holds at the documented origin (an on-prem NIM or a gateway is not it).
_DOCUMENTED_ADDRESS_CHECKS: dict[str, Callable[[], bool]] = {
    "openrouter": openrouter_base_is_documented,
    "nvidia": nvidia_base_is_documented,
}


def _lmstudio_host_is_loopback() -> bool:
    """Whether ``LMSTUDIO_HOST`` is unset (default loopback) or points at loopback."""
    host = os.environ.get(_LMSTUDIO_HOST_ENV, "").strip()
    if not host:
        return True
    return bool(is_loopback_url(host if "://" in host else f"http://{host}"))


def _ollama_placement(model: Mapping[str, Any]) -> Placement:
    """Local only when the call stays on this machine; anything else is cloud.

    Mirrors where ``build_ollama_model`` actually sends the call (ADR-051): a
    non-loopback ``OLLAMA_BASE_URL``, a model discovery marked cloud, and -- for
    a model discovery never saw -- a ``:cloud`` / ``-cloud`` name or an
    ``OLLAMA_API_KEY`` that reroutes a not-pulled model to ollama.com.
    """
    if not ollama_base_is_loopback() or model.get("cloud") is True:
        return "ollama_cloud"
    if "cloud" not in model:
        name = str(model["id"]).removeprefix("ollama:")
        if name.endswith(_CLOUD_SUFFIXES):
            return "ollama_cloud"
        if os.environ.get(ENV_API_KEY) and not is_served_locally(name):
            return "ollama_cloud"
    return "this_machine"


def _placement(model: Mapping[str, Any]) -> Placement:
    provider = str(model["provider"])
    if provider == "ollama":
        return _ollama_placement(model)
    if provider == "lmstudio":
        return "this_machine" if _lmstudio_host_is_loopback() else "unverified_address"
    if provider in _ALWAYS_ON_MACHINE:
        return "this_machine"
    if provider == "openai" and openai_base_is_nvidia():
        return "nvidia_via_openai"
    documented = _DOCUMENTED_ADDRESS_CHECKS.get(provider)
    if documented is not None and not documented():
        return "unverified_address"
    return "hosted"


def _live_prices(info: CloudModelInfo | None) -> Prices | None:
    """The listing's published prices, or ``None`` when it published none."""
    if info is None:
        return None
    triple = (info.price_in, info.price_out, info.price_request)
    return None if all(p is None for p in triple) else Prices(*triple)


def _curated_prices(entry: RegisteredModel | None) -> Prices | None:
    """The registry's token prices, or ``None`` when it records none."""
    if entry is None or (entry.price_in is None and entry.price_out is None):
        return None
    return Prices(price_in=entry.price_in, price_out=entry.price_out)


def annotate_price_labels(
    models: Sequence[Mapping[str, Any]],
    cloud_listing: Sequence[CloudModelInfo] = (),
) -> list[dict[str, Any]]:
    """Return copies of ``models`` with ``price_label`` and ``price_reason`` added.

    Every row gets both fields. ``cloud_listing`` is the same sweep the probe
    merged into ``models``; it supplies live published prices (OpenRouter).
    """
    registry = load_registry().by_id()
    live = {info.id: info for info in cloud_listing}
    annotated: list[dict[str, Any]] = []
    for model in models:
        entry = registry.get(str(model["id"]))
        facts = PriceFacts(
            provider=str(model["provider"]),
            placement=_placement(model),
            live=_live_prices(live.get(str(model["id"]))),
            curated=_curated_prices(entry),
            curated_lane=None if entry is None else entry.cost_lane,
        )
        label, reason = label_price(facts)
        annotated.append({**model, "price_label": label, "price_reason": reason})
    return annotated


__all__ = ["annotate_price_labels"]
