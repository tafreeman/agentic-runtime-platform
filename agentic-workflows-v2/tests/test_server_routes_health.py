"""Tests for health check route."""

from __future__ import annotations

from agentic_v2.server.models import HealthResponse


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
