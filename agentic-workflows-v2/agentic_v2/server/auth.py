"""API key authentication middleware for the Agentic server.

Implements a single-key bearer-token gate using Starlette's
``BaseHTTPMiddleware``.

Authentication behavior:
    * When ``AGENTIC_API_KEY`` is set in the environment, every HTTP
      request whose path starts with ``/api/`` (except public prefixes
      like ``/api/health``, ``/docs``, ``/openapi.json``, ``/redoc``)
      must supply the key via ``Authorization: Bearer <key>`` or the
      ``X-API-Key: <key>`` header.  Token comparison uses
      :func:`secrets.compare_digest` to prevent timing side-channels.
    * When the env var is **not** set, the middleware is a no-op and all
      requests are allowed (local development mode).
    * Non-API routes (UI static files, WebSocket upgrade) bypass
      authentication entirely so the React frontend can load without
      credentials.

Per-IP 401 brute-force throttle (``AuthThrottle``):
    After ``AGENTIC_AUTH_LOCKOUT_THRESHOLD`` (default ``5``) consecutive
    failed authentication attempts within ``AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS``
    (default ``60``) seconds, the middleware returns ``429 Too Many Requests``
    with a ``Retry-After`` header for ``AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS``
    (default ``300``) seconds.  State is in-process only (no Redis) and is
    reset on successful authentication.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal
from urllib.parse import urlparse

from fastapi.responses import JSONResponse
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)

from ..models.secrets import SecretProvider, get_secret
from .audit_log import audit_auth_request_event

if TYPE_CHECKING:
    from fastapi import Request, WebSocket

logger = logging.getLogger(__name__)

# Paths that bypass authentication
_PUBLIC_PREFIXES = ("/api/health", "/docs", "/openapi.json", "/redoc")

# Exact paths that are always public (bypass auth AND rate limiting)
_PUBLIC_EXACT_PATHS: frozenset[str] = frozenset({"/metrics"})


# ---------------------------------------------------------------------------
# Per-IP brute-force throttle
# ---------------------------------------------------------------------------


@dataclass
class _ThrottleState:
    """Mutable per-IP failure tracking state.

    Attributes:
        failures: Monotonic timestamps of recent failed auth attempts.
        locked_until: Monotonic timestamp after which the lockout expires,
            or ``None`` when the IP is not currently locked out.
    """

    failures: deque[float] = field(default_factory=deque)
    locked_until: float | None = None


class AuthThrottle:
    """In-process per-IP sliding-window auth failure throttle.

    Tracks failed authentication attempts per client IP address using
    monotonic timestamps.  After *threshold* failures within *window*
    seconds the IP is locked out for *lockout* seconds.

    Env-var overrides (read once at construction time):

    * ``AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS``   — sliding window (default 60)
    * ``AGENTIC_AUTH_LOCKOUT_THRESHOLD``         — max failures before lockout (default 5)
    * ``AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS``  — lockout duration (default 300)

    Args:
        window: Sliding-window size in seconds.
        threshold: Number of failures that triggers a lockout.
        lockout: Duration of the lockout period in seconds.
        clock: Callable returning current monotonic time.  Injectable for
            testing (default: :func:`time.monotonic`).
    """

    def __init__(
        self,
        window: float | None = None,
        threshold: int | None = None,
        lockout: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.window: float = float(
            window
            if window is not None
            else os.environ.get("AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS", "60")
        )
        self.threshold: int = int(
            threshold
            if threshold is not None
            else os.environ.get("AGENTIC_AUTH_LOCKOUT_THRESHOLD", "5")
        )
        self.lockout: float = float(
            lockout
            if lockout is not None
            else os.environ.get("AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS", "300")
        )
        self._clock = clock
        self._state: dict[str, _ThrottleState] = defaultdict(_ThrottleState)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_locked(self, ip: str) -> tuple[bool, float]:
        """Check whether *ip* is currently locked out.

        Args:
            ip: Client IP address string.

        Returns:
            A tuple ``(locked, retry_after_seconds)`` where *locked* is
            ``True`` when the IP must be rejected and *retry_after_seconds*
            is the remaining lockout duration in seconds (0 when not locked).
        """
        now = self._clock()
        self._evict_expired(now)
        state = self._state.get(ip)
        if state is None or state.locked_until is None:
            return False, 0.0
        remaining = state.locked_until - now
        if remaining > 0:
            return True, remaining
        # Lockout expired — clear it
        state.locked_until = None
        state.failures.clear()
        return False, 0.0

    def record_failure(self, ip: str) -> None:
        """Record a failed authentication attempt for *ip*.

        If the failure count within the sliding window reaches
        *threshold*, the IP enters a lockout period.  The failure deque
        is cleared when a lockout starts so the counter does not keep
        growing.
        """
        now = self._clock()
        state = self._state[ip]

        # Drop entries outside the sliding window
        cutoff = now - self.window
        while state.failures and state.failures[0] <= cutoff:
            state.failures.popleft()

        state.failures.append(now)

        if len(state.failures) >= self.threshold:
            state.locked_until = now + self.lockout
            state.failures.clear()
            logger.warning(
                "Auth throttle: IP %s locked out for %.0f seconds after %d failures",
                ip,
                self.lockout,
                self.threshold,
            )

    def record_success(self, ip: str) -> None:
        """Clear failure history for *ip* on successful authentication."""
        self._state.pop(ip, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_expired(self, now: float) -> None:
        """Remove state entries whose lockout and failure window have both expired.

        Called lazily on each request — no background task needed.
        """
        expired_ips = [
            ip
            for ip, state in self._state.items()
            if (state.locked_until is None or state.locked_until <= now)
            and (not state.failures or state.failures[-1] <= now - self.window)
        ]
        for ip in expired_ips:
            del self._state[ip]


def _get_auth_throttle_singleton() -> AuthThrottle:
    """Return the process-level AuthThrottle singleton.

    The singleton is constructed once from env-vars at first call.
    Tests can replace ``app.state.auth_throttle`` per-app without
    touching this module-level singleton.
    """
    global _AUTH_THROTTLE_SINGLETON
    if _AUTH_THROTTLE_SINGLETON is None:
        _AUTH_THROTTLE_SINGLETON = AuthThrottle()
    return _AUTH_THROTTLE_SINGLETON


_AUTH_THROTTLE_SINGLETON: AuthThrottle | None = None
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8010",
    "http://127.0.0.1:8010",
)


@dataclass(frozen=True)
class AuthToken:
    """Resolved authentication token and its transport."""

    value: str
    source: Literal["authorization", "x-api-key", "query"]

    @property
    def is_deprecated_transport(self) -> bool:
        """Query-string tokens are a compatibility fallback only."""
        return self.source == "query"


def _get_api_key(provider: SecretProvider | None = None) -> str | None:
    """Read the API key from the environment on each call.

    This allows key rotation without a full server restart.
    """
    return get_secret("AGENTIC_API_KEY", provider=provider)


def get_allowed_origins(provider: SecretProvider | None = None) -> list[str]:
    """Return configured browser origins for CORS and WebSocket validation."""
    raw = get_secret("AGENTIC_CORS_ORIGINS", provider=provider)
    if raw:
        return [_normalize_origin(item) for item in raw.split(",") if item.strip()]
    return list(_DEFAULT_CORS_ORIGINS)


def is_public_path(path: str) -> bool:
    """Return True when *path* should bypass API key authentication.

    Exact public paths (``/metrics``) are always exempt regardless of prefix.
    Non-API paths (no ``/api/`` prefix) are exempt by default so the React
    SPA, WebSocket upgrades, and the Prometheus scrape endpoint work without
    credentials.
    """
    if path in _PUBLIC_EXACT_PATHS:
        return True
    if not path.startswith("/api/"):
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def extract_http_token(request: Request) -> AuthToken | None:
    """Extract an API key from HTTP headers."""
    return _extract_token_from_headers(request.headers)


def extract_websocket_token(websocket: WebSocket) -> AuthToken | None:
    """Extract an API key from WebSocket headers."""
    return _extract_token_from_headers(websocket.headers)


def websocket_uses_query_token(websocket: WebSocket) -> bool:
    """Return True when a WebSocket handshake still carries a query token."""
    return bool((websocket.query_params.get("token") or "").strip())


def is_token_authorized(token: str | None, api_key: str | None) -> bool:
    """Compare *token* with the configured API key using constant time."""
    if api_key is None:
        return True
    return token is not None and secrets.compare_digest(token, api_key)


def is_websocket_origin_allowed(
    websocket: WebSocket, allowed_origins: list[str] | None = None
) -> bool:
    """Validate browser origins for WebSocket handshakes.

    Non-browser clients often omit the Origin header; those requests are
    allowed. Browser requests must either come from an explicitly
    allowed origin, use a wildcard allowlist, or match the current Host
    header exactly.
    """
    origin = _normalize_origin(websocket.headers.get("origin"))
    if origin is None:
        return True

    host = websocket.headers.get("host", "")
    if _origin_matches_host(origin, host):
        return True

    # Allow any localhost/127.0.0.1 origin — Vite dev server starts on dynamic
    # ports (5173, 5174, …) so we can't enumerate every possible port.
    if _is_localhost_origin(origin):
        return True

    for allowed in allowed_origins or get_allowed_origins():
        if allowed == "*" or _normalize_origin(allowed) == origin:
            return True
    return False


def build_auth_error_response() -> JSONResponse:
    """Return the standard API auth failure payload."""
    return JSONResponse(
        status_code=401,
        content={"detail": "Invalid or missing API key"},
    )


def _build_throttle_response(retry_after_seconds: float) -> JSONResponse:
    """Return a ``429 Too Many Requests`` response for locked-out IPs.

    Args:
        retry_after_seconds: Number of seconds the client must wait before retrying.

    Returns:
        A JSON response with ``Retry-After`` header set.
    """
    retry_int = max(1, int(retry_after_seconds))
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many failed authentication attempts. Please retry later.",
            "retry_after": retry_int,
        },
        headers={"Retry-After": str(retry_int)},
    )


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces bearer-token authentication on ``/api/``
    routes, with an integrated per-IP brute-force lockout.

    When ``AGENTIC_API_KEY`` is not set, all requests pass through unchanged.
    Otherwise, requests to protected paths must include a valid token via
    ``Authorization: Bearer <key>`` or ``X-API-Key: <key>``.  Invalid or
    missing tokens receive a ``401`` JSON response.

    After ``AGENTIC_AUTH_LOCKOUT_THRESHOLD`` (default ``5``) failures within
    ``AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS`` (default ``60``) seconds from the
    same IP, subsequent requests return ``429 Too Many Requests`` with a
    ``Retry-After`` header for ``AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS``
    (default ``300``) seconds.  Successful authentication resets the counter.

    The throttle state is stored on ``app.state.auth_throttle`` (an
    :class:`AuthThrottle` instance) so tests can inject a fresh instance
    per test app.  Falls back to a process-level singleton when not set.

    Attributes:
        Inherits from ``BaseHTTPMiddleware``; no additional instance state.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        api_key = _get_api_key()
        if api_key is None:
            return await call_next(request)

        path = request.url.path

        # Allow public endpoints and non-API routes (UI static files)
        if is_public_path(path):
            return await call_next(request)

        client_host = request.client.host if request.client else "unknown"

        # Resolve the throttle — prefer app.state.auth_throttle so tests can inject
        throttle: AuthThrottle
        try:
            throttle = request.app.state.auth_throttle
        except AttributeError:
            throttle = _get_auth_throttle_singleton()

        # Reject locked-out IPs before even checking credentials
        is_locked, retry_after = throttle.is_locked(client_host)
        if is_locked:
            logger.warning(
                "Auth throttle: rejecting locked IP %s (retry after %.0fs)",
                client_host,
                retry_after,
            )
            await audit_auth_request_event(
                request,
                "auth.throttled",
                outcome="denied",
                metadata={
                    "path": path,
                    "status_code": 429,
                    "retry_after": int(max(1, retry_after)),
                },
            )
            return _build_throttle_response(retry_after)

        # Check for API key in headers
        token = extract_http_token(request)
        if token is None or not is_token_authorized(token.value, api_key):
            logger.warning("Authentication failed for %s from %s", path, client_host)
            throttle.record_failure(client_host)

            # Re-check immediately: this failure may have triggered a lockout
            is_now_locked, retry_after = throttle.is_locked(client_host)
            if is_now_locked:
                await audit_auth_request_event(
                    request,
                    "auth.throttled",
                    outcome="denied",
                    metadata={
                        "path": path,
                        "token_source": (
                            token.source if token is not None else "missing"
                        ),
                        "status_code": 429,
                        "retry_after": int(max(1, retry_after)),
                    },
                )
                return _build_throttle_response(retry_after)

            await audit_auth_request_event(
                request,
                "auth.failed",
                outcome="failure",
                metadata={
                    "path": path,
                    "token_source": token.source if token is not None else "missing",
                    "status_code": 401,
                },
            )
            return build_auth_error_response()

        # Successful auth — clear any failure history for this IP
        throttle.record_success(client_host)
        await audit_auth_request_event(
            request,
            "auth.succeeded",
            outcome="success",
            metadata={
                "path": path,
                "token_source": token.source,
                "status_code": 200,
            },
        )
        return await call_next(request)


def _extract_token(request: Request) -> str | None:
    """Backward-compatible token extraction helper for tests."""
    token = extract_http_token(request)
    return token.value if token is not None else None


def _extract_token_from_headers(headers) -> AuthToken | None:
    """Extract API key from Authorization or X-API-Key header."""
    # Try Authorization: Bearer <key>
    auth_header = headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return AuthToken(value=token, source="authorization")

    # Try X-API-Key header
    api_key_header = headers.get("x-api-key")
    if api_key_header:
        token = api_key_header.strip()
        if token:
            return AuthToken(value=token, source="x-api-key")

    return None


def _normalize_origin(origin: str | None) -> str | None:
    if origin is None:
        return None
    normalized = origin.strip().rstrip("/")
    return normalized or None


def _origin_matches_host(origin: str, host: str) -> bool:
    """Return True when *origin* targets the same host as the request."""
    parsed_origin = urlparse(origin)
    if not parsed_origin.hostname:
        return False

    origin_scheme = parsed_origin.scheme or "http"
    origin_host = parsed_origin.hostname.lower()
    origin_port = parsed_origin.port or _default_port(origin_scheme)

    parsed_host = urlparse(f"//{host}")
    if not parsed_host.hostname:
        return False

    host_name = parsed_host.hostname.lower()
    host_port = parsed_host.port or _default_port(origin_scheme)
    return origin_host == host_name and origin_port == host_port


def _is_localhost_origin(origin: str) -> bool:
    """Return True when *origin* is any localhost or loopback address."""
    parsed = urlparse(origin)
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _default_port(scheme: str) -> int | None:
    if scheme in {"http", "ws"}:
        return 80
    if scheme in {"https", "wss"}:
        return 443
    return None
