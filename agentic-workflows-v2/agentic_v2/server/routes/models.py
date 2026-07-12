"""Model provider discovery and probe endpoint.

Provides ``GET /api/models/probe`` which re-runs the provider availability
check and returns the current tier-to-model mapping so clients can inspect
which backends are active without restarting the server.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


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
