"""Unified model discovery snapshot across every serving path (ARP-IMPROVEMENTS F2).

Before this module, a caller needing "what can this machine reach right now"
had to know which of five differently-shaped functions to call --
:func:`agentic_v2.models.cloud_discovery.discover_cloud_models`,
:func:`agentic_v2.models.ollama_discovery.discover_ollama_models`,
:func:`agentic_v2.models.local_discovery.discover_lmstudio_models` /
:func:`~agentic_v2.models.local_discovery.discover_onnx_models`, plus the three
this change adds (Lemonade, Docker Model Runner, Foundry Local) -- and
reconcile records of three different shapes. :func:`discover_all_models`
returns one list of :class:`DiscoveredModel` covering all seven.

Each record's ``cost_lane`` is curated, never guessed:

- local/lmstudio/onnx/lemonade/docker-model-runner/foundry-local -- ``"local"``
  (weights on this machine, no account, no charge). Ollama is more involved:
  a model reroutes to ``"free"`` (Ollama Cloud) when it would actually be
  invoked at ``CLOUD_HOST`` (mirroring ``build_ollama_model``'s own ADR-051
  decision -- keyed *and* not found in the local listing; the raw
  ``published :cloud/-cloud`` classification alone is not sufficient, since a
  locally-listed entry can carry that suffix with no ``remote_host`` stamp
  and still be served locally) or when ``OLLAMA_BASE_URL`` itself is not
  loopback (mirroring :func:`agentic_v2.models.model_registry.cost_lane_for`'s
  own downgrade -- every call already leaves this machine regardless of any
  cloud classification).
- every cloud id (including nvidia) -- :func:`agentic_v2.models.model_registry.cost_lane_for`,
  which fails closed to ``"paid"`` for any id not curated in
  ``model_registry.yaml``. This is also where NVIDIA NIM's curated
  free-endpoint models live (as ``tiers: []`` entries -- curated for cost
  lane, deliberately not promoted into a tier chain). A newly-discovered,
  uncurated cloud id is therefore reported ``"paid"`` even when it might in
  fact be free -- ADR-040 holds: discovery never promotes a judgment call the
  registry has not made.

**Per ADR-040, this module only WARNS and reports.** It never adds a
discovered id to a tier chain -- that stays a deliberate, human-reviewed edit
to ``model_registry.yaml``.

``verify=True`` (completing one real chat call per model, distinguishing
``verified_by: completion`` from the default ``verified_by: listing``, and
telling ``empty_response``/``timeout``/``unavailable`` apart) is
ARP-IMPROVEMENTS F3 and is intentionally not implemented here -- seeing this
raise means F3 was requested, not a bug. F3 also matters for a reason beyond
scope: verifying by placing a real call against a *paid*-lane model would
itself spend money, which is exactly what F1's cost-lane ceiling exists to
prevent, so a correct implementation must thread ``AGENTIC_MAX_COST_LANE``
through verification too. Deferred together, not split.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

VerifiedBy = Literal["listing", "completion"]


@dataclass(frozen=True)
class DiscoveredModel:
    """One model, from any serving path, in a single uniform shape."""

    id: str  # provider-prefixed, e.g. "ollama:qwen3:1.7b", "nvidia:meta/llama-3.1-8b-instruct"
    provider: str
    endpoint: str | None
    cost_lane: Literal["local", "free", "paid"]
    reachable: bool
    verified_by: VerifiedBy
    latency_ms: float | None
    probed_at: str  # ISO 8601 UTC timestamp of this snapshot, not per-model

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view for API responses / a persisted snapshot file."""
        return {
            "id": self.id,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "cost_lane": self.cost_lane,
            "reachable": self.reachable,
            "verified_by": self.verified_by,
            "latency_ms": self.latency_ms,
            "probed_at": self.probed_at,
        }


