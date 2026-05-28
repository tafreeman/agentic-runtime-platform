"""HTTP metrics middleware for the Agentic Workflows V2 server.

Records per-request duration histograms and request count counters via the
OTEL Metrics API. Delegates to :func:`~agentic_v2.integrations.metrics.record_http_request`
which is a no-op when metrics are not enabled.

Path normalisation strips run IDs and numeric segments so cardinality stays
bounded (e.g. ``/api/runs/abc-123`` → ``/api/runs/{id}``).
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from ...integrations.metrics import record_http_request

logger = logging.getLogger(__name__)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that records HTTP request duration and counts.

    Attaches to the FastAPI application via ``app.add_middleware(MetricsMiddleware)``.
    Records:

    * ``http_request_duration_seconds`` histogram (method, route, status_code)
    * ``http_requests_total`` counter (method, route, status_code)

    The ``/metrics`` scrape path itself is excluded to prevent self-referential
    metric inflation and cardinality noise.
    """

    # Paths to exclude from instrumentation
    _SKIP_PATHS: frozenset[str] = frozenset({"/metrics"})

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        path = request.url.path

        # Skip the Prometheus scrape endpoint itself
        if path in self._SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        status_code = 500  # Default if call_next raises unexpectedly
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            try:
                record_http_request(
                    method=request.method,
                    path=path,
                    status_code=status_code,
                    duration_seconds=duration,
                )
            except Exception:
                # Never let metrics recording crash the request pipeline
                logger.debug("Metrics recording failed for %s %s", request.method, path)
