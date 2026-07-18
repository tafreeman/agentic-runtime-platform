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
    discover_lmstudio_models,
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
        502: {"description": "LM Studio rejected the load request"},
        503: {"description": "LM Studio is unavailable"},
    },
)
async def load_lmstudio(request: LmStudioLoadRequest) -> LmStudioLoadResponse:
    """Load one discovered LM Studio chat model into memory.

    The discovery guard prevents this route from becoming an arbitrary model
    loader: only chat-capable models returned by the configured LM Studio
    library can be loaded. Already-loaded models are an idempotent success.
    """
    key = request.model.removeprefix("lmstudio:")
    full_id = f"lmstudio:{key}"
    discovered = await asyncio.to_thread(discover_lmstudio_models)
    info = next((item for item in discovered if item.id == full_id), None)
    if info is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"{full_id} was not found in the configured LM Studio chat library"
            ),
        )
    if info.running:
        return LmStudioLoadResponse(model=full_id, status="already_loaded")

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