def _endpoint_for_cloud_provider(provider: str) -> str | None:
    """Best-effort endpoint description for a keyed cloud provider."""
    if provider == "nvidia":
        from .cloud_discovery import resolve_nvidia_base_url

        return resolve_nvidia_base_url()
    if provider == "openrouter":
        from .cloud_discovery import resolve_openrouter_base_url

        return resolve_openrouter_base_url()
    if provider == "openai":
        return (
            os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("OPENAI_API_BASE")
            or "https://api.openai.com/v1"
        )
    static = {
        "anthropic": "https://api.anthropic.com",
        "gemini": "https://generativelanguage.googleapis.com",
        "gh": "https://models.github.ai",
    }
    return static.get(provider)


def discover_all_models(*, verify: bool = False) -> list[DiscoveredModel]:
    """Return one uniform record per model across every serving path.

    Aggregates :mod:`cloud_discovery` (openai/anthropic/gemini/gh/nvidia/
    openrouter), :mod:`ollama_discovery`, :mod:`local_discovery` (LM Studio +
    ONNX), and the three paths this change adds (:mod:`lemonade_discovery`,
    :mod:`docker_model_runner_discovery`, :mod:`foundry_local_discovery`).
    Every source is best-effort already (never raises), so this function
    never raises either. ``reachable`` reflects "this source's listing
    included it" -- see the module docstring for why ``verify=True`` (a real
    completion call) is not implemented here.

    Raises:
        NotImplementedError: if ``verify=True`` -- ARP-IMPROVEMENTS F3, not
            implemented as part of F2. See the module docstring.
    """
    if verify:
        raise NotImplementedError(
            "discover_all_models(verify=True) is ARP-IMPROVEMENTS F3 "
            "(per-model real completion call, think:false / empty-response / "
            "timeout handling, and a cost-lane-aware ceiling on which lanes "
            "verification is allowed to call) and was deferred, not "
            "implemented, when F1/F2 were built. Call with verify=False "
            "(the default) for a listing-only snapshot."
        )

    probed_at = datetime.now(UTC).isoformat()
    models: list[DiscoveredModel] = []

    from ..langchain.model_utils import provider_prefix
    from .cloud_discovery import discover_cloud_models
    from .model_registry import cost_lane_for

    for info in discover_cloud_models():
        provider = provider_prefix(info.id)
        models.append(
            DiscoveredModel(
                id=info.id,
                provider=provider,
                endpoint=_endpoint_for_cloud_provider(provider),
                cost_lane=cost_lane_for(info.id),
                reachable=True,
                verified_by="listing",
                latency_ms=None,
                probed_at=probed_at,
            )
        )

    from .model_registry import ollama_base_is_loopback
    from .ollama_discovery import (
        CLOUD_HOST,
        DEFAULT_LOCAL_HOST,
        ENV_API_KEY,
        discover_ollama_models,
        is_served_locally,
    )
    from .ollama_discovery import ENV_BASE_URL as OLLAMA_ENV

    ollama_endpoint = os.environ.get(OLLAMA_ENV, DEFAULT_LOCAL_HOST)
    ollama_keyed = bool(os.environ.get(ENV_API_KEY))
    ollama_loopback = ollama_base_is_loopback()
    for ollama_info in discover_ollama_models():
        # Mirrors build_ollama_model's own reroute decision exactly
        # (ADR-051): cloud=True alone does NOT mean "reached via CLOUD_HOST"
        # -- _is_cloud() also classifies a LOCALLY-listed entry as cloud via
        # a `:cloud`/`-cloud` name-suffix fallback when no remote_host stamp
        # is present, and that entry is still served through the local
        # endpoint (it came from the local /api/tags listing). Only a keyed
        # request for a model NOT found there actually reroutes.
        reroutes_to_cloud = ollama_keyed and not is_served_locally(ollama_info.name)
        endpoint = CLOUD_HOST if reroutes_to_cloud else ollama_endpoint
        # Mirrors cost_lane_for's downgrade: a non-loopback OLLAMA_BASE_URL
        # means every call already leaves this machine regardless of the
        # cloud/local classification above (a live-discovered id has no
        # registry entry to route through cost_lane_for itself, so this
        # reimplements its same two checks for consistency).
        if reroutes_to_cloud or not ollama_loopback:
            cost_lane: Literal["local", "free", "paid"] = "free"
        else:
            cost_lane = "free" if ollama_info.cloud else "local"
        models.append(
            DiscoveredModel(
                id=ollama_info.id,
                provider="ollama",
                endpoint=endpoint,
                cost_lane=cost_lane,
                reachable=True,
                verified_by="listing",
                latency_ms=None,
                probed_at=probed_at,
            )
        )

    from .local_discovery import (
        discover_lmstudio_catalog,
        discover_onnx_models,
        resolve_lmstudio_host,
    )

    lmstudio_catalog = discover_lmstudio_catalog()
    lmstudio_endpoint = resolve_lmstudio_host() if lmstudio_catalog.models else None
    for lmstudio_info in lmstudio_catalog.models:
        models.append(
            DiscoveredModel(
                id=lmstudio_info.id,
                provider="lmstudio",
                endpoint=lmstudio_endpoint,
                cost_lane="local",
                reachable=True,
                verified_by="listing",
                latency_ms=None,
                probed_at=probed_at,
            )
        )
    for onnx_info in discover_onnx_models():
        models.append(
            DiscoveredModel(
                id=onnx_info.id,
                provider="onnx",
                endpoint=None,  # filesystem-scanned, not a network endpoint
                cost_lane="local",
                reachable=True,
                verified_by="listing",
                latency_ms=None,
                probed_at=probed_at,
            )
        )

    from .docker_model_runner_discovery import (
        DEFAULT_BASE_URL as DMR_DEFAULT,
    )
    from .docker_model_runner_discovery import (
        ENV_BASE_URL as DMR_ENV,
    )
    from .docker_model_runner_discovery import (
        discover_docker_model_runner_models,
    )
    from .foundry_local_discovery import (
        DEFAULT_BASE_URL as FOUNDRY_DEFAULT,
    )
    from .foundry_local_discovery import (
        ENV_BASE_URL as FOUNDRY_ENV,
    )
    from .foundry_local_discovery import (
        discover_foundry_local_models,
    )
    from .lemonade_discovery import (
        DEFAULT_BASE_URL as LEMONADE_DEFAULT,
    )
    from .lemonade_discovery import (
        ENV_BASE_URL as LEMONADE_ENV,
    )
    from .lemonade_discovery import (
        discover_lemonade_models,
    )

    for lemonade_info in discover_lemonade_models():
        models.append(
            DiscoveredModel(
                id=lemonade_info.id,
                provider="lemonade",
                endpoint=os.environ.get(LEMONADE_ENV, LEMONADE_DEFAULT),
                cost_lane="local",
                reachable=True,
                verified_by="listing",
                latency_ms=None,
                probed_at=probed_at,
            )
        )
    for dmr_info in discover_docker_model_runner_models():
        models.append(
            DiscoveredModel(
                id=dmr_info.id,
                provider="docker-model-runner",
                endpoint=os.environ.get(DMR_ENV, DMR_DEFAULT),
                cost_lane="local",
                reachable=True,
                verified_by="listing",
                latency_ms=None,
                probed_at=probed_at,
            )
        )
    for foundry_info in discover_foundry_local_models():
        models.append(
            DiscoveredModel(
                id=foundry_info.id,
                provider="foundry-local",
                endpoint=os.environ.get(FOUNDRY_ENV, FOUNDRY_DEFAULT),
                cost_lane="local",
                reachable=True,
                verified_by="listing",
                latency_ms=None,
                probed_at=probed_at,
            )
        )

    return models


__all__ = ["DiscoveredModel", "discover_all_models"]
