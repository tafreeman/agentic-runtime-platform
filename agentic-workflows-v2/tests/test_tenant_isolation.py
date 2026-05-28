"""Tenant isolation tests for Epic 8 E8-2."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from agentic_v2.core.tenant import (
    DEFAULT_TENANT_ID,
    TenantContext,
    get_tenant_context,
)
from agentic_v2.server.routes import runs as runs_routes
from agentic_v2.workflows.run_logger import RunLogger


def _write_run(runs_dir, tenant_id: str, run_id: str) -> None:
    tenant_dir = runs_dir / tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "workflow_name": "code_review",
        "status": "success",
        "success_rate": 100,
        "total_duration_ms": 1,
        "step_count": 0,
        "failed_step_count": 0,
        "start_time": "2026-05-18T00:00:00+00:00",
        "end_time": "2026-05-18T00:00:01+00:00",
        "steps": [],
    }
    (tenant_dir / f"20260518T000000Z_code_review_{run_id}_success.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_tenant_a_cannot_list_tenant_b_runs(monkeypatch, tmp_path) -> None:
    _write_run(tmp_path, "tenant-a", "run-a")
    _write_run(tmp_path, "tenant-b", "run-b")
    monkeypatch.setattr(runs_routes, "run_logger", RunLogger(runs_dir=tmp_path))

    app = FastAPI()
    app.include_router(runs_routes.router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/runs", headers={"X-Tenant-ID": "tenant-a"})

    assert response.status_code == 200
    run_ids = {item["run_id"] for item in response.json()}
    assert run_ids == {"run-a"}


def test_default_tenant_can_read_legacy_root_runs(monkeypatch, tmp_path) -> None:
    legacy_payload = {
        "run_id": "legacy-run",
        "workflow_name": "code_review",
        "status": "success",
        "steps": [],
    }
    (tmp_path / "20260518T000000Z_code_review_legacy-run_success.json").write_text(
        json.dumps(legacy_payload),
        encoding="utf-8",
    )
    monkeypatch.setattr(runs_routes, "run_logger", RunLogger(runs_dir=tmp_path))

    app = FastAPI()
    app.include_router(runs_routes.router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/runs/legacy-run.json")

    assert response.status_code == 200
    assert response.json()["run_id"] == "legacy-run"


def _tenant_app(user: Any | None = None, oidc_enabled: bool = False) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def inject_user(request: Request, call_next):
        if user is not None:
            request.state.user = user
        request.app.state.agentic_oidc_enabled = oidc_enabled
        return await call_next(request)

    @app.get("/tenant")
    async def tenant(
        context: TenantContext = Depends(get_tenant_context),
    ) -> dict[str, str]:
        return {"tenant_id": context.tenant_id, "source": context.source}

    return app


def test_tenant_context_extracts_tenant_from_oidc_claims() -> None:
    user = {"auth_type": "oidc", "claims": {"tid": "tenant-from-jwt"}}
    client = TestClient(_tenant_app(user=user, oidc_enabled=True))

    response = client.get("/tenant", headers={"X-Tenant-ID": "ignored-header"})

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-from-jwt", "source": "oidc"}


def test_tenant_context_uses_header_when_oidc_inactive() -> None:
    client = TestClient(_tenant_app(oidc_enabled=False))

    response = client.get("/tenant", headers={"X-Tenant-ID": "tenant-from-header"})

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": "tenant-from-header",
        "source": "header",
    }


def test_tenant_context_defaults_when_no_claim_or_header() -> None:
    client = TestClient(_tenant_app(oidc_enabled=False))

    response = client.get("/tenant")

    assert response.status_code == 200
    assert response.json() == {"tenant_id": DEFAULT_TENANT_ID, "source": "default"}
