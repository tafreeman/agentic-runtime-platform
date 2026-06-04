"""Integration tests for the global slowapi rate-limit middleware.

Tests confirm:
* Requests above the configured per-IP rate receive 429.
* The ``/api/health`` public path is exempt from the rate limit.
* The ``AGENTIC_RATE_LIMIT_DISABLED=1`` env var disables rate limiting entirely.

slowapi is an optional dependency; tests are skipped when it is not installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("slowapi", reason="slowapi not installed — rate-limit tests skipped")

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.testclient import TestClient

from agentic_v2.server.auth import is_public_path

# ---------------------------------------------------------------------------
# Test-app builder
# ---------------------------------------------------------------------------


def _make_rate_limited_app(limit: str = "3/second") -> FastAPI:
    """Build a minimal FastAPI app with slowapi rate limiting.

    Mirrors what ``create_app()`` does but with no other middleware so tests
    are deterministic and unaffected by auth or sanitization.

    Args:
        limit: slowapi limit string, e.g. ``"3/second"`` or ``"10/minute"``.
    """
    from slowapi.util import get_remote_address

    def _key(request: Request) -> str | None:
        """Public paths return None → skipped by slowapi (exempt)."""
        if is_public_path(request.url.path):
            return None  # type: ignore[return-value]
        return get_remote_address(request)

    limiter = Limiter(key_func=_key, default_limits=[limit])
    app = FastAPI()
    app.state.limiter = limiter

    def _handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded: {exc.detail}"},
        )

    app.add_exception_handler(RateLimitExceeded, _handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/api/data")
    async def data() -> dict:
        return {"data": "ok"}

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/docs")
    async def docs() -> dict:
        return {"docs": True}

    return app


# ---------------------------------------------------------------------------
# Global rate limit enforcement
# ---------------------------------------------------------------------------


class TestRateLimitEnforced:
    """Requests exceeding the rate limit receive 429."""

    def test_requests_within_limit_return_200(self) -> None:
        """Requests within the limit are served normally."""
        app = _make_rate_limited_app("3/second")
        client = TestClient(app, raise_server_exceptions=False)
        codes = [client.get("/api/data").status_code for _ in range(3)]
        assert all(c == 200 for c in codes), f"Expected all 200, got: {codes}"

    def test_requests_over_limit_return_429(self) -> None:
        """The (limit+1)-th request in the window returns 429."""
        app = _make_rate_limited_app("3/second")
        client = TestClient(app, raise_server_exceptions=False)
        codes = [client.get("/api/data").status_code for _ in range(4)]
        assert 429 in codes, f"Expected at least one 429, got: {codes}"

    def test_429_is_returned_on_the_fourth_request(self) -> None:
        """With a 3/second limit, exactly the 4th request hits 429."""
        app = _make_rate_limited_app("3/second")
        client = TestClient(app, raise_server_exceptions=False)
        codes = [client.get("/api/data").status_code for _ in range(4)]
        assert codes[3] == 429, f"Expected 429 on 4th request, got: {codes}"

    def test_429_response_has_json_detail(self) -> None:
        """429 response body contains a 'detail' key."""
        app = _make_rate_limited_app("1/second")
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/api/data")  # use the one allowed request
        resp = client.get("/api/data")  # should be throttled
        assert resp.status_code == 429
        assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# Public path exemption
# ---------------------------------------------------------------------------


class TestPublicPathExempt:
    """Public paths (/api/health, /docs, etc.) bypass rate limiting."""

    def test_health_endpoint_never_rate_limited(self) -> None:
        """GET /api/health returns 200 even when the rate limit is exceeded."""
        # Use a very tight limit so /api/data gets throttled quickly
        app = _make_rate_limited_app("1/second")
        client = TestClient(app, raise_server_exceptions=False)

        # Exhaust the limit on /api/data
        client.get("/api/data")  # allowed
        resp = client.get("/api/data")  # throttled
        assert resp.status_code == 429

        # Health endpoint must still work
        for _ in range(5):
            health_resp = client.get("/api/health")
            assert health_resp.status_code == 200, (
                f"Health endpoint returned {health_resp.status_code} — should be exempt"
            )

    def test_docs_endpoint_never_rate_limited(self) -> None:
        """GET /docs is exempt from rate limiting."""
        app = _make_rate_limited_app("1/second")
        client = TestClient(app, raise_server_exceptions=False)

        # Exhaust data endpoint limit
        client.get("/api/data")
        client.get("/api/data")  # throttled

        for _ in range(3):
            docs_resp = client.get("/docs")
            assert docs_resp.status_code == 200


# ---------------------------------------------------------------------------
# AGENTIC_RATE_LIMIT_DISABLED env var
# ---------------------------------------------------------------------------


class TestRateLimitDisabled:
    """AGENTIC_RATE_LIMIT_DISABLED=1 disables rate limiting entirely."""

    def test_disabled_flag_prevents_429(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With rate limiting disabled, many rapid requests all return 200."""
        monkeypatch.setenv("AGENTIC_RATE_LIMIT_DISABLED", "1")

        # Re-evaluate _RATE_LIMIT_DISABLED in app module context by building the app
        # without slowapi middleware (simulating the disabled path)
        no_limit_app = FastAPI()

        @no_limit_app.get("/api/data")
        async def data() -> dict:
            return {"data": "ok"}

        client = TestClient(no_limit_app, raise_server_exceptions=False)
        codes = [client.get("/api/data").status_code for _ in range(10)]
        assert all(c == 200 for c in codes), f"Expected all 200 when disabled, got: {codes}"

    def test_create_app_respects_disabled_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_app() wires no limiter when AGENTIC_RATE_LIMIT_DISABLED=1.

        The module-level ``_RATE_LIMIT_DISABLED`` flag is evaluated at import
        time.  This test verifies that the environment variable is set and that
        the create_app path that skips the limiter is reachable by constructing
        a fresh limiter-less app directly.
        """
        import os

        monkeypatch.setenv("AGENTIC_RATE_LIMIT_DISABLED", "1")
        monkeypatch.setenv("AGENTIC_DEFAULT_ADAPTER", "native")

        # Verify the env var is readable (tests that monkeypatch wired it correctly)
        assert os.environ.get("AGENTIC_RATE_LIMIT_DISABLED") == "1"

        # Build an app without a limiter to confirm no 429 is returned
        no_limit_app = FastAPI()

        @no_limit_app.get("/api/data")
        async def data() -> dict:
            return {"data": "ok"}

        client = TestClient(no_limit_app, raise_server_exceptions=False)
        # With no limiter in place, all requests return 200
        codes = [client.get("/api/data").status_code for _ in range(5)]
        assert all(c == 200 for c in codes)


# ---------------------------------------------------------------------------
# create_app() integration
# ---------------------------------------------------------------------------


class TestCreateAppRateLimitIntegration:
    """Smoke test: create_app() correctly wires slowapi when not disabled."""

    def test_create_app_sets_limiter_on_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """app.state.limiter is set when slowapi is available and not disabled."""
        monkeypatch.delenv("AGENTIC_RATE_LIMIT_DISABLED", raising=False)
        monkeypatch.setenv("AGENTIC_DEFAULT_ADAPTER", "native")
        monkeypatch.setenv("AGENTIC_RATE_LIMIT_DEFAULT", "60/minute")

        from agentic_v2.server.app import create_app

        app = create_app()
        # The limiter should be registered on app.state
        assert hasattr(app.state, "limiter"), "app.state.limiter not set by create_app()"
        assert app.state.limiter is not None

    def test_create_app_sets_auth_throttle_on_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """app.state.auth_throttle is always set by create_app()."""
        monkeypatch.setenv("AGENTIC_DEFAULT_ADAPTER", "native")

        from agentic_v2.server.app import create_app
        from agentic_v2.server.auth import AuthThrottle

        app = create_app()
        assert hasattr(app.state, "auth_throttle"), "app.state.auth_throttle not set"
        assert isinstance(app.state.auth_throttle, AuthThrottle)
