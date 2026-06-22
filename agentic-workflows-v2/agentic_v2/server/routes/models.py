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


@router.get("/models/probe", responses={
    500: {"description": "Internal Server Error"},
    503: {"description": "Service Unavailable"},
})
async def probe_models() -> dict[str, Any]:
    """Re-probe available LLM providers and return current tier defaults.

    Runs the same availability check as server startup so tier defaults
    reflect the current environment (useful after rotating API keys or
    bringing up a new local provider).
    """
    try:
        from ...langchain.models import probe_and_update_tier_defaults

        # The probe performs blocking network I/O (live Ollama discovery does
        # up to three synchronous httpx requests, ~5s each). Offload to a thread
        # so the async event loop is never frozen for concurrent requests.
        summary = await asyncio.to_thread(probe_and_update_tier_defaults)
        logger.info(
            "On-demand model probe complete: available=%s",
            summary["available_providers"],
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
