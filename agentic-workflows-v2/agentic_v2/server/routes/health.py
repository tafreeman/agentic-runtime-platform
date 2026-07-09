"""Health and readiness endpoints for the Agentic server.

Two probes with distinct semantics:

* ``GET /api/health`` -- cheap **liveness** probe. Returns a static
  ``{"status": "ok", "version": "0.1.0"}`` with no dependency inspection.
  Answers "is the process alive?" and nothing more.
* ``GET /api/health/ready`` -- **readiness** probe. Inspects critical
  dependencies (Redis, when configured) plus routing health (degraded
  selections, open circuit breakers). Returns HTTP 503 when a configured
  critical dependency is unreachable, so orchestrators stop sending traffic
  to a process that is alive but cannot serve correctly.

Both paths are public (``/api/health*`` is listed in the auth public prefixes
in :mod:`~agentic_v2.server.auth`).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Response, status

from ...models.model_stats import CircuitState
from ...settings import get_settings, is_agentic_no_llm_enabled
from ..models import DependencyStatus, HealthResponse, ReadinessResponse

if TYPE_CHECKING:
    from ...models.redis_state import RedisCircuitBreakerStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Cached Redis store for the readiness probe. Creating and closing a fresh
# connection pool on every probe would churn sockets (TIME_WAIT exhaustion
# under frequent orchestrator health checks); instead the probe keeps one
# store alive and only reconnects when the URL changes or the connection
# drops. Guarded by a lock so concurrent probes don't race the (re)connect.
_redis_probe_store: RedisCircuitBreakerStore | None = None
_redis_probe_lock = asyncio.Lock()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe: confirm the process is alive (no dependency checks).

    Also reports ``no_llm_mode``, read live from the environment via
    :func:`is_agentic_no_llm_enabled` (not the cached ``get_settings()``
    singleton) so a flag flipped after process start is reflected
    immediately -- callers such as the dashboard should trust this field
    over any client-side build-time flag.
    """
    return HealthResponse(no_llm_mode=is_agentic_no_llm_enabled())


async def _check_redis(redis_url: str | None) -> DependencyStatus:
    """Probe Redis connectivity when a URL is configured.

    Returns a ``DependencyStatus`` whose ``status`` is:
      * ``skipped`` -- no ``redis_url`` configured (Redis is optional).
      * ``ok``      -- a live PING succeeded.
      * ``down``    -- configured but the connection/PING failed (critical).

    The Redis URL is never echoed back (it may embed credentials).
    """
    if not redis_url:
        return DependencyStatus(
            name="redis", status="skipped", detail="redis_url not configured"
        )

    # Imported lazily so the endpoint works even without the redis extra.
    from ...models.redis_state import RedisCircuitBreakerStore

    global _redis_probe_store
    async with _redis_probe_lock:
        store = _redis_probe_store
        # (Re)connect only when there is no usable cached store: first probe,
        # URL changed, or the previous connection was lost. A healthy cached
        # store costs zero new connections per probe.
        if store is None or store.redis_url != redis_url or not store.is_connected:
            if store is not None:
                await store.close()
            store = await RedisCircuitBreakerStore.connect(redis_url=redis_url)
            _redis_probe_store = store

        try:
            alive = store.is_connected and await asyncio.wait_for(
                store.health_check(), timeout=2.0
            )
        except TimeoutError:
            return DependencyStatus(
                name="redis",
                status="down",
                detail="health check timed out",
            )
        if alive:
            return DependencyStatus(name="redis", status="ok")
        # health_check marks the store disconnected on connection errors, so
        # the next probe reconnects rather than reusing a dead pool.
        return DependencyStatus(
            name="redis",
            status="down",
            detail="Redis is configured but did not respond to PING",
        )


def _routing_health() -> tuple[int, list[str]]:
    """Return (degraded_selection_count, open_circuit_breaker_models).

    Reads the process-global SmartModelRouter without forcing creation of
    backend connections — purely an in-memory state inspection.
    """
    from ...models.smart_router import get_smart_router

    smart_router = get_smart_router()
    open_breakers = [
        model
        for model, stats in smart_router.model_stats.items()
        if stats.circuit_state == CircuitState.OPEN
    ]
    return smart_router.degraded_selection_count, open_breakers


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness_check(response: Response) -> ReadinessResponse:
    """Readiness probe: 200 when serviceable, 503 when a critical dep is down.

    Critical dependency today is Redis (only when ``redis_url`` is set). Open
    circuit breakers and degraded-selection counts are reported for visibility
    but do not by themselves flip readiness to 503 — the process can still
    serve via healthy tiers/fallback.
    """
    settings = get_settings()

    dependencies: list[DependencyStatus] = []
    redis_status = await _check_redis(getattr(settings, "redis_url", None))
    dependencies.append(redis_status)

    degraded_count, open_breakers = _routing_health()

    critical_down = any(dep.status == "down" for dep in dependencies)
    if critical_down:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        ready = "not_ready"
    else:
        ready = "ready"

    return ReadinessResponse(
        status=ready,
        dependencies=dependencies,
        degraded_selection_count=degraded_count,
        open_circuit_breakers=open_breakers,
    )
