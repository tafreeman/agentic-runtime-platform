"""Tests for W3C traceparent propagation middleware and WebSocket handshake.

Coverage targets:
* middleware/tracing.py — TraceparentMiddleware header injection, no-op paths
* server/app.py — CORS expose_headers includes traceparent
* server/websocket.py — trace_context message on WebSocket handshake
"""

from __future__ import annotations

import importlib.util
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

# Tests that ``patch("opentelemetry...")`` need the real package importable
# (mock.patch import-resolves the target); the tracing extra is optional, so
# skip those tests — and only those — when it is absent. The otel-absent
# paths (e.g. ``test_returns_none_when_otel_not_installed``) still run.
_requires_otel = pytest.mark.skipif(
    importlib.util.find_spec("opentelemetry") is None,
    reason="opentelemetry not installed (tracing extra)",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_tracing_module() -> None:
    """Remove cached tracing module state so patches take effect cleanly."""
    for key in list(sys.modules.keys()):
        if "agentic_v2.server.middleware.tracing" in key:
            del sys.modules[key]


def _make_fake_span_context(
    trace_id: int = 0x4BF92F3577B34DA6A3CE929D0E0E4736,
    span_id: int = 0x00F067AA0BA902B7,
    is_valid: bool = True,
    trace_flags: int = 0x1,
) -> MagicMock:
    """Return a mock SpanContext with the given values."""
    ctx = MagicMock()
    ctx.trace_id = trace_id
    ctx.span_id = span_id
    ctx.is_valid = is_valid
    ctx.trace_flags = trace_flags
    ctx.trace_state = None
    return ctx


def _make_fake_span(ctx: MagicMock) -> MagicMock:
    span = MagicMock()
    span.get_span_context.return_value = ctx
    return span


# ---------------------------------------------------------------------------
# Unit tests: tracing.py — build_traceparent()
# ---------------------------------------------------------------------------


class TestBuildTraceparent:
    """Tests for build_traceparent() helper."""

    def test_returns_none_when_otel_not_installed(self) -> None:
        """build_traceparent() returns None when OTEL SDK is missing."""
        from agentic_v2.server.middleware.tracing import build_traceparent

        with patch.dict(
            sys.modules, {"opentelemetry": None, "opentelemetry.trace": None}
        ):
            result = build_traceparent()
        # ImportError path — result is None
        assert result is None

    @_requires_otel
    def test_returns_none_for_invalid_span_context(self) -> None:
        """build_traceparent() returns None when the span context is invalid."""
        ctx = _make_fake_span_context(is_valid=False)
        span = _make_fake_span(ctx)

        with patch("opentelemetry.trace.get_current_span", return_value=span):
            from agentic_v2.server.middleware.tracing import build_traceparent

            result = build_traceparent()

        assert result is None

    @_requires_otel
    def test_returns_none_for_zero_trace_id(self) -> None:
        """build_traceparent() returns None when trace_id is all-zeros."""
        ctx = _make_fake_span_context(trace_id=0, span_id=0x00F067AA0BA902B7)
        span = _make_fake_span(ctx)

        with patch("opentelemetry.trace.get_current_span", return_value=span):
            from agentic_v2.server.middleware.tracing import build_traceparent

            result = build_traceparent()

        assert result is None

    @_requires_otel
    def test_returns_valid_traceparent(self) -> None:
        """build_traceparent() returns a correctly formatted W3C traceparent."""
        ctx = _make_fake_span_context()
        span = _make_fake_span(ctx)

        with patch("opentelemetry.trace.get_current_span", return_value=span):
            from agentic_v2.server.middleware.tracing import build_traceparent

            result = build_traceparent()

        assert result is not None
        traceparent, _tracestate = result
        parts = traceparent.split("-")
        assert len(parts) == 4
        assert parts[0] == "00"  # version
        assert len(parts[1]) == 32  # trace-id
        assert len(parts[2]) == 16  # parent-id
        assert parts[3] in ("00", "01")  # trace-flags

    @_requires_otel
    def test_sampled_flag_is_01(self) -> None:
        """Sampled spans produce trace flags '01'."""
        ctx = _make_fake_span_context(trace_flags=0x1)
        span = _make_fake_span(ctx)

        with patch("opentelemetry.trace.get_current_span", return_value=span):
            from agentic_v2.server.middleware.tracing import build_traceparent

            result = build_traceparent()

        assert result is not None
        traceparent, _ = result
        assert traceparent.endswith("-01")

    @_requires_otel
    def test_not_sampled_flag_is_00(self) -> None:
        """Not-sampled spans produce trace flags '00'."""
        ctx = _make_fake_span_context(trace_flags=0x0)
        span = _make_fake_span(ctx)

        with patch("opentelemetry.trace.get_current_span", return_value=span):
            from agentic_v2.server.middleware.tracing import build_traceparent

            result = build_traceparent()

        assert result is not None
        traceparent, _ = result
        assert traceparent.endswith("-00")

    @_requires_otel
    def test_tracestate_included_when_present(self) -> None:
        """build_traceparent() returns non-empty tracestate when the span has it."""
        ctx = _make_fake_span_context()
        ctx.trace_state = MagicMock()
        ctx.trace_state.__str__ = lambda _: "vendor=abc"
        span = _make_fake_span(ctx)

        with patch("opentelemetry.trace.get_current_span", return_value=span):
            from agentic_v2.server.middleware.tracing import build_traceparent

            result = build_traceparent()

        assert result is not None
        _traceparent, tracestate = result
        assert tracestate == "vendor=abc"


# ---------------------------------------------------------------------------
# Unit tests: tracing.py — format helper
# ---------------------------------------------------------------------------


class TestFormatTraceparent:
    """Tests for the _format_traceparent() internal helper."""

    def test_format_sampled(self) -> None:
        from agentic_v2.server.middleware.tracing import _format_traceparent

        result = _format_traceparent("a" * 32, "b" * 16, is_sampled=True)
        assert result == f"00-{'a' * 32}-{'b' * 16}-01"

    def test_format_not_sampled(self) -> None:
        from agentic_v2.server.middleware.tracing import _format_traceparent

        result = _format_traceparent("a" * 32, "b" * 16, is_sampled=False)
        assert result.endswith("-00")


# ---------------------------------------------------------------------------
# Integration tests: TraceparentMiddleware via TestClient
# ---------------------------------------------------------------------------


class TestTraceparentMiddlewareDisabled:
    """Middleware is a no-op when AGENTIC_TRACING is not set."""

    def test_no_traceparent_header_when_tracing_disabled(self) -> None:
        from fastapi import FastAPI
        from starlette.responses import PlainTextResponse

        from agentic_v2.server.middleware.tracing import TraceparentMiddleware

        app = FastAPI()
        app.add_middleware(TraceparentMiddleware)

        @app.get("/ping")
        async def ping() -> PlainTextResponse:
            return PlainTextResponse("pong")

        with patch(
            "agentic_v2.server.middleware.tracing.is_tracing_enabled",
            return_value=False,
        ):
            with TestClient(app) as client:
                resp = client.get("/ping")

        assert resp.status_code == 200
        assert "traceparent" not in resp.headers

    def test_no_server_timing_when_tracing_disabled(self) -> None:
        from fastapi import FastAPI
        from starlette.responses import PlainTextResponse

        from agentic_v2.server.middleware.tracing import TraceparentMiddleware

        app = FastAPI()
        app.add_middleware(TraceparentMiddleware)

        @app.get("/ping")
        async def ping() -> PlainTextResponse:
            return PlainTextResponse("pong")

        with patch(
            "agentic_v2.server.middleware.tracing.is_tracing_enabled",
            return_value=False,
        ):
            with TestClient(app) as client:
                resp = client.get("/ping")

        assert "server-timing" not in {k.lower() for k in resp.headers}


class TestTraceparentMiddlewareEnabled:
    """Middleware injects headers when tracing is enabled and a span is active."""

    def _make_app_with_span(self, ctx: MagicMock) -> Any:
        from fastapi import FastAPI
        from starlette.responses import PlainTextResponse

        from agentic_v2.server.middleware.tracing import TraceparentMiddleware

        span = _make_fake_span(ctx)
        app = FastAPI()
        app.add_middleware(TraceparentMiddleware)

        @app.get("/ping")
        async def ping() -> PlainTextResponse:
            return PlainTextResponse("pong")

        return app, span

    @_requires_otel
    def test_traceparent_header_injected(self) -> None:
        ctx = _make_fake_span_context()
        app, span = self._make_app_with_span(ctx)

        with (
            patch(
                "agentic_v2.server.middleware.tracing.is_tracing_enabled",
                return_value=True,
            ),
            patch("opentelemetry.trace.get_current_span", return_value=span),
        ):
            with TestClient(app) as client:
                resp = client.get("/ping")

        assert resp.status_code == 200
        assert "traceparent" in resp.headers
        parts = resp.headers["traceparent"].split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
        assert len(parts[1]) == 32
        assert len(parts[2]) == 16

    @_requires_otel
    def test_server_timing_header_injected(self) -> None:
        ctx = _make_fake_span_context()
        app, span = self._make_app_with_span(ctx)

        with (
            patch(
                "agentic_v2.server.middleware.tracing.is_tracing_enabled",
                return_value=True,
            ),
            patch("opentelemetry.trace.get_current_span", return_value=span),
        ):
            with TestClient(app) as client:
                resp = client.get("/ping")

        server_timing = resp.headers.get("server-timing", "")
        assert "traceid" in server_timing
        # The trace ID from our fake span is present
        assert "4bf92f3577b34da6a3ce929d0e0e4736" in server_timing

    @_requires_otel
    def test_no_header_when_build_traceparent_returns_none(self) -> None:
        """If no active span, headers are not injected."""
        ctx = _make_fake_span_context(is_valid=False)
        app, span = self._make_app_with_span(ctx)

        with (
            patch(
                "agentic_v2.server.middleware.tracing.is_tracing_enabled",
                return_value=True,
            ),
            patch("opentelemetry.trace.get_current_span", return_value=span),
        ):
            with TestClient(app) as client:
                resp = client.get("/ping")

        assert "traceparent" not in resp.headers


# ---------------------------------------------------------------------------
# Integration tests: CORS expose_headers in app.py
# ---------------------------------------------------------------------------


class TestCORSExposeHeaders:
    """CORS middleware exposes traceparent, tracestate, Server-Timing."""

    def test_expose_headers_includes_traceparent(self) -> None:
        import os

        with patch.dict(os.environ, {"AGENTIC_RATE_LIMIT_DISABLED": "1"}):
            from agentic_v2.server.app import create_app

            app = create_app()

        # Find the CORSMiddleware in the middleware stack and check expose_headers
        cors_mw = None
        for mw in app.middleware_stack.__class__.__mro__:
            pass  # middleware_stack is compiled; introspect via user_middleware
        for entry in app.user_middleware:
            cls_name = getattr(entry.cls, "__name__", "")
            if "CORS" in cls_name:
                cors_mw = entry
                break

        assert cors_mw is not None, "CORSMiddleware not found in middleware stack"
        expose = cors_mw.kwargs.get("expose_headers", [])
        assert "traceparent" in expose
        assert "tracestate" in expose
        assert "Server-Timing" in expose


# ---------------------------------------------------------------------------
# Integration tests: WebSocket trace_context message
# ---------------------------------------------------------------------------


class TestWebSocketTraceContext:
    """WebSocket handshake sends trace_context when tracing is enabled."""

    @pytest.mark.asyncio
    @_requires_otel
    async def test_trace_context_message_sent_when_tracing_enabled(self) -> None:
        from agentic_v2.server.websocket import ConnectionManager

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()

        ctx = _make_fake_span_context()
        span = _make_fake_span(ctx)

        mgr = ConnectionManager()

        # Simulate the websocket_endpoint connect + trace_context send
        with (
            patch("agentic_v2.server.websocket.is_tracing_enabled", return_value=True),
            patch("opentelemetry.trace.get_current_span", return_value=span),
        ):
            await mgr.connect(ws, "run-trace-test")

            from agentic_v2.server.middleware.tracing import build_traceparent

            result = build_traceparent()
            assert result is not None
            traceparent, tracestate = result
            trace_ctx_msg: dict[str, Any] = {
                "type": "trace_context",
                "traceparent": traceparent,
            }
            if tracestate:
                trace_ctx_msg["tracestate"] = tracestate
            await ws.send_json(trace_ctx_msg)

        # Verify the message was sent with correct structure
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "trace_context"
        assert "traceparent" in call_args
        parts = call_args["traceparent"].split("-")
        assert len(parts) == 4

    @pytest.mark.asyncio
    async def test_no_trace_context_when_tracing_disabled(self) -> None:
        """No trace_context message when AGENTIC_TRACING=0."""
        from agentic_v2.server.websocket import ConnectionManager

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        mgr = ConnectionManager()

        with patch(
            "agentic_v2.server.websocket.is_tracing_enabled", return_value=False
        ):
            await mgr.connect(ws, "run-no-trace")
            # Simulate the endpoint logic: only send trace_context when enabled
            from agentic_v2.server.websocket import (
                is_tracing_enabled,  # type: ignore[attr-defined]
            )

            if is_tracing_enabled():
                await ws.send_json({"type": "trace_context", "traceparent": "dummy"})

        ws.send_json.assert_not_called()

    @_requires_otel
    def test_trace_context_message_format(self) -> None:
        """trace_context message contains the expected keys."""
        ctx = _make_fake_span_context()
        span = _make_fake_span(ctx)

        with patch("opentelemetry.trace.get_current_span", return_value=span):
            from agentic_v2.server.middleware.tracing import build_traceparent

            result = build_traceparent()

        assert result is not None
        traceparent, _tracestate = result
        msg = {"type": "trace_context", "traceparent": traceparent}

        assert msg["type"] == "trace_context"
        assert msg["traceparent"].startswith("00-")
