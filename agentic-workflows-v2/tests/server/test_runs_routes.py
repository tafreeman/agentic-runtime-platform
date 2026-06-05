"""Route-level tests for run history endpoints."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

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
