"""Direct model chat playground route.

Provides ``POST /api/chat`` — a request-scoped SSE stream that sends the
supplied conversation straight to the requested model id via
``langchain.models.get_chat_model`` (bypassing ``SmartModelRouter`` tier
selection) and streams the reply back as typed ``ChatStreamEvent`` frames.
This is the "does this model actually work" probe: real auth/quota/connection
failures surface as safe in-stream ``error`` frames.

Wire contract (source of truth: ``agentic_v2/contracts/chat.py``):

* every frame is ``data: <event JSON>`` followed by a blank line on a
  ``text/event-stream`` body;
* every stream terminates with exactly one ``done`` OR one ``error`` frame;
* model/provider failures (unknown prefix, missing key, 401, 429, connection
  refused) surface as in-stream ``error`` frames on the HTTP 200 response.
  Only FastAPI request validation stays a native 422, and a missing LangChain
  install returns the same 503 convention as ``routes/models.py``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ...contracts.chat import (
    ChatDoneEvent,
    ChatErrorEvent,
    ChatMessage,
    ChatRequest,
    ChatTokenEvent,
)
from ...core.errors import classify_error
from ...core.tenant import TenantContext, get_tenant_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

#: Response headers matching the runs SSE precedent, plus an explicit
#: anti-buffering hint so reverse proxies do not batch token frames.
_SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

# Secret-scrubbing patterns for outbound error messages — a provider error
# string may echo the credential it rejected; never forward it to the client.
# The route fronts EVERY prefix get_chat_model supports, so the patterns cover
# each reachable provider's key shape, not just OpenAI-style ``sk-`` keys:
# GitHub (ghp_/gho_/ghu_/ghs_/ghr_/github_pat_), NVIDIA (nvapi-),
# Google (AIza...), plus generic bearer headers and long hex runs.
_SECRET_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"Bearer\s+\S+"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"nvapi-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)

#: Upper bound on the error text forwarded to the client.
_MAX_ERROR_MESSAGE_LEN = 300


def _safe_error_message(exc: Exception) -> str:
    """Return a scrubbed, truncated error description safe for the wire.

    Redacts bearer tokens and every reachable provider's API-key shape, then
    truncates so a verbose provider error can never leak environment values to
    the browser (or, via the caller's log line, to the server log).
    """
    message = f"{type(exc).__name__}: {exc}"
    for pattern in _SECRET_RES:
        message = pattern.sub("[redacted]", message)
    return message[:_MAX_ERROR_MESSAGE_LEN]


def _extract_text(content: Any) -> str:
    """Extract plain text from a streamed chunk's ``content`` attribute.

    LangChain chunks carry either a plain string or a list of content blocks
    (strings or ``{"type": "text", "text": ...}`` dicts); non-text blocks
    (tool calls, thinking) are skipped.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def _sse_frame(event: ChatTokenEvent | ChatDoneEvent | ChatErrorEvent) -> str:
    """Serialize one chat stream event as an SSE ``data:`` frame."""
    return f"data: {event.model_dump_json()}\n\n"


def _to_langchain_messages(
    messages: Sequence[ChatMessage], message_types: dict[str, Any]
) -> list[Any]:
    """Convert wire ``ChatMessage`` turns to LangChain message objects."""
    return [message_types[m.role](content=m.content) for m in messages]


async def _chat_event_stream(
    request: ChatRequest,
    build_model: Callable[..., Any],
    message_types: dict[str, Any],
) -> AsyncIterator[str]:
    """Stream the model reply as SSE frames, ending in ``done`` or ``error``.

    The model is built INSIDE the generator so every failure — unknown
    prefix, missing key, provider 401/429, connection refused, mid-stream
    drop — lands in the ``except`` arm and is emitted as a terminal in-stream
    ``error`` frame rather than an HTTP 5xx.
    """
    try:
        model = build_model(request.model, temperature=request.temperature)
        lc_messages = _to_langchain_messages(request.messages, message_types)
        async for chunk in model.astream(lc_messages):
            delta = _extract_text(getattr(chunk, "content", ""))
            if delta:
                yield _sse_frame(ChatTokenEvent(delta=delta))
        yield _sse_frame(ChatDoneEvent(model=request.model))
    except Exception as exc:
        code, _should_retry = classify_error(str(exc))
        # Deliberately no exc_info: the raw traceback footer repeats str(exc)
        # verbatim, which may echo the rejected credential — log the same
        # scrubbed text the wire gets ("no secrets in logs" rule).
        safe_message = _safe_error_message(exc)
        logger.warning(
            "Chat stream failed: model=%s, category=%s, error=%s",
            request.model,
            code.value,
            safe_message,
        )
        yield _sse_frame(ChatErrorEvent(message=safe_message, category=code.value))


@router.post("/chat", responses={503: {"description": "Service Unavailable"}})
async def chat_stream(
    request: ChatRequest,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
) -> StreamingResponse:
    """Stream a direct chat completion from one explicitly requested model.

    Routes straight to ``get_chat_model(request.model, ...)`` — no
    ``SmartModelRouter`` tier selection — so a caller can verify that a
    specific provider/model id actually works with the current credentials.
    The ``tenant`` dependency is resolved for its auth side effect, matching
    every other ``/api`` route.
    """
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from ...langchain.models import get_chat_model
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LangChain extras not installed — cannot serve chat: {exc}",
        ) from exc

    logger.info(
        "Chat request: model=%s, messages=%d", request.model, len(request.messages)
    )
    message_types: dict[str, Any] = {
        "system": SystemMessage,
        "user": HumanMessage,
        "assistant": AIMessage,
    }
    return StreamingResponse(
        _chat_event_stream(request, get_chat_model, message_types),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
