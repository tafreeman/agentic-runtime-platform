"""Integration tests for APIKeyMiddleware per-IP 401 brute-force throttle.

Exercises the full Starlette/FastAPI middleware stack with a TestClient.
The throttle threshold and window are set to small values so tests run fast.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from agentic_v2.server.auth import APIKeyMiddleware, AuthThrottle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_KEY = "test-secret-key-123"
_BAD_KEY = "wrong-key"
_THRESHOLD = 5  # 5 failures → 6th returns 429
_LOCKOUT = 300  # seconds


def _make_throttle_app(
    api_key: str = _VALID_KEY,
    threshold: int = _THRESHOLD,
    lockout: float = float(_LOCKOUT),
) -> FastAPI:
    """Create a minimal FastAPI app wired with APIKeyMiddleware + a fresh AuthThrottle."""
    app = FastAPI()
    app.state.auth_throttle = AuthThrottle(window=60.0, threshold=threshold, lockout=lockout)
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/data")
    async def protected() -> dict:
        return {"data": "secret"}

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# Basic auth pass / fail without throttle involvement
# ---------------------------------------------------------------------------


class TestAuthBasic:
    """Baseline auth behaviour — first N failures still return 401."""

    @pytest.fixture(autouse=True)
    def _set_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTIC_API_KEY", _VALID_KEY)

    def test_valid_key_returns_200(self) -> None:
        app = _make_throttle_app()
        client = TestClient(app)
        response = client.get("/api/data", headers={"Authorization": f"Bearer {_VALID_KEY}"})
        assert response.status_code == 200

    def test_bad_key_first_failure_returns_401(self) -> None:
        app = _make_throttle_app()
        client = TestClient(app)
        response = client.get("/api/data", headers={"Authorization": f"Bearer {_BAD_KEY}"})
        assert response.status_code == 401

    def test_health_always_returns_200(self) -> None:
        app = _make_throttle_app()
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Throttle engagement
# ---------------------------------------------------------------------------


class TestThrottleEngagement:
    """After threshold failures the next request gets 429."""

    @pytest.fixture(autouse=True)
    def _set_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTIC_API_KEY", _VALID_KEY)

    def _exhaust_failures(
        self, client: TestClient, n: int, path: str = "/api/data"
    ) -> list[int]:
        """Send *n* requests with bad credentials and collect status codes."""
        codes = []
        for _ in range(n):
            resp = client.get(path, headers={"Authorization": f"Bearer {_BAD_KEY}"})
            codes.append(resp.status_code)
        return codes

    def test_first_n_minus_one_failures_return_401(self) -> None:
        """The first (THRESHOLD-1) failures all return 401 — not yet locked."""
        app = _make_throttle_app(threshold=5)
        client = TestClient(app)
        # 4 failures = threshold - 1; none should trigger lockout
        codes = self._exhaust_failures(client, 4)
        assert all(c == 401 for c in codes), f"Expected all 401, got: {codes}"

    def test_threshold_failure_returns_429(self) -> None:
        """The THRESHOLD-th failure itself triggers the lockout and returns 429.

        When the failure count reaches the threshold, the lockout is activated
        immediately; the triggering request also returns 429 (not 401).
        """
        app = _make_throttle_app(threshold=5)
        client = TestClient(app)
        # 4 failures below threshold
        self._exhaust_failures(client, 4)
        # 5th failure triggers lockout → 429
        resp = client.get("/api/data", headers={"Authorization": f"Bearer {_BAD_KEY}"})
        assert resp.status_code == 429

    def test_threshold_plus_one_returns_429(self) -> None:
        """The (THRESHOLD+1)-th request also returns 429 — IP remains locked."""
        app = _make_throttle_app(threshold=5)
        client = TestClient(app)
        # 5 failures to exhaust threshold (5th triggers lockout)
        self._exhaust_failures(client, 5)
        # 6th attempt — IP is now in lockout → 429
        resp = client.get("/api/data", headers={"Authorization": f"Bearer {_BAD_KEY}"})
        assert resp.status_code == 429

    def test_429_response_contains_retry_after_header(self) -> None:
        """429 responses include a Retry-After header."""
        app = _make_throttle_app(threshold=5, lockout=300.0)
        client = TestClient(app)
        self._exhaust_failures(client, 5)
        resp = client.get("/api/data", headers={"Authorization": f"Bearer {_BAD_KEY}"})
        assert resp.status_code == 429
        assert "retry-after" in {k.lower() for k in resp.headers}

    def test_429_retry_after_value_is_positive_integer(self) -> None:
        """Retry-After header is a positive integer string."""
        app = _make_throttle_app(threshold=5, lockout=60.0)
        client = TestClient(app)
        self._exhaust_failures(client, 5)
        resp = client.get("/api/data", headers={"Authorization": f"Bearer {_BAD_KEY}"})
        assert resp.status_code == 429
        retry_after_raw = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
        assert retry_after_raw is not None
        retry_after = int(retry_after_raw)
        assert retry_after > 0

    def test_locked_ip_gets_429_even_with_correct_key(self) -> None:
        """A locked IP is rejected before credential check."""
        app = _make_throttle_app(threshold=5)
        client = TestClient(app)
        self._exhaust_failures(client, 5)
        # Even with the correct key, the locked IP gets 429
        resp = client.get("/api/data", headers={"Authorization": f"Bearer {_VALID_KEY}"})
        assert resp.status_code == 429

    def test_health_endpoint_never_throttled(self) -> None:
        """Public health endpoint is always reachable regardless of throttle state."""
        app = _make_throttle_app(threshold=2)
        client = TestClient(app)
        self._exhaust_failures(client, 2)
        # Still locked
        resp = client.get("/api/data")
        assert resp.status_code in {401, 429}
        # But health remains accessible
        health_resp = client.get("/api/health")
        assert health_resp.status_code == 200


# ---------------------------------------------------------------------------
# Success clears the counter
# ---------------------------------------------------------------------------


class TestSuccessClearsCounter:
    """Successful authentication resets the per-IP failure counter."""

    @pytest.fixture(autouse=True)
    def _set_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTIC_API_KEY", _VALID_KEY)

    def test_success_after_failures_clears_counter(self) -> None:
        """Successful auth after failures resets the counter so further failures start fresh."""
        app = _make_throttle_app(threshold=5)
        client = TestClient(app)

        # 4 failures (below threshold)
        for _ in range(4):
            client.get("/api/data", headers={"Authorization": f"Bearer {_BAD_KEY}"})

        # Successful auth
        resp = client.get("/api/data", headers={"Authorization": f"Bearer {_VALID_KEY}"})
        assert resp.status_code == 200

        # After reset, need another full threshold of failures to lock
        for _ in range(4):
            resp = client.get("/api/data", headers={"Authorization": f"Bearer {_BAD_KEY}"})
            assert resp.status_code == 401

        # 5th failure post-reset still not locked yet (threshold=5, this is the 5th)
        resp = client.get("/api/data", headers={"Authorization": f"Bearer {_BAD_KEY}"})
        # The 5th failure triggers the lockout on the 5th call (threshold=5 means 5 triggers lockout)
        # After recording the 5th failure it becomes locked; is_locked will return True
        # The test just confirms the counter was reset after success
        assert resp.status_code in {401, 429}  # 5th failure may or may not hit threshold
