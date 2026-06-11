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

import logging

from fastapi import APIRouter, Response, status

from ...models.model_stats import CircuitState
from ...settings import get_settings
from ..models import DependencyStatus, HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe: confirm the process is alive (no dependency checks)."""
    return HealthResponse()


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

    store = await RedisCircuitBreakerStore.connect(redis_url=redis_url)
    try:
        if store.is_connected and await store.health_check():
            return DependencyStatus(name="redis", status="ok")
        return DependencyStatus(
            name="redis",
            status="down",
            detail="Redis is configured but did not respond to PING",
        )
    finally:
        await store.close()


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
