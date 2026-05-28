"""Tests for the fail-closed ``SanitizationASGIMiddleware`` ASGI wrapper.

Adversarial regression tests covering two failure modes:
1. Detector runtime error — must return HTTP 500, not silently pass through.
2. Sanitizer not initialized (``app.state.sanitization is None``) — must return
   HTTP 503, not silently pass through (fail-closed default).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agentic_v2.middleware.base import MiddlewareChain
from agentic_v2.middleware.sanitization import SanitizationMiddleware
from agentic_v2.server.app import create_app
from agentic_v2.server.middleware import SanitizationASGIMiddleware


class _ExplodingDetector:
    """Stub sanitizer whose ``process`` always raises — simulates a detector bug."""

    async def process(self, text: str, metadata: dict[str, Any]) -> None:
        raise RuntimeError("detector exploded")


class _ExplodingScanDetector:
    """Real chain detector whose ``scan`` fails."""

    name = "exploding-scan"
    version = "test"

    async def scan(self, text: str) -> list[Any]:
        raise RuntimeError("scan exploded")


async def _echo(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _make_app(detector: Any) -> Starlette:
    app = Starlette(routes=[Route("/run", _echo, methods=["POST"])])
    app.state.sanitization = detector
    app.add_middleware(SanitizationASGIMiddleware)
    return app


def _make_app_without_sanitizer_attr() -> Starlette:
    app = Starlette(routes=[Route("/run", _echo, methods=["POST"])])
    app.add_middleware(SanitizationASGIMiddleware)
    return app


async def test_exploding_detector_returns_500() -> None:
    """A detector that raises must trigger fail-closed HTTP 500, not pass-through."""
    app = _make_app(_ExplodingDetector())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run",
            json={"workflow": "test"},
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 500
    assert response.json()["detail"] == "Internal sanitization error"


async def test_real_detector_scan_error_returns_500() -> None:
    """A real detector scan failure must fail closed through the ASGI boundary."""
    chain = MiddlewareChain(detectors=[_ExplodingScanDetector()])
    sanitizer = SanitizationMiddleware(chain=chain)
    app = _make_app(sanitizer)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run",
            json={"workflow": "test"},
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal sanitization error"


async def test_no_sanitizer_returns_503() -> None:
    """When sanitizer is None (init failed), requests must be rejected with 503 (fail-closed)."""
    app = _make_app(None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run",
            json={"workflow": "test"},
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 503
    assert "sanitization" in response.json()["detail"]


async def test_unconfigured_sanitizer_attr_returns_503() -> None:
    """Missing sanitizer state must be treated as not initialized."""
    app = _make_app_without_sanitizer_attr()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run",
            json={"workflow": "test"},
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 503
    assert "sanitization" in response.json()["detail"]


async def test_no_sanitizer_passes_through_when_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With AGENTIC_SANITIZER_FAIL_OPEN=1, a None sanitizer falls back to pass-through."""
    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "1")
    app = _make_app(None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run",
            json={"workflow": "test"},
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 200


async def test_missing_sanitizer_attr_passes_through_when_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AGENTIC_SANITIZER_FAIL_OPEN=1 also permits missing sanitizer state."""
    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "1")
    app = _make_app_without_sanitizer_attr()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run",
            json={"workflow": "test"},
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 200


async def test_no_sanitizer_rejects_when_fail_open_env_is_not_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only AGENTIC_SANITIZER_FAIL_OPEN=1 enables fail-open runtime behavior."""
    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "true")
    app = _make_app(None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run",
            json={"workflow": "test"},
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 503


async def test_non_json_content_type_bypasses_sanitizer() -> None:
    """Non-JSON content types must bypass the detector (and thus not explode)."""
    app = _make_app(_ExplodingDetector())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run",
            content=b"plain text body",
            headers={"content-type": "text/plain"},
        )
    assert response.status_code == 200


async def test_fail_open_escape_hatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """With AGENTIC_SANITIZER_FAIL_OPEN=1, detector errors fall back to pass-through."""
    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "1")
    app = _make_app(_ExplodingDetector())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/run",
            json={"workflow": "test"},
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 200


def test_app_startup_fails_closed_when_sanitizer_init_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server startup must fail if sanitizer initialization fails by default."""

    def _raise_init_error(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("sanitizer boom")

    monkeypatch.delenv("AGENTIC_SANITIZER_FAIL_OPEN", raising=False)
    monkeypatch.setattr(SanitizationMiddleware, "default", _raise_init_error)
    app = create_app()

    with pytest.raises(RuntimeError, match="Sanitization middleware failed"):
        with TestClient(app):
            pass


def test_app_startup_allows_fail_open_escape_hatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit fail-open flag preserves operator-controlled startup."""

    def _raise_init_error(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("sanitizer boom")

    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "1")
    monkeypatch.setattr(SanitizationMiddleware, "default", _raise_init_error)
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200


def test_app_startup_fails_closed_when_fail_open_env_is_not_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only AGENTIC_SANITIZER_FAIL_OPEN=1 enables fail-open startup behavior."""

    def _raise_init_error(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("sanitizer boom")

    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "true")
    monkeypatch.setattr(SanitizationMiddleware, "default", _raise_init_error)
    app = create_app()

    with pytest.raises(RuntimeError, match="Sanitization middleware failed"):
        with TestClient(app):
            pass
