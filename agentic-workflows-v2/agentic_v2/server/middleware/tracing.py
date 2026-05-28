"""W3C traceparent propagation middleware for the Agentic Workflows V2 server.

Injects the current OTEL span's W3C ``traceparent`` and optional ``tracestate``
headers into every HTTP response so that browsers and downstream services can
correlate frontend traces with backend spans.

Also appends a ``Server-Timing`` header with the trace ID so the trace viewer
link is visible in browser DevTools without installing additional tooling.

All OTEL imports are guarded with ``try/except ImportError`` — the middleware
degrades to a silent no-op when the OpenTelemetry SDK is not installed.

Environment variables:
    AGENTIC_TRACING: Must be "1" for headers to be injected (mirrors the
        existing tracing flag checked by :func:`~agentic_v2.integrations.otel.is_tracing_enabled`).
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from ...integrations.otel import is_tracing_enabled

logger = logging.getLogger(__name__)

# W3C Trace Context version byte (currently the only valid version)
_TRACEPARENT_VERSION = "00"

# Trace flags: 01 = sampled, 00 = not sampled
_TRACE_FLAG_SAMPLED = "01"
_TRACE_FLAG_NOT_SAMPLED = "00"

# Invalid / zero span context — used to detect a non-recording span
_INVALID_TRACE_ID = "0" * 32
_INVALID_SPAN_ID = "0" * 16


def _format_traceparent(trace_id_hex: str, span_id_hex: str, is_sampled: bool) -> str:
    """Format a W3C traceparent header value.

    Format: ``{version}-{trace-id}-{parent-id}-{trace-flags}``

    Args:
        trace_id_hex: 32-char lowercase hex trace ID.
        span_id_hex: 16-char lowercase hex span ID.
        is_sampled: Whether the span is sampled.

    Returns:
        A W3C traceparent string, e.g.
        ``"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"``.
    """
    flags = _TRACE_FLAG_SAMPLED if is_sampled else _TRACE_FLAG_NOT_SAMPLED
    return f"{_TRACEPARENT_VERSION}-{trace_id_hex}-{span_id_hex}-{flags}"


def build_traceparent() -> tuple[str, str] | None:
    """Build W3C traceparent and tracestate values from the active OTEL span.

    Returns:
        A ``(traceparent, tracestate)`` tuple when a valid recording span is
        active, otherwise ``None``.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.trace import SpanContext
    except ImportError:
        return None

    span = trace.get_current_span()
    if span is None:
        return None

    ctx: SpanContext = span.get_span_context()
    if ctx is None or not ctx.is_valid:
        return None

    trace_id_hex = format(ctx.trace_id, "032x")
    span_id_hex = format(ctx.span_id, "016x")

    # Reject all-zero IDs (invalid / non-recording spans)
    if trace_id_hex == _INVALID_TRACE_ID or span_id_hex == _INVALID_SPAN_ID:
        return None

    is_sampled = bool(ctx.trace_flags & 0x1)
    traceparent = _format_traceparent(trace_id_hex, span_id_hex, is_sampled)

    tracestate = ""
    if ctx.trace_state:
        try:
            tracestate = str(ctx.trace_state)
        except Exception:
            tracestate = ""

    return traceparent, tracestate


class TraceparentMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that injects W3C trace context headers into responses.

    For every HTTP response, when tracing is enabled and an active OTEL span
    exists, the following headers are added:

    * ``traceparent`` — W3C ``00-{trace_id}-{span_id}-{flags}``
    * ``tracestate`` — W3C trace state (omitted when empty)
    * ``Server-Timing`` — ``traceid;desc="{trace_id}"`` for DevTools visibility

    When tracing is disabled, the SDK is not installed, or no recording span is
    active, this middleware is a transparent pass-through with no overhead.

    The middleware never raises — all errors are logged at DEBUG level so that
    a broken OTEL SDK cannot take down the request pipeline.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response: Response = await call_next(request)

        if not is_tracing_enabled():
            return response

        try:
            result = build_traceparent()
            if result is None:
                return response

            traceparent, tracestate = result

            response.headers["traceparent"] = traceparent

            if tracestate:
                response.headers["tracestate"] = tracestate

            # Derive trace_id from traceparent for the Server-Timing header.
            # Format: 00-{trace_id}-{span_id}-{flags}  → parts[1] is trace_id.
            parts = traceparent.split("-")
            if len(parts) == 4:
                trace_id = parts[1]
                response.headers["Server-Timing"] = f'traceid;desc="{trace_id}"'

        except Exception:
            logger.debug(
                "TraceparentMiddleware: failed to inject traceparent header",
                exc_info=True,
            )

        return response
