"""FastAPI lifespan context manager and its startup helper functions.

Provides :func:`lifespan` (the async context manager passed to ``FastAPI(lifespan=...)``)
and all startup/shutdown helpers it delegates to.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..adapters import get_registry
from ..core.errors import ConfigurationError
from ..integrations.metrics import is_metrics_enabled, shutdown_metrics
from ..integrations.otel import is_tracing_enabled, shutdown_tracing
from ..models import SmartModelRouter, get_smart_router, set_smart_router
from ..settings import Settings, get_settings
from . import websocket
from .audit_log import AuditLogger, NullAuditStore, build_audit_logger
from .auth import _get_api_key
from .middleware.rate_limit import (
    _DISABLE_RATE_LIMITING_ENV,
    _RATE_LIMIT_DISABLED,
    _SLOWAPI_AVAILABLE,
)

logger = logging.getLogger(__name__)


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

    AGENTIC_DEFAULT_ADAPTER controls which engine the server treats as
    its selected engine at startup. Named YAML workflow requests default
    to "langchain" during the migration window because
    WorkflowRunRequest.adapter defaults to "langchain". Set to "native"
    to validate and run the dependency-light DAG/Pipeline adapter
    instead.
    """
    _selected_adapter = (
        os.environ.get("AGENTIC_DEFAULT_ADAPTER", "langchain").strip().lower()
    )
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

    NoProviderConfiguredError is non-fatal at startup — the server
    starts in a degraded state; the error is surfaced per-request via
    the 503 handler.
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
