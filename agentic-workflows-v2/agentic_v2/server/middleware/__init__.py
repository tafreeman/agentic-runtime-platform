"""ASGI middleware wrappers for the Agentic Workflows V2 server."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_FAIL_OPEN_ENV_VAR = "AGENTIC_SANITIZER_FAIL_OPEN"
_SANITIZER_NOT_CONFIGURED = object()


def _fail_open_enabled() -> bool:
    """Return True when the operator has explicitly opted into fail-open behavior."""
    return os.environ.get(_FAIL_OPEN_ENV_VAR, "").strip() == "1"


class SanitizationASGIMiddleware(BaseHTTPMiddleware):
    """Starlette BaseHTTPMiddleware that applies prompt sanitization to JSON request
    bodies.

    Reads ``app.state.sanitization`` (a :class:`~agentic_v2.middleware.sanitization.SanitizationMiddleware`
    instance) to process incoming request bodies.  Only JSON payloads are
    inspected; all other content types pass through unchanged.

    Classifications:
        * ``clean`` / ``requires_approval`` — pass through unmodified.
        * ``redacted`` — replace the request body with the sanitized text.
        * ``blocked`` — return HTTP 422 immediately.

    Fail-closed behavior:
        On any unexpected detector exception, the middleware returns HTTP 500
        with ``{"detail": "Internal sanitization error"}`` rather than passing
        the request through unsanitized. Recoverable body-decode errors
        (``UnicodeDecodeError`` / ``json.JSONDecodeError``) are logged and
        similarly fail-closed. Set ``AGENTIC_SANITIZER_FAIL_OPEN=1`` to
        temporarily restore legacy fail-open behavior (not recommended).

        When ``app.state.sanitization`` is missing or explicitly ``None``
        (initialization failed), the middleware returns HTTP 503 unless
        ``AGENTIC_SANITIZER_FAIL_OPEN=1`` is set — in which case requests are
        passed through with sanitization disabled.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        sanitizer = getattr(
            request.app.state, "sanitization", _SANITIZER_NOT_CONFIGURED
        )
        if sanitizer is _SANITIZER_NOT_CONFIGURED or sanitizer is None:
            if _fail_open_enabled():
                return await call_next(request)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Service unavailable: sanitization layer not initialized"
                },
            )

        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            return await call_next(request)

        body_bytes, body_error = await self._read_body(request)
        if body_error is not None:
            return body_error
        if body_bytes is None:
            # Fail-open after a body-read error: forward the original request
            # without sanitizing it.
            return await call_next(request)

        outcome = await self._sanitize_request(request, sanitizer, body_bytes)
        if isinstance(outcome, JSONResponse):
            return outcome

        # ``outcome`` is the (possibly rebuilt) request to forward downstream.
        return await call_next(outcome)

    async def _read_body(
        self, request: Request
    ) -> tuple[bytes | None, JSONResponse | None]:
        """Read the request body and classify the outcome.

        Returns one of:

        * ``(body, None)`` — read succeeded; proceed to sanitize.
        * ``(None, response)`` — fail-closed error response to return.
        * ``(None, None)`` — fail-open after an error; forward the original
          request without sanitizing.

        Decode/JSON errors fail closed with HTTP 400; any other error fails
        closed with HTTP 500. Both honor ``AGENTIC_SANITIZER_FAIL_OPEN``.
        """
        try:
            return await request.body(), None
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.exception("Sanitization middleware: body decode error")
            if _fail_open_enabled():
                return None, None
            return None, JSONResponse(
                status_code=400,
                content={"detail": "Malformed request body"},
            )
        except Exception:
            logger.exception("Sanitization middleware error — request rejected")
            if _fail_open_enabled():
                return None, None
            return None, JSONResponse(
                status_code=500,
                content={"detail": "Internal sanitization error"},
            )

    async def _sanitize_request(
        self, request: Request, sanitizer: Any, body_bytes: bytes
    ) -> Request | JSONResponse:
        """Sanitize the body and return either a response or a request to forward.

        Returns a :class:`JSONResponse` when the request is blocked or an
        unexpected error occurs (fail-closed unless fail-open is enabled).
        Otherwise returns the original or sanitized-body :class:`Request`.
        """
        try:
            body_text = body_bytes.decode("utf-8", errors="replace")
            result = await sanitizer.process(body_text, {"source": "api_request"})

            if result.classification == "blocked":
                return JSONResponse(
                    status_code=422,
                    content={"detail": "Request blocked by sanitization policy"},
                )

            if result.classification == "redacted":
                # Rebuild request with sanitized body
                sanitized = result.sanitized_text.encode("utf-8")

                async def receive():
                    return {
                        "type": "http.request",
                        "body": sanitized,
                        "more_body": False,
                    }

                return Request(request.scope, receive)
            return request
        except Exception:
            logger.exception("Sanitization middleware error — request rejected")
            if _fail_open_enabled():
                return request
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal sanitization error"},
            )
