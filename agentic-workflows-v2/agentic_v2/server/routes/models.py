"""Model provider discovery and probe endpoint.

Provides ``GET /api/models/probe`` which re-runs the provider availability
check and returns the current tier-to-model mapping so clients can inspect
which backends are active without restarting the server.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ...models.local_discovery import (
    LmStudioLoadError,
    LmStudioUnavailableError,
    discover_lmstudio_catalog,
    load_lmstudio_model,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


class LmStudioLoadRequest(BaseModel):
    """Request to load one model already present in LM Studio's library."""

    model: str = Field(min_length=1, max_length=512)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        """Trim the id and reject control characters before forwarding JSON."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("model must not be blank")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("model must not contain control characters")
        return normalized


class LmStudioLoadResponse(BaseModel):
    """Stable ARP response for a native LM Studio model-load operation."""

    model: str
    status: Literal["loaded", "already_loaded"]
    instance_id: str | None = None
    load_time_seconds: float | None = None
    running: bool = True


@router.get(
    "/models/probe",
    responses={
        500: {"description": "Internal Server Error"},
        503: {"description": "Service Unavailable"},
    },
)
async def probe_models() -> dict[str, Any]:
    """Re-probe available LLM providers and return current tier defaults.

    Runs the same availability check as server startup so tier defaults
    reflect the current environment (useful after rotating API keys or
    bringing up a new local provider).
    """
    try:
        from ...langchain.models import (
            enumerate_known_models,
            probe_and_update_tier_defaults,
        )
        from ...models.cloud_discovery import discover_cloud_models
        from ...settings import is_agentic_no_llm_enabled

        def _probe() -> dict[str, Any]:
            # Both calls perform blocking network I/O (Ollama/LM Studio httpx
            # requests, up to ~5s each). Run together in a thread so the async
            # event loop is never frozen for concurrent requests.
            # Fetch the cloud listing ONCE and share it between the registry
            # drift pass and the catalog merge — each previously ran its own
            # full sweep per request (only OpenRouter's slice is TTL-cached).
            cloud_listing = (
                None if is_agentic_no_llm_enabled() else discover_cloud_models()
            )
            result = probe_and_update_tier_defaults(cloud_listing=cloud_listing)
            result["models"] = enumerate_known_models(cloud_listing=cloud_listing)
            return result

        summary = await asyncio.to_thread(_probe)
        summary["no_llm_mode"] = is_agentic_no_llm_enabled()
        logger.info(
            "On-demand model probe complete: available=%s, models=%d",
            summary["available_providers"],
            len(summary["models"]),
        )
        return summary
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LangChain extras not installed — cannot probe models: {exc}",
        ) from exc
    except Exception as exc:
        logger.exception("Model probe failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/models/lmstudio/load",
    response_model=LmStudioLoadResponse,
    responses={
        404: {"description": "Model is not in the downloaded LM Studio library"},
        409: {"description": "The server lacks the native v1 load API"},
        502: {"description": "LM Studio rejected the load request"},
        503: {"description": "LM Studio is unavailable"},
    },
)
async def load_lmstudio(request: LmStudioLoadRequest) -> LmStudioLoadResponse:
    """Load one discovered LM Studio chat model into memory.

    The discovery guard prevents this route from becoming an arbitrary model
    loader: only chat-capable models returned by the configured LM Studio
    library can be loaded. Already-loaded models are an idempotent success.
    When discovery fell back to a pre-v1 API, loading is rejected up front —
    POSTing the v1 load endpoint at such a server would only 404.
    """
    key = request.model.removeprefix("lmstudio:")
    full_id = f"lmstudio:{key}"
    catalog = await asyncio.to_thread(discover_lmstudio_catalog)
    info = next((item for item in catalog.models if item.id == full_id), None)
    if info is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"{full_id} was not found in the configured LM Studio chat library"
            ),
        )
    if info.running:
        return LmStudioLoadResponse(model=full_id, status="already_loaded")
    if not catalog.supports_load:
        raise HTTPException(
            status_code=409,
            detail=(
                "The LM Studio server does not expose the native v1 load API "
                f"(discovered via {catalog.api!r}); load the model in the "
                "LM Studio app instead"
            ),
        )

    try:
        result = await asyncio.to_thread(load_lmstudio_model, key)
    except LmStudioUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LmStudioLoadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    instance_id = result.get("instance_id")
    load_time_seconds = result.get("load_time_seconds")
    return LmStudioLoadResponse(
        model=full_id,
        status="loaded",
        instance_id=instance_id if isinstance(instance_id, str) else None,
        load_time_seconds=(
            float(load_time_seconds)
            if isinstance(load_time_seconds, (int, float))
            else None
        ),
    )


#: Providers that :func:`discover_all_models` can enumerate but that
#: ``get_chat_model()`` has no execution builder for, so a discovered id
#: cannot actually be run yet. They are surfaced with this flag rather than
#: hidden: leaving them out entirely is what made them invisible, but
#: listing them as selectable would trade one wrong answer for another.
#: Kept in sync with the deliberate omission in
#: ``agentic_v2.langchain.model_utils.PROVIDER_ENV_KEYS``.
DISCOVERY_ONLY_PROVIDERS: frozenset[str] = frozenset(
    {"lemonade", "docker-model-runner", "foundry-local"}
)


@router.get(
    "/models/discovery-snapshot",
    responses={500: {"description": "Internal Server Error"}},
)
async def models_discovery_snapshot() -> dict[str, Any]:
    """Every model ARP can see, across every serving path, in one response.

    ``/models/probe`` answers a narrower question -- which tier defaults are
    live -- and reaches only the cloud, Ollama, LM Studio and ONNX paths. The
    Lemonade, Docker Model Runner and Foundry Local backends have discovery
    implementations and tests but no HTTP caller, so models served by them
    were invisible to every client. This exposes
    :func:`agentic_v2.models.discovery_snapshot.discover_all_models`, which
    already aggregates all eight provider families in one uniform shape.

    Listing-only: ``verify=True`` is unimplemented upstream (ARP-IMPROVEMENTS
    F3), so ``reachable`` means "this provider's listing included it", not
    "a completion call succeeded".
    """
    from ...models.discovery_snapshot import discover_all_models

    try:
        models = await asyncio.to_thread(discover_all_models)
    except Exception as exc:  # pragma: no cover - defensive, facade is best-effort
        logger.exception("Discovery snapshot failed")
        raise HTTPException(
            status_code=500, detail=f"discovery snapshot failed: {exc}"
        ) from exc

    payload = []
    seen: set[str] = set()
    by_provider: dict[str, int] = {}
    for model in models:
        record = model.to_dict()
        record["runnable"] = model.provider not in DISCOVERY_ONLY_PROVIDERS
        record["source"] = "discovered"
        payload.append(record)
        seen.add(model.id)
        by_provider[model.provider] = by_provider.get(model.provider, 0) + 1

    # Union in the curated registry. Discovery lists what a provider is
    # serving right now; the registry declares what ARP is configured to use,
    # and the two are not nested. A curated id whose provider listing no
    # longer returns it (ADR-040 calls these quarantined) exists only here,
    # and GitHub Models is declared but not enumerated by cloud discovery at
    # all -- so a snapshot built from discovery alone silently drops both.
    from ...models import model_registry

    try:
        for model_id in sorted(model_registry.all_ids()):
            if model_id in seen:
                continue
            provider = model_registry.provider_for(model_id)
            payload.append(
                {
                    "id": model_id,
                    "provider": provider,
                    "endpoint": None,
                    "cost_lane": model_registry.cost_lane_for(model_id),
                    "reachable": False,
                    "verified_by": "registry",
                    "latency_ms": None,
                    "probed_at": None,
                    "runnable": provider not in DISCOVERY_ONLY_PROVIDERS,
                    # Curated, but this run's provider listing did not include
                    # it -- either the provider is unkeyed or the id is
                    # quarantined. Listed, flagged, not silently dropped.
                    "source": "registry-only",
                }
            )
            seen.add(model_id)
            by_provider[provider] = by_provider.get(provider, 0) + 1
    except Exception:  # pragma: no cover - registry is optional at runtime
        logger.exception("Curated registry unavailable for the snapshot")

    return {
        "total": len(payload),
        "by_provider": dict(sorted(by_provider.items(), key=lambda kv: -kv[1])),
        "discovery_only_providers": sorted(DISCOVERY_ONLY_PROVIDERS),
        "sources": {
            "discovered": sum(1 for m in payload if m["source"] == "discovered"),
            "registry_only": sum(1 for m in payload if m["source"] == "registry-only"),
        },
        "models": payload,
    }
