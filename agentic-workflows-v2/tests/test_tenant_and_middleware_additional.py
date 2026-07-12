from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentic_v2.core import tenant as tenant_mod
from agentic_v2.server.middleware import SanitizationASGIMiddleware, _fail_open_enabled


class _SanitizerResult:
    def __init__(self, classification: str, sanitized_text: str = ""):
        self.classification = classification
        self.sanitized_text = sanitized_text
        self.is_safe = classification != "blocked"
        self.findings = []


class _FakeSanitizer:
    def __init__(self, result: _SanitizerResult | Exception):
        self.result = result

    async def process(self, body_text: str, _meta: dict[str, str]):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _app_with_route() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SanitizationASGIMiddleware)

    @app.post("/echo")
    async def echo(request: Request):
        return await request.json()

    @app.get("/plain")
    async def plain():
        return {"ok": True}

    return app


def test_tenant_helpers_cover_user_header_default_and_migration(
    monkeypatch, tmp_path: Path
):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-tenant-id", b"header-tenant")],
            "app": SimpleNamespace(state=SimpleNamespace(agentic_oidc_enabled=False)),
        }
    )
    request.state.user = {"tenant_id": "oidc tenant", "sub": "user-123"}
    resolved = tenant_mod.get_tenant_context(request)
    assert resolved.tenant_id == "oidc_tenant"
    assert resolved.source == "oidc"
    assert resolved.actor_subject == "user-123"

    request.state.user = None
    resolved = tenant_mod.get_tenant_context(request)
    assert resolved.tenant_id == "header-tenant"
    assert resolved.source == "header"

    request_no_header = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace(agentic_oidc_enabled=True)),
        }
    )
    resolved = tenant_mod.get_tenant_context(request_no_header)
    assert resolved.tenant_id == tenant_mod.DEFAULT_TENANT_ID
    assert resolved.source == "default"

    assert tenant_mod.sanitize_tenant_id("  weird/tenant.* ") == "weird_tenant"

    runs_root = tmp_path / "runs"
    datasets_root = tmp_path / "datasets"
    runs_root.mkdir()
    datasets_root.mkdir()
    (runs_root / "run.json").write_text("{}", encoding="utf-8")
    (datasets_root / "sample.json").write_text("{}", encoding="utf-8")

    moved = tenant_mod.migrate_legacy_tenant_storage(
        runs_dir=runs_root,
        datasets_dir=datasets_root,
        tenant_id="tenant-a",
        dry_run=False,
    )
    assert moved["runs"]
    assert moved["datasets"]
    assert (runs_root / "tenant-a" / "run.json").exists()
    assert (datasets_root / "tenant-a" / "sample.json").exists()

    monkeypatch.setattr(
        tenant_mod, "get_settings", lambda: SimpleNamespace(agentic_oidc_enabled=True)
    )
    assert tenant_mod._oidc_enabled(request_no_header) is True


def test_sanitization_middleware_covers_fail_closed_fail_open_and_redaction(
    monkeypatch,
):
    app = _app_with_route()
    client = TestClient(app)

    monkeypatch.delenv("AGENTIC_SANITIZER_FAIL_OPEN", raising=False)
    response = client.post("/echo", json={"message": "hi"})
    assert response.status_code == 503

    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "1")
    response = client.post("/echo", json={"message": "hi"})
    assert response.status_code == 200
    assert response.json() == {"message": "hi"}
    assert _fail_open_enabled() is True

    monkeypatch.delenv("AGENTIC_SANITIZER_FAIL_OPEN", raising=False)
    app.state.sanitization = _FakeSanitizer(_SanitizerResult("blocked"))
    response = client.post("/echo", json={"message": "blocked"})
    assert response.status_code == 422

    app.state.sanitization = _FakeSanitizer(
        _SanitizerResult("redacted", '{"message":"sanitized"}')
    )
    response = client.post("/echo", json={"message": "secret"})
    assert response.status_code == 200

    app.state.sanitization = _FakeSanitizer(RuntimeError("boom"))
    response = client.post("/echo", json={"message": "error"})
    assert response.status_code == 500

    app.state.sanitization = _FakeSanitizer(_SanitizerResult("clean"))
    response = client.get("/plain")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
