"""Route-level tests for run history endpoints."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agentic_v2.core.tenant import get_tenant_context
from agentic_v2.server.routes import runs as runs_routes
from agentic_v2.workflows.run_logger import RunLogger
from tests._server_test_helpers import make_configured_app


def test_get_run_accepts_run_id_json_alias(monkeypatch, tmp_path):
    """Serve run details when clients request /api/runs/{run_id}.json."""
    payload = {
        "run_id": "code_review-abc123",
        "workflow_name": "code_review",
        "status": "failed",
        "steps": [],
    }
    run_path = tmp_path / "20260502T181725Z_code_review_failed.json"
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(runs_routes, "run_logger", RunLogger(runs_dir=tmp_path))

    client = TestClient(make_configured_app())
    response = client.get("/api/runs/code_review-abc123.json")

    assert response.status_code == 200
    assert response.json()["run_id"] == payload["run_id"]


def test_get_run_returns_404_for_unknown_run_identifier(monkeypatch, tmp_path):
    """Return 404 when a run filename or run_id cannot be resolved."""
    monkeypatch.setattr(runs_routes, "run_logger", RunLogger(runs_dir=tmp_path))

    client = TestClient(make_configured_app())
    response = client.get("/api/runs/missing-run.json")

    assert response.status_code == 404


def test_stream_route_requires_tenant_auth_dependency():
    """The SSE stream route is wired to the same tenant/auth dependency as its siblings.

    Regression guard for C-07: ``stream_run_events`` previously took only
    ``run_id`` and resolved no ``TenantContext``, so it had no per-tenant
    authorization context while every other run-history handler did. This
    inspects the resolved FastAPI dependant rather than HTTP behaviour, so it
    fails on the un-gated handler even though the API-key middleware also
    fronts the route.
    """
    stream_route = next(
        route
        for route in runs_routes.router.routes
        if getattr(route, "path", "") == "/runs/{run_id}/stream"
    )
    dependency_callables = [
        dependency.call for dependency in stream_route.dependant.dependencies
    ]
    assert get_tenant_context in dependency_callables


def test_stream_endpoint_rejects_unauthenticated_request(monkeypatch):
    """Reject an unauthenticated SSE stream request once an API key is configured.

    The ``GET /api/runs/{run_id}/stream`` route must be gated like every other
    run-history route: with ``AGENTIC_API_KEY`` set, a caller who supplies no
    credential (even one who guesses a valid ``run_id``) gets 401 and never
    reaches the live execution feed.
    """
    monkeypatch.setenv("AGENTIC_API_KEY", "stream-secret-key")

    client = TestClient(make_configured_app())
    response = client.get("/api/runs/code_review-abc123/stream")

    assert response.status_code in (401, 403)


def test_stream_endpoint_rejects_wrong_api_key(monkeypatch):
    """Reject an SSE stream request that presents the wrong bearer token."""
    monkeypatch.setenv("AGENTIC_API_KEY", "stream-secret-key")

    client = TestClient(make_configured_app())
    response = client.get(
        "/api/runs/code_review-abc123/stream",
        headers={"Authorization": "Bearer not-the-right-key"},
    )

    assert response.status_code in (401, 403)
