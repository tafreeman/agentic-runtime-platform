"""FastAPI application factory for the Agentic Workflows V2 server.

Provides :func:`create_app`, which assembles the FastAPI instance with
middleware, routes, and optional SPA serving. See sub-modules for details:

* :mod:`.middleware.rate_limit` — slowapi rate-limit setup
* :mod:`.lifespan` — startup/shutdown lifecycle management
* :mod:`.spa` — static SPA serving helpers
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..logging_config import configure_logging
from ..settings import get_settings
from . import websocket
from .audit_log import AuditLogger, NullAuditStore
from .auth import APIKeyMiddleware, AuthThrottle, get_allowed_origins
from .auth_oidc import OIDCAuthMiddleware, validate_oidc_settings
from .lifespan import (
    _initialize_sanitization_state,
    lifespan,
)
from .middleware.metrics import MetricsMiddleware
from .middleware.rate_limit import configure_rate_limiting
from .middleware.tracing import TraceparentMiddleware
from .routes import (
    agents,
    evaluation_routes,
    health,
    model_finder,
    models,
    runs,
    workflows,
)
from .spa import UI_DIST_DIR, _mount_spa

# Configure logging — JSON when LOG_FORMAT=json, text otherwise.
configure_logging(log_format=get_settings().log_format)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-export surface.
# ---------------------------------------------------------------------------
# Only `lifespan`, `_initialize_sanitization_state`, and `websocket` are
# reachable through `agentic_v2.server.app` (imported above; `create_app` is
# defined here). The lifecycle helpers the lifespan delegates to —
# `_install_smart_router`, `_validate_selected_adapter`, `_probe_llm_providers`,
# `build_audit_logger`, `_enforce_rate_limiting_available` — and the rate-limit
# flags (`_SLOWAPI_AVAILABLE` / `_RATE_LIMIT_DISABLED`) live in `.lifespan`.
# `lifespan()` calls them as bare names bound to the lifespan module's globals,
# so tests must import and patch them on `agentic_v2.server.lifespan`, NOT here
# — a re-export shim would not intercept those calls.


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Assembles middleware (CORS, API key auth, rate limiting), registers API
    route groups under ``/api/``, mounts the WebSocket endpoint, and
    optionally serves the built React SPA from ``ui/dist/``.

    Middleware order (outermost → innermost, i.e. request processing order):

    1. ``CORSMiddleware`` — CORS preflight / header injection (outermost so
       it can handle preflight OPTIONS requests before any other layer runs).
    2. ``SlowAPIMiddleware`` — global per-IP rate limiting.
    3. ``MetricsMiddleware`` — HTTP request duration and count recording.
    4. ``TraceparentMiddleware`` — W3C traceparent response-header injection.
    5. ``SanitizationASGIMiddleware`` — prompt-injection and secret redaction.
    6. ``APIKeyMiddleware`` — bearer-token authentication + per-IP 401 throttle
       (innermost).

    Note that ``app.add_middleware`` prepends each layer, so the first call
    adds the innermost middleware and the last call adds the outermost.
    CORSMiddleware is therefore registered last.

    Returns:
        A fully configured ``FastAPI`` instance ready for ``uvicorn``.
    """
    app = FastAPI(
        title="Agentic Workflows V2 API",
        description="REST API for multi-model AI workflow orchestration",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Per-IP auth failure throttle — stored on app.state so tests can inject
    # a fresh AuthThrottle instance with custom thresholds per test app.
    app.state.auth_throttle = AuthThrottle()
    app.state.audit_logger = AuditLogger(NullAuditStore(), enabled=False)
    _initialize_sanitization_state(app)

    settings = get_settings()

    # Authentication. OIDC mode preserves AGENTIC_API_KEY as a fallback.
    if settings.agentic_oidc_enabled:
        validate_oidc_settings(settings)
        app.add_middleware(OIDCAuthMiddleware)
        logger.info("OIDC bearer-token authentication enabled")
    else:
        app.add_middleware(APIKeyMiddleware)

    # Sanitization middleware (wraps app.state.sanitization set in lifespan)
    from .middleware import SanitizationASGIMiddleware

    app.add_middleware(SanitizationASGIMiddleware)

    # W3C traceparent injection — adds traceparent/tracestate/Server-Timing
    # response headers so the browser can correlate frontend and backend spans.
    # No-op when AGENTIC_TRACING is not set or OTEL SDK is not installed.
    app.add_middleware(TraceparentMiddleware)

    # HTTP metrics middleware — records request duration + counts (no-op when
    # metrics are disabled or OTEL SDK is not installed)
    app.add_middleware(MetricsMiddleware)

    # Global rate limiting via slowapi (outermost — added last)
    configure_rate_limiting(app)

    # Configure CORS (added last → outermost so it wraps the full chain and
    # CORS preflight responses are always returned before any other middleware
    # can short-circuit the request).
    # expose_headers allows the browser to read traceparent/tracestate from
    # CORS responses (same-origin requests can read all headers already).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type", "Accept"],
        expose_headers=["traceparent", "tracestate", "Server-Timing"],
    )

    # E7-3: Map NoProviderConfiguredError to 503 Service Unavailable
    from ..core.errors import NoProviderConfiguredError

    def _no_provider_handler(
        request: Request, exc: NoProviderConfiguredError
    ) -> JSONResponse:
        """Convert NoProviderConfiguredError to HTTP 503 with guidance JSON."""
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc)},
        )

    app.add_exception_handler(NoProviderConfiguredError, _no_provider_handler)

    # Include routes
    app.include_router(health.router, prefix="/api")
    app.include_router(agents.router, prefix="/api")
    app.include_router(models.router, prefix="/api")
    app.include_router(workflows.router, prefix="/api")
    app.include_router(evaluation_routes.router, prefix="/api")
    app.include_router(model_finder.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(websocket.router)

    # Mount Prometheus metrics scrape endpoint (opt-in via AGENTIC_METRICS=1)
    from ..integrations.metrics import get_metrics_app, is_metrics_enabled

    metrics_asgi = get_metrics_app()
    if metrics_asgi is not None:
        app.mount("/metrics", metrics_asgi)
        logger.info("Prometheus metrics endpoint mounted at /metrics")
    elif is_metrics_enabled():
        logger.warning(
            "AGENTIC_METRICS=1 but opentelemetry-exporter-prometheus is not installed. "
            "Install with: pip install 'agentic-workflows-v2[tracing]'"
        )

    # Serve built frontend in production (after API routes so they take priority)
    if UI_DIST_DIR.exists():
        _mount_spa(app)

    return app


# Create global app instance
app = create_app()
