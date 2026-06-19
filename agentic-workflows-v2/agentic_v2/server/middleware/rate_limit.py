"""Global rate-limiting setup using slowapi.

Provides the Limiter instance and handler used by :func:`_configure_rate_limiting`
in :mod:`agentic_v2.server.app`.

Environment variables:
    AGENTIC_RATE_LIMIT_DISABLED: Set to ``"1"`` to disable rate limiting (for tests).
    AGENTIC_RATE_LIMIT_DEFAULT: Override the per-IP limit string, e.g. ``"100/minute"``.
    AGENTIC_DISABLE_RATE_LIMITING: Set to ``"1"`` to explicitly accept no rate limiting
        when slowapi is not installed (see :func:`_enforce_rate_limiting_available`).
"""

from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse

from ..auth import is_public_path

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

    def _rate_limit_exceeded_handler(
        _request: Request, exc: RateLimitExceeded
    ) -> JSONResponse:
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


def configure_rate_limiting(app: "FastAPI") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Register slowapi global rate-limiting middleware when available.

    Logs an explanatory message in each of the three states: enabled,
    explicitly disabled via env var, or unavailable (slowapi not installed).
    """
    import logging


    logger = logging.getLogger(__name__)

    if _limiter is not None and _SLOWAPI_AVAILABLE:
        app.state.limiter = _limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)
        logger.info("Rate limiting enabled: %s per IP", _RATE_LIMIT_DEFAULT)
    elif _RATE_LIMIT_DISABLED:
        logger.info("Rate limiting disabled (AGENTIC_RATE_LIMIT_DISABLED=1)")
    else:
        logger.warning("slowapi not installed — rate limiting is inactive")
