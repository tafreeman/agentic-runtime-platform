"""Tenant isolation, OIDC auth, and terminal-event rules for live-run streams."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agentic_v2.core.tenant import TenantContext
from agentic_v2.server import websocket as ws_module
from agentic_v2.server.auth import AuthThrottle
from agentic_v2.server.auth_oidc import (
    AuthenticatedActor,
    OIDCAuthenticationError,
    OIDCProviderUnavailable,
)
from agentic_v2.server.routes import runs as runs_routes
from agentic_v2.server.websocket import ConnectionManager
from agentic_v2.workflows.run_logger import RunLogger

TENANT_A = TenantContext(tenant_id="tenant-a", source="oidc")


@pytest.fixture
def fresh_manager(monkeypatch: pytest.MonkeyPatch, tmp_path) -> ConnectionManager:
    mgr = ConnectionManager(retention_seconds=3600)
    monkeypatch.setattr(ws_module, "manager", mgr)
    monkeypatch.setattr(runs_routes, "run_logger", RunLogger(runs_dir=tmp_path))
    monkeypatch.delenv("AGENTIC_API_KEY", raising=False)
    return mgr


class TestRunOwnership:
    def test_bound_run_is_visible_only_to_owner(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("run-1", "tenant-a")
        assert fresh_manager.is_run_accessible("run-1", "tenant-a")
        assert not fresh_manager.is_run_accessible("run-1", "tenant-b")

    def test_first_binding_wins(self, fresh_manager) -> None:
        assert fresh_manager.bind_run_tenant("run-1", "tenant-a")
        assert fresh_manager.bind_run_tenant("run-1", "tenant-a")
        assert not fresh_manager.bind_run_tenant("run-1", "tenant-b")
        assert not fresh_manager.is_run_accessible("run-1", "tenant-b")

    def test_unknown_run_fails_closed(self, fresh_manager, tmp_path) -> None:
        assert not fresh_manager.is_run_accessible(
            "ghost", "tenant-a", run_logger=RunLogger(runs_dir=tmp_path)
        )

    def test_unbound_run_falls_back_to_own_tenant_record(
        self, fresh_manager, tmp_path
    ) -> None:
        base = RunLogger(runs_dir=tmp_path)
        tenant_dir = base.for_tenant("tenant-a").runs_dir
        (tenant_dir / "20260101T000000Z_wf_success.json").write_text(
            json.dumps({"run_id": "wf-abc"}), encoding="utf-8"
        )
        assert fresh_manager.is_run_accessible("wf-abc", "tenant-a", run_logger=base)
        assert not fresh_manager.is_run_accessible(
            "wf-abc", "tenant-b", run_logger=base
        )

    def test_clear_buffer_drops_binding(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("run-1", "tenant-a")
        fresh_manager.clear_buffer("run-1")
        assert "run-1" not in fresh_manager._run_tenants


def _event(kind: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"type": kind, "run_id": "r", "timestamp": "t"}
    if kind == "workflow_end":
        base["status"] = "success"
    if kind == "error":
        base["error"] = "boom"
    return {**base, **extra}


def _evaluation_complete() -> dict[str, Any]:
    return _event(
        "evaluation_complete",
        rubric="x",
        weighted_score=1.0,
        overall_score=1.0,
        grade="A",
        passed=True,
        pass_threshold=0.5,
        criteria=[],
        hard_gates=[],
        hard_gate_failures=[],
        step_scores=[],
    )


async def _collect(mgr: ConnectionManager, events: list[dict[str, Any]]) -> list[str]:
    response = await runs_routes.stream_run_events("r", TENANT_A)
    received: list[str] = []

    async def consume() -> None:
        async for chunk in response.body_iterator:
            received.append(json.loads(str(chunk).removeprefix("data: "))["type"])

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the generator register its SSE listener
    for event in events:
        await mgr.broadcast("r", event)
    await asyncio.wait_for(task, timeout=5)
    return received


class TestSseStream:
    async def test_cross_tenant_stream_is_404(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("run-b", "tenant-b")
        with pytest.raises(HTTPException) as exc:
            await runs_routes.stream_run_events("run-b", TENANT_A)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Run not found: run-b"

    async def test_unknown_run_stream_is_404(self, fresh_manager) -> None:
        with pytest.raises(HTTPException) as exc:
            await runs_routes.stream_run_events("ghost", TENANT_A)
        assert exc.value.status_code == 404

    async def test_ends_on_workflow_end_without_evaluation(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("r", "tenant-a")
        got = await _collect(
            fresh_manager, [_event("workflow_end", evaluation_enabled=False)]
        )
        assert got == ["workflow_end"]

    async def test_evaluation_events_delivered_after_workflow_end(
        self, fresh_manager
    ) -> None:
        fresh_manager.bind_run_tenant("r", "tenant-a")
        got = await _collect(
            fresh_manager,
            [
                _event("workflow_end", evaluation_enabled=True),
                _event("evaluation_start"),
                _evaluation_complete(),
            ],
        )
        assert got == ["workflow_end", "evaluation_start", "evaluation_complete"]

    async def test_error_is_terminal(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("r", "tenant-a")
        assert await _collect(fresh_manager, [_event("error")]) == ["error"]

    async def test_error_ends_stream_during_evaluation(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("r", "tenant-a")
        got = await _collect(
            fresh_manager,
            [
                _event("workflow_end", evaluation_enabled=True),
                _event("evaluation_start"),
                _event("error"),
            ],
        )
        assert got[-1] == "error"


class _FakeAuthenticator:
    """Accepts ``good-a`` / ``good-b``; rejects everything else."""

    def __init__(self, unavailable: bool = False) -> None:
        self._unavailable = unavailable

    async def authenticate(self, token: str) -> AuthenticatedActor:
        if self._unavailable:
            raise OIDCProviderUnavailable("down")
        tenants = {"good-a": "tenant-a", "good-b": "tenant-b"}
        if token not in tenants:
            raise OIDCAuthenticationError("bad")
        return AuthenticatedActor(
            auth_type="oidc", subject=f"user-{token}", tenant_id=tenants[token]
        )


def _ws_app(*, oidc: bool, unavailable: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(ws_module.router)
    app.state.agentic_oidc_enabled = oidc
    app.state.oidc_authenticator = _FakeAuthenticator(unavailable)
    app.state.auth_throttle = AuthThrottle()
    return app


def _connect(client: TestClient, path: str, token: str | None) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with client.websocket_connect(path, headers=headers):
        pass


class TestWebSocketOidc:
    def test_rejects_missing_token_without_api_key(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("run-a", "tenant-a")
        with (
            TestClient(_ws_app(oidc=True)) as client,
            pytest.raises(WebSocketDisconnect),
        ):
            _connect(client, "/ws/execution/run-a", None)

    def test_rejects_invalid_token(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("run-a", "tenant-a")
        with (
            TestClient(_ws_app(oidc=True)) as client,
            pytest.raises(WebSocketDisconnect),
        ):
            _connect(client, "/ws/execution/run-a", "forged")

    def test_provider_outage_closes_socket(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("run-a", "tenant-a")
        with (
            TestClient(_ws_app(oidc=True, unavailable=True)) as client,
            pytest.raises(WebSocketDisconnect),
        ):
            _connect(client, "/ws/execution/run-a", "good-a")

    def test_accepts_owner_tenant(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("run-a", "tenant-a")
        with TestClient(_ws_app(oidc=True)) as client:
            _connect(client, "/ws/execution/run-a", "good-a")

    def test_rejects_cross_tenant_run(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("run-a", "tenant-a")
        with (
            TestClient(_ws_app(oidc=True)) as client,
            pytest.raises(WebSocketDisconnect),
        ):
            _connect(client, "/ws/execution/run-a", "good-b")

    def test_rejects_query_param_token(self, fresh_manager) -> None:
        fresh_manager.bind_run_tenant("run-a", "tenant-a")
        with (
            TestClient(_ws_app(oidc=True)) as client,
            pytest.raises(WebSocketDisconnect),
        ):
            _connect(client, "/ws/execution/run-a?token=good-a", None)


def test_api_key_path_is_scoped_to_default_tenant(
    fresh_manager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTIC_API_KEY", "k")
    fresh_manager.bind_run_tenant("run-default", "default")
    fresh_manager.bind_run_tenant("run-other", "tenant-b")
    with TestClient(_ws_app(oidc=False)) as client:
        _connect(client, "/ws/execution/run-default", "k")
        with pytest.raises(WebSocketDisconnect):
            _connect(client, "/ws/execution/run-other", "k")
