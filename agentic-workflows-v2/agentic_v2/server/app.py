"""FastAPI application factory for the Agentic Workflows V2 server.

Provides :func:`create_app`, which assembles the FastAPI instance with:

* **CORS middleware** -- origins configurable via ``AGENTIC_CORS_ORIGINS`` env var
  (comma-separated), defaulting to common localhost development ports.
* **Authentication** -- legacy API-key auth via ``AGENTIC_API_KEY`` or
  OIDC JWT bearer-token auth via ``AGENTIC_OIDC_ENABLED=1``.
* **Global rate limiting** -- slowapi-based per-IP limit, configurable via
  ``AGENTIC_RATE_LIMIT_DEFAULT`` env var (default ``"60/minute"``).  Set
  ``AGENTIC_RATE_LIMIT_DISABLED=1`` to disable entirely (for tests).
  Public paths (``/api/health``, ``/docs``, ``/openapi.json``, ``/redoc``) are
  exempt from the rate limit.
* **Route registration** -- health, agents, workflows (under ``/api/``), plus
  the WebSocket streaming endpoint at ``/ws/execution/{run_id}``.
* **SPA static serving** -- when the built React frontend exists under
  ``ui/dist/``, static assets are served at ``/assets/`` and all remaining
  paths fall through to ``index.html`` (client-side routing).
* **Lifespan handler** -- on startup, probes available LLM providers and
  updates tier defaults for both the LangGraph and native DAG engines;
  on shutdown, flushes OpenTelemetry spans.

A module-level ``app`` instance is created for use by ``uvicorn`` or the
``agentic serve`` CLI command.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..adapters import get_registry
from ..core.errors import ConfigurationError
from ..integrations.metrics import get_metrics_app, is_metrics_enabled, shutdown_metrics
from ..integrations.otel import is_tracing_enabled, shutdown_tracing
from ..logging_config import configure_logging
from ..models import (
    SmartModelRouter,
    get_smart_router,
    set_smart_router,
)
from ..settings import Settings, get_settings
from . import websocket
from .audit_log import AuditLogger, NullAuditStore, build_audit_logger
from .auth import (
    APIKeyMiddleware,
    AuthThrottle,
    _get_api_key,
    get_allowed_origins,
    is_public_path,
)
from .auth_oidc import OIDCAuthMiddleware, validate_oidc_settings
from .middleware.metrics import MetricsMiddleware
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

# Configure logging — JSON when LOG_FORMAT=json, text otherwise.
configure_logging(log_format=get_settings().log_format)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global rate limiting (slowapi)
# ---------------------------------------------------------------------------
# Set AGENTIC_RATE_LIMIT_DISABLED=1 to skip rate limiting entirely (tests).
# Set AGENTIC_RATE_LIMIT_DEFAULT to override the per-IP limit string, e.g.
# "100/minute" or "10/second".  Format: "<count>/<period>" where period is
# one of second, minute, hour, day.
_RATE_LIMIT_DISABLED: bool = os.environ.get("AGENTIC_RATE_LIMIT_DISABLED", "0") == "1"
_RATE_LIMIT_DEFAULT: str = os.environ.get("AGENTIC_RATE_LIMIT_DEFAULT", "60/minute")

# Env var name that lets an operator explicitly accept running with no rate
# limiting when slowapi is not installed.  Read at startup (not import) so the
# acknowledgement can be toggled per-process and exercised in tests.
_DISABLE_RATE_LIMITING_ENV: str = "AGENTIC_DISABLE_RATE_LIMITING"


try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.util import get_remote_address

    def _public_exempt_key(request: Request) -> str | None:
        """Key function: exempt public paths, use remote IP for others.

        Returning ``None`` instructs slowapi to skip rate-limit enforcement for
        that request, which effectively exempts ``/api/health``, ``/docs``,
        ``/openapi.json``, and ``/redoc`` from the global default limit.
        """
        if is_public_path(request.url.path):
            return None  # type: ignore[return-value]  # None → skip limit
        return get_remote_address(request)

    _limiter: Limiter | None = (
        None
        if _RATE_LIMIT_DISABLED
        else Limiter(key_func=_public_exempt_key, default_limits=[_RATE_LIMIT_DEFAULT])
    )

    def _rate_limit_exceeded_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
        """Convert a slowapi ``RateLimitExceeded`` exception to a 429 JSON response."""
        retry_after = getattr(exc, "retry_after", None)
        headers = {}
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded: {exc.detail}"},
            headers=headers,
        )

    _SLOWAPI_AVAILABLE = True
except ImportError:
    _limiter = None
    _SLOWAPI_AVAILABLE = False
    SlowAPIMiddleware = None  # type: ignore[assignment,misc]
    RateLimitExceeded = None  # type: ignore[assignment,misc]

    def _rate_limit_exceeded_handler(_request: Request, _exc: Exception) -> JSONResponse:  # type: ignore[misc]
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


# Built frontend assets directory
UI_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "ui" / "dist"
UI_DIST_DIR_RESOLVED = UI_DIST_DIR.resolve()


def _initialize_sanitization_state(app: FastAPI) -> Exception | None:
    """Populate ``app.state.sanitization`` once and remember any init failure.

    Test suites often instantiate ``TestClient(app)`` without entering its
    context manager, which means the FastAPI lifespan hook never runs. Eagerly
    initializing the sanitizer here keeps request-time behavior consistent
    across both plain ``TestClient(app)`` usage and full startup lifecycles,
    while still letting lifespan fail closed if initialization actually broke.
    """
    if hasattr(app.state, "sanitization"):
        prior_error = getattr(app.state, "sanitization_init_error", None)
        # Narrow the untyped getattr result so the return type is provably
        # ``Exception | None`` (keeps the exception-chain cause valid; python:S5707).
        return prior_error if isinstance(prior_error, BaseException) else None

    try:
        from ..middleware.sanitization import SanitizationMiddleware

        app.state.sanitization = SanitizationMiddleware.default(dry_run=False)
        app.state.sanitization_init_error = None
        logger.info("Sanitization middleware initialized (dry_run=False)")
        return None
    except Exception as exc:
        logger.exception("Failed to initialize sanitization middleware")
        app.state.sanitization = None
        app.state.sanitization_init_error = exc
        return exc


def _validate_selected_adapter() -> None:
    """Eagerly validate the configured startup adapter, aborting on misconfig.

    AGENTIC_DEFAULT_ADAPTER controls which engine the server treats as its
    selected engine at startup. Named YAML workflow requests default to
    "langchain" during the migration window because WorkflowRunRequest.adapter
    defaults to "langchain". Set to "native" to validate and run the
    dependency-light DAG/Pipeline adapter instead.
    """
    _selected_adapter = os.environ.get("AGENTIC_DEFAULT_ADAPTER", "langchain").strip().lower()
    logger.info("Default adapter: %s", _selected_adapter)
    try:
        get_registry().validate_selected(_selected_adapter)
    except ConfigurationError:
        logger.critical(
            "Server startup aborted: LangChain engine is selected "
            "(AGENTIC_DEFAULT_ADAPTER=%r) but extras are not installed. "
            "Fix with: pip install -e '.[langchain]'  "
            "or set AGENTIC_DEFAULT_ADAPTER=native to use the native engine.",
            _selected_adapter,
        )
        raise


def _enforce_rate_limiting_available() -> None:
    """Fail fast at startup when rate limiting is silently absent.

    When ``slowapi`` is not installed the server would otherwise come up with no
    per-IP rate limiting and no error, leaving unauthenticated LLM-budget
    exhaustion wide open. Refuse to start unless the operator has explicitly
    accepted that risk via ``AGENTIC_DISABLE_RATE_LIMITING=1`` (or the existing
    ``AGENTIC_RATE_LIMIT_DISABLED=1`` test override).

    Raises:
        RuntimeError: ``slowapi`` is unavailable and no override env var is set.
    """
    if _SLOWAPI_AVAILABLE:
        return

    explicitly_disabled = (
        os.environ.get(_DISABLE_RATE_LIMITING_ENV, "0") == "1" or _RATE_LIMIT_DISABLED
    )
    if explicitly_disabled:
        logger.warning(
            "slowapi is not installed — rate limiting is inactive "
            "(explicitly accepted via %s=1)",
            _DISABLE_RATE_LIMITING_ENV,
        )
        return

    raise RuntimeError(
        "slowapi is required for rate limiting; install it or set "
        f"{_DISABLE_RATE_LIMITING_ENV}=1 to explicitly disable."
    )


def _probe_llm_providers() -> None:
    """Probe available LLM providers and update tier defaults for both engines.

    NoProviderConfiguredError is non-fatal at startup — the server starts in a
    degraded state; the error is surfaced per-request via the 503 handler.
    """
    try:
        from ..langchain.models import probe_and_update_tier_defaults

        summary = probe_and_update_tier_defaults()
        logger.info(
            "LLM providers: available=%s, unavailable=%s",
            summary["available_providers"],
            summary["unavailable_providers"],
        )
    except ImportError:
        logger.warning("LangChain extras not installed — skipping LLM provider probe")
    except Exception as _probe_exc:  # broad catch is intentional at startup
        from ..core.errors import NoProviderConfiguredError

        if isinstance(_probe_exc, NoProviderConfiguredError):
            logger.warning(
                "No LLM provider configured — server starts in degraded mode. "
                "Set a provider API key or AGENTIC_NO_LLM=1. See docs/NO_LLM_MODE.md"
            )
        else:
            logger.warning("LLM provider probe failed (non-fatal): %s", _probe_exc)


async def _install_smart_router(settings: Settings) -> SmartModelRouter:
    """Install the process-wide :class:`SmartModelRouter`, Redis-backed if configured.

    When ``settings.redis_url`` is set, build a router whose circuit-breaker
    state is shared across workers via a :class:`RedisCircuitBreakerStore`
    (``SmartModelRouter.create_with_redis``) and install it as the global
    singleton consumed by ``get_smart_router()``. This is what activates the
    Redis CAS persistence path (``redis_state.py``) on a real app run.

    Graceful degradation (never crashes startup):
    - ``redis_url`` unset → keep the existing in-process router.
    - ``redis_url`` set but the Redis connection fails, the ``redis`` package
      is not installed, or construction raises → log a warning and fall back
      to the in-process router.

    Args:
        settings: Resolved application settings.

    Returns:
        The active router (Redis-backed when the connection succeeded,
        otherwise the in-process router). Callers should keep a reference so
        the lifespan can ``aclose()`` it on shutdown to drain background CAS
        save tasks.
    """
    if not settings.redis_url:
        # No Redis configured — in-process router with local file persistence.
        return get_smart_router()

    try:
        router = await SmartModelRouter.create_with_redis(
            redis_url=settings.redis_url,
            prefix=settings.redis_circuit_breaker_prefix,
            ttl_seconds=settings.redis_circuit_breaker_ttl,
        )
    except Exception as exc:  # graceful degradation — never crash startup
        logger.warning(
            "SmartModelRouter Redis init failed (%s); "
            "falling back to in-process circuit-breaker state",
            exc,
        )
        return get_smart_router()

    store = router._redis_store
    if store is not None and store.is_connected:
        set_smart_router(router)
        logger.info(
            "SmartModelRouter using Redis-backed circuit-breaker state: %s",
            settings.redis_url,
        )
        return router

    # create_with_redis returned a router whose store could not connect (the
    # factory degrades internally rather than raising). Drain its empty task
    # set for tidiness and keep the in-process router as the installed one.
    logger.warning(
        "REDIS_URL is set (%s) but the Redis circuit-breaker store is not "
        "connected; falling back to in-process state",
        settings.redis_url,
    )
    await router.aclose()
    return get_smart_router()


def _enforce_sanitization_init(app: FastAPI, init_error: Exception) -> None:
    """Apply fail-open/fail-closed policy after a sanitization init failure.

    When ``AGENTIC_SANITIZER_FAIL_OPEN=1`` the server starts with sanitization
    disabled; otherwise a ``RuntimeError`` is raised to fail closed.
    """
    from .middleware import _fail_open_enabled

    if _fail_open_enabled():
        logger.critical(
            "AGENTIC_SANITIZER_FAIL_OPEN=1 — starting WITHOUT sanitization. "
            "Prompt injection and secret redaction are DISABLED. "
            "Do not use this setting in production."
        )
        app.state.sanitization = None
        return

    # Bind to a BaseException|None-typed local so the exception-chain
    # cause is always provably valid (python:S5707).
    cause: BaseException | None = (
        init_error if isinstance(init_error, BaseException) else None
    )
    raise RuntimeError(
        "Sanitization middleware failed to initialize. "
        "Set AGENTIC_SANITIZER_FAIL_OPEN=1 to bypass (insecure — not for production)."
    ) from cause


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage server startup and shutdown lifecycle.

    Startup:
        Probes all configured LLM providers (GitHub Models, OpenAI,
        Anthropic, Gemini, Ollama) and updates the tier-to-model
        default mappings for both the LangGraph and native engines.

    Shutdown:
        Flushes and shuts down OpenTelemetry tracing and metrics if enabled.

    Yields:
        Control to the FastAPI event loop for the duration of the
        server's lifetime.
    """
    logger.info("Starting Agentic Workflows V2 Server")

    settings = get_settings()

    # Warn if no HTTP API authentication mechanism is configured.
    if not _get_api_key() and not settings.agentic_oidc_enabled:
        logger.warning(
            "AGENTIC_API_KEY is not set — all API routes are publicly accessible. "
            "Set this env var or enable AGENTIC_OIDC_ENABLED to require authentication."
        )

    # Eagerly validate the selected adapter at boot so misconfiguration is
    # surfaced with a clear error instead of an obscure mid-workflow traceback.
    _validate_selected_adapter()

    # Refuse to start with rate limiting silently absent (slowapi missing and no
    # explicit opt-out), which would expose unauthenticated LLM-budget drain.
    _enforce_rate_limiting_available()

    _probe_llm_providers()

    # Initialize sanitization middleware.
    # Enforcement mode: dry_run=False blocks/redacts unsafe content.
    init_error = _initialize_sanitization_state(app)
    if init_error is not None:
        _enforce_sanitization_init(app, init_error)

    if is_tracing_enabled():
        logger.info("OpenTelemetry tracing is enabled")
    if is_metrics_enabled():
        logger.info("OpenTelemetry metrics (Prometheus scrape) is enabled at /metrics")

    # Install the SmartModelRouter — Redis-backed (shared circuit-breaker state
    # across workers) when REDIS_URL is set, otherwise the in-process router.
    # Graceful: a missing/unreachable Redis falls back without crashing startup.
    # Stored on app.state so the shutdown block can drain its background CAS
    # save tasks via aclose().
    app.state.smart_router = await _install_smart_router(settings)

    # Initialize the durable WebSocket replay store (Redis / SQLite / in-memory).
    # Must happen after settings are loaded so build_replay_store() can read
    # REDIS_URL and replay_store_backend from the resolved settings object.
    await websocket.manager.initialize_store()

    # Initialize tamper-evident audit logging after settings resolve.  The
    # request helpers are no-op-safe, so a startup failure keeps the server up
    # with audit disabled rather than breaking local development.
    try:
        app.state.audit_logger = await build_audit_logger(get_settings())
    except Exception as exc:
        logger.exception("Audit logger initialization failed: %s", exc)
        app.state.audit_logger = AuditLogger(NullAuditStore(), enabled=False)

    yield
    logger.info("Shutting down Agentic Workflows V2 Server")
    audit_logger = getattr(app.state, "audit_logger", None)
    if isinstance(audit_logger, AuditLogger):
        await audit_logger.close()
    # Drain the router's fire-and-forget Redis CAS save tasks before tearing
    # down tracing, so no circuit-breaker state write is silently abandoned.
    smart_router = getattr(app.state, "smart_router", None)
    if isinstance(smart_router, SmartModelRouter):
        await smart_router.aclose()
    shutdown_tracing()
    shutdown_metrics()


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
    _configure_rate_limiting(app)

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

    def _no_provider_handler(request: Request, exc: NoProviderConfiguredError) -> JSONResponse:
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


