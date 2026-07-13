"""Model provider discovery, probe, and family-ranking endpoints.

Provides:

* ``GET /api/models/probe`` — re-runs the provider availability check and
  returns the current tier-to-model mapping so clients can inspect which
  backends are active without restarting the server.
* ``GET /api/models/rankings`` — returns the cached model-family rankings
  (empty shape when no ranking has run yet).
* ``POST /api/models/autorank`` — kicks off a background family-ranking job
  (202), short-circuits to the cached payload when it is fresh (200), and
  refuses to stack jobs (409) or rank in no-LLM mode (503).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...models.model_rankings import (
    RankingsPayload,
    load_rankings,
    normalize_family,
    rankings_cache_is_fresh,
    resolve_ranker_model,
    run_autorank,
    save_rankings,
)
from .chat import _safe_error_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])

#: Guards the single-flight autorank job. Acquired non-blocking by the POST
#: handler and released by the background job's ``finally`` (``threading.Lock``
#: may be released from a different thread than the one that acquired it).
_AUTORANK_LOCK = threading.Lock()


class AutorankRequest(BaseModel):
    """``POST /api/models/autorank`` body."""

    model: str | None = None
    force: bool = False


class AutorankStartedResponse(BaseModel):
    """202 payload confirming a ranking job was kicked off."""

    status: Literal["started"] = "started"
    ranked_with: str


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


def _collect_family_names() -> list[str]:
    """Enumerate the model catalog and reduce it to sorted unique family keys.

    Reuses the same sweep as ``GET /api/models/probe``: one shared cloud
    listing threaded into ``enumerate_known_models`` so the ranking job never
    runs its own per-provider discovery pass.
    """
    from ...langchain.models import enumerate_known_models
    from ...models.cloud_discovery import discover_cloud_models

    cloud_listing = discover_cloud_models()
    models = enumerate_known_models(cloud_listing=cloud_listing)
    families = {normalize_family(str(entry.get("id", ""))) for entry in models}
    return sorted(family for family in families if family)


def _run_autorank_job(ranker_model: str) -> None:
    """Background worker: enumerate families, rank them, persist the result.

    Always writes an honest terminal cache state — ``ready`` with provenance
    on success, ``failed`` with a scrubbed error otherwise — and always
    releases the single-flight lock.
    """
    try:
        families = _collect_family_names()
        payload = run_autorank(families, ranker_model)
        save_rankings(payload)
    except Exception as exc:
        safe_message = _safe_error_message(exc)
        logger.warning(
            "Autorank job failed: ranker=%s, error=%s", ranker_model, safe_message
        )
        save_rankings(
            RankingsPayload(
                status="failed",
                ranked_with=ranker_model,
                grounded=None,
                updated_at=None,
                error=safe_message,
                families={},
            )
        )
    finally:
        _AUTORANK_LOCK.release()


@router.get("/models/rankings", response_model=RankingsPayload)
async def get_model_rankings() -> RankingsPayload:
    """Return the cached model-family rankings (empty shape when unranked).

    The payload always carries its provenance — ``ranked_with``, ``grounded``,
    and ``updated_at`` — so clients can distinguish grounded web-search
    rankings from knowledge-only ones and show their age.
    """
    return await asyncio.to_thread(load_rankings)


@router.post(
    "/models/autorank",
    status_code=202,
    response_model=AutorankStartedResponse,
    responses={
        200: {
            "model": RankingsPayload,
            "description": "Fresh cache short-circuit (updated_at < 7 days).",
        },
        409: {"description": "A ranking job is already running."},
        503: {"description": "No-LLM mode — placeholder scores would be garbage."},
    },
)
async def autorank_models(
    request: AutorankRequest, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Start a background model-family ranking job.

    Returns 202 with the resolved ranker when a job kicks off, 200 with the
    full cached payload when it is fresh (< 7 days) and ``force`` is unset,
    409 while a job is running, and 503 in ``AGENTIC_NO_LLM`` mode.
    """
    from ...settings import is_agentic_no_llm_enabled

    if is_agentic_no_llm_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "AGENTIC_NO_LLM mode is active — the placeholder model cannot "
                "produce honest rankings."
            ),
        )

    ranker_model = resolve_ranker_model(request.model)

    cached = await asyncio.to_thread(load_rankings)
    if not request.force and rankings_cache_is_fresh(cached):
        return JSONResponse(status_code=200, content=cached.model_dump(mode="json"))

    if not _AUTORANK_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="A ranking job is already running."
        )
    try:
        await asyncio.to_thread(
            save_rankings,
            RankingsPayload(status="running", ranked_with=ranker_model),
        )
        background_tasks.add_task(_run_autorank_job, ranker_model)
    except Exception:
        _AUTORANK_LOCK.release()
        raise

    logger.info("Autorank job started: ranker=%s", ranker_model)
    started = AutorankStartedResponse(ranked_with=ranker_model)
    return JSONResponse(status_code=202, content=started.model_dump(mode="json"))
