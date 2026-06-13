"""Tests for the health (liveness) and readiness routes.

Covers:
  * ``HealthResponse`` model defaults (liveness contract).
  * ``GET /api/health`` -- cheap liveness probe, always 200.
  * ``GET /api/health/ready`` -- readiness probe:
      - 200 "ready" when no critical dependency is down.
      - 503 "not_ready" naming the failed dependency when Redis is
        configured but unreachable.
      - degraded-selection count and open circuit breakers surfaced.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import agentic_v2.settings as _settings_module
from agentic_v2.models.model_stats import CircuitState, ModelStats
from agentic_v2.server.models import HealthResponse
from tests._server_test_helpers import make_configured_app


class TestHealthResponse:
    """Tests for HealthResponse model (used by GET /api/health)."""

    def test_health_response_defaults(self) -> None:
        """HealthResponse has correct defaults."""
        resp = HealthResponse()
        assert resp.status == "ok"
        assert resp.version == "0.1.0"

    def test_health_response_contains_status_ok(self) -> None:
        """Response body includes status='ok'."""
        resp = HealthResponse()
        data = resp.model_dump()
        assert data["status"] == "ok"

    def test_health_response_contains_version(self) -> None:
        """Response body includes a version string."""
        resp = HealthResponse()
        assert isinstance(resp.version, str)
        assert len(resp.version) > 0


@pytest.fixture()
def client() -> TestClient:
    """A TestClient over a sanitizer-configured app (all /api routes mounted)."""
    return TestClient(make_configured_app())


class TestLivenessProbe:
    """GET /api/health stays a cheap, dependency-free liveness probe."""

    def test_health_returns_200_ok(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestReadinessProbe:
    """GET /api/health/ready inspects dependencies and routing health."""

    @pytest.fixture(autouse=True)
    def _reset_probe_cache(self):
        """Isolate the module-level cached Redis probe store between tests."""
        import agentic_v2.server.routes.health as health_mod

        health_mod._redis_probe_store = None
        yield
        health_mod._redis_probe_store = None

    def test_ready_200_when_redis_not_configured(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no redis_url, Redis is 'skipped' and readiness is 200/ready."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("AGENTIC_REDIS_URL", raising=False)
        _settings_module.get_settings.cache_clear()

        resp = client.get("/api/health/ready")
        assert resp.status_code == 200

        body = resp.json()
        assert body["status"] == "ready"
        redis_dep = next(d for d in body["dependencies"] if d["name"] == "redis")
        assert redis_dep["status"] == "skipped"
        # Routing health fields are present for visibility.
        assert "degraded_selection_count" in body
        assert "open_circuit_breakers" in body

    def test_not_ready_503_when_redis_configured_but_down(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Redis configured but unreachable → 503 naming redis as down."""
        # Point at a closed port so connect() fails fast and stays disconnected.
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
        _settings_module.get_settings.cache_clear()

        # Sanity: the setting actually took effect.
        assert _settings_module.get_settings().redis_url == "redis://127.0.0.1:1/0"

        resp = client.get("/api/health/ready")
        assert resp.status_code == 503

        body = resp.json()
        assert body["status"] == "not_ready"
        redis_dep = next(d for d in body["dependencies"] if d["name"] == "redis")
        assert redis_dep["status"] == "down"
        # The failed dependency is named, and no secret/URL is leaked in detail.
        assert redis_dep["name"] == "redis"
        assert "127.0.0.1" not in (redis_dep["detail"] or "")

    def test_redis_probe_reuses_cached_connection(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Repeated probes reuse one Redis store instead of reconnecting.

        PR #73 review (Gemini): a fresh connection pool per probe churns
        sockets under frequent orchestrator health checks; the probe must
        connect once and reuse the store while it stays healthy.
        """
        url = "redis://127.0.0.1:6399/0"
        monkeypatch.setenv("REDIS_URL", url)
        _settings_module.get_settings.cache_clear()

        connect_calls = {"count": 0}

        class _FakeStore:
            redis_url = url
            is_connected = True

            async def health_check(self) -> bool:
                return True

            async def close(self) -> None:
                pass

        async def _fake_connect(redis_url: str, **_kwargs: object) -> _FakeStore:
            connect_calls["count"] += 1
            return _FakeStore()

        from agentic_v2.models.redis_state import RedisCircuitBreakerStore

        monkeypatch.setattr(RedisCircuitBreakerStore, "connect", _fake_connect)

        for _ in range(3):
            resp = client.get("/api/health/ready")
            assert resp.status_code == 200
            redis_dep = next(
                d for d in resp.json()["dependencies"] if d["name"] == "redis"
            )
            assert redis_dep["status"] == "ok"

        assert connect_calls["count"] == 1, (
            f"Expected a single cached connection across probes, got "
            f"{connect_calls['count']} connects — pool churn regression"
        )

    def test_ready_surfaces_open_circuit_breakers(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OPEN circuit breaker on a model is reported in the readiness body."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        _settings_module.get_settings.cache_clear()

        # Trip a breaker on the process-global router the route inspects.
        from agentic_v2.models.smart_router import get_smart_router

        router = get_smart_router()
        tripped = ModelStats(model_id="ollama:phi4")
        for _ in range(5):
            tripped.record_failure("error")
        assert tripped.circuit_state == CircuitState.OPEN
        router.model_stats["ollama:phi4"] = tripped
        router.degraded_selection_count = 3

        resp = client.get("/api/health/ready")
        assert resp.status_code == 200  # open breaker alone does not fail readiness

        body = resp.json()
        assert "ollama:phi4" in body["open_circuit_breakers"]
        assert body["degraded_selection_count"] == 3

    def test_not_ready_503_when_redis_health_check_hangs(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hanging Redis health_check is aborted after 2 s and returns 503.

        Regression guard for the ``asyncio.wait_for`` timeout wrapping
        ``store.health_check()``.  The fake store never resolves its ping, so
        without the timeout the probe would block for the OS TCP timeout
        (minutes); with the fix it returns ``down`` promptly.
        """
        url = "redis://127.0.0.1:6399/0"
        monkeypatch.setenv("REDIS_URL", url)
        _settings_module.get_settings.cache_clear()

        class _HangingStore:
            redis_url = url
            is_connected = True

            async def health_check(self) -> bool:
                # Simulate a hung TCP connection — sleep longer than the probe
                # timeout so asyncio.wait_for raises TimeoutError.
                await asyncio.sleep(60)
                return True  # pragma: no cover — never reached under timeout

            async def close(self) -> None:
                pass

        async def _fake_connect(redis_url: str, **_kwargs: object) -> _HangingStore:
            return _HangingStore()

        from agentic_v2.models.redis_state import RedisCircuitBreakerStore

        monkeypatch.setattr(RedisCircuitBreakerStore, "connect", _fake_connect)

        resp = client.get("/api/health/ready")
        assert resp.status_code == 503

        body = resp.json()
        assert body["status"] == "not_ready"
        redis_dep = next(d for d in body["dependencies"] if d["name"] == "redis")
        assert redis_dep["status"] == "down"
        assert redis_dep["detail"] == "health check timed out"