def _configure_rate_limiting(app: FastAPI) -> None:
    """Register slowapi global rate-limiting middleware when available.

    Logs an explanatory message in each of the three states: enabled,
    explicitly disabled via env var, or unavailable (slowapi not installed).
    """
    if _limiter is not None and _SLOWAPI_AVAILABLE:
        app.state.limiter = _limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)
        logger.info("Rate limiting enabled: %s per IP", _RATE_LIMIT_DEFAULT)
    elif _RATE_LIMIT_DISABLED:
        logger.info("Rate limiting disabled (AGENTIC_RATE_LIMIT_DISABLED=1)")
    else:
        logger.warning("slowapi not installed — rate limiting is inactive")


def _mount_spa(app: FastAPI) -> None:
    """Mount static assets and the SPA fallback route for the built React UI."""
    # Serve static assets (JS, CSS, etc.)
    app.mount(
        "/assets", StaticFiles(directory=str(UI_DIST_DIR / "assets")), name="assets"
    )

    # SPA fallback: serve index.html for all non-API, non-asset routes
    index_html = UI_DIST_DIR / "index.html"

    @app.get("/{path:path}")
    async def spa_fallback(request: Request, path: str):
        # Serve real files from dist/, but prevent directory traversal. Resolve
        # the candidate and confirm it stays within the dist tree using
        # os.path.commonpath — a sanitizer pattern CodeQL recognizes for
        # py/path-injection (the prior `in .parents` check was equivalent but
        # not recognized as a barrier).
        if path:
            base = os.path.realpath(UI_DIST_DIR_RESOLVED)
            candidate = os.path.realpath(os.path.join(base, path))
            if (
                os.path.commonpath([base, candidate]) == base
                and os.path.isfile(candidate)
            ):
                return FileResponse(candidate)
        return FileResponse(index_html)

    logger.info("Serving UI from %s", UI_DIST_DIR)


# Create global app instance
app = create_app()
