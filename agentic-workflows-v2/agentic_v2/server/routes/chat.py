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
    ChatImagePart,
    ChatMediaEvent,
    ChatMessage,
    ChatRequest,
    ChatRouteEvent,
    ChatTextPart,
    ChatTokenEvent,
    _validate_image_data_url,
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

    Redacts bearer tokens and every reachable provider's API-key shape,
    then truncates so a verbose provider error can never leak
    environment values to the browser (or, via the caller's log line, to
    the server log).
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


def _extract_media(content: Any) -> list[ChatMediaEvent]:
    """Extract safe raster image blocks from a model response chunk.

    LangChain integrations expose several provider block shapes. Only
    HTTPS URLs and validated raster data URLs cross the browser
    boundary; SVG and executable/data content are ignored.
    """
    if not isinstance(content, list):
        return []
    events: list[ChatMediaEvent] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        raw_url: Any = None
        mime = block.get("mime_type") or block.get("media_type")
        alt = block.get("alt") or "Model-generated image"
        if block_type in {"image_url", "output_image"}:
            image_url = block.get("image_url")
            raw_url = image_url.get("url") if isinstance(image_url, dict) else image_url
            raw_url = raw_url or block.get("url")
        elif block_type == "image":
            raw_url = block.get("url")
            source = block.get("source")
            if raw_url is None and isinstance(source, dict):
                source_mime = source.get("media_type")
                source_data = source.get("data")
                if isinstance(source_mime, str) and isinstance(source_data, str):
                    mime = source_mime
                    raw_url = f"data:{source_mime};base64,{source_data}"
        if not isinstance(raw_url, str):
            continue
        if raw_url.startswith("data:image/"):
            try:
                _validate_image_data_url(raw_url)
            except ValueError:
                continue
            mime = raw_url[5 : raw_url.index(";")]
        elif raw_url.startswith("https://"):
            if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                continue
        else:
            continue
        if mime in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            events.append(
                ChatMediaEvent(mime_type=mime, url=raw_url, alt=str(alt)[:300])
            )
    return events


def _sse_frame(
    event: (
        ChatRouteEvent
        | ChatTokenEvent
        | ChatMediaEvent
        | ChatDoneEvent
        | ChatErrorEvent
    ),
) -> str:
    """Serialize one chat stream event as an SSE ``data:`` frame."""
    return f"data: {event.model_dump_json()}\n\n"


def _to_langchain_messages(
    messages: Sequence[ChatMessage], message_types: dict[str, Any]
) -> list[Any]:
    """Convert wire ``ChatMessage`` turns to LangChain message objects."""
    converted: list[Any] = []
    for message in messages:
        if isinstance(message.content, str):
            content: Any = message.content
        else:
            content = []
            for part in message.content:
                if isinstance(part, ChatTextPart):
                    content.append({"type": "text", "text": part.text})
                elif isinstance(part, ChatImagePart):
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": part.url, "detail": part.detail},
                        }
                    )
        converted.append(message_types[message.role](content=content))
    return converted


async def _chat_event_stream(
    request: ChatRequest,
    build_model: Callable[..., Any],
    message_types: dict[str, Any],
    get_candidates: Callable[[int], Sequence[str]] | None = None,
) -> AsyncIterator[str]:
    """Stream the model reply as SSE frames, ending in ``done`` or ``error``.

    The model is built INSIDE the generator so every failure — unknown
    prefix, missing key, provider 401/429, connection refused, mid-stream
    drop — lands in the ``except`` arm and is emitted as a terminal in-stream
    ``error`` frame rather than an HTTP 5xx.
    """
    try:
        if request.model is not None:
            selected_model = request.model
            model = build_model(selected_model, temperature=request.temperature)
        else:
            if request.tier is None or get_candidates is None:
                raise ValueError("tier routing is unavailable")
            candidates = list(get_candidates(request.tier))
            model = None
            selected_model = ""
            last_error: Exception | None = None
            for candidate in candidates:
                try:
                    model = build_model(candidate, temperature=request.temperature)
                    selected_model = candidate
                    break
                except (ImportError, ValueError) as exc:
                    last_error = exc
            if model is None:
                raise ValueError(
                    f"No available model for tier {request.tier}. "
                    f"Checked: {candidates}. Last error: {last_error}"
                )
            yield _sse_frame(
                ChatRouteEvent(
                    requested_tier=request.tier,
                    model=selected_model,
                )
            )

        lc_messages = _to_langchain_messages(request.messages, message_types)
        emitted_media: set[str] = set()
        async for chunk in model.astream(lc_messages):
            content = getattr(chunk, "content", "")
            delta = _extract_text(content)
            if delta:
                yield _sse_frame(ChatTokenEvent(delta=delta))
            for media in _extract_media(content):
                if media.url not in emitted_media:
                    emitted_media.add(media.url)
                    yield _sse_frame(media)
        yield _sse_frame(ChatDoneEvent(model=selected_model))
    except Exception as exc:
        code, _should_retry = classify_error(str(exc))
        # Deliberately no exc_info: the raw traceback footer repeats str(exc)
        # verbatim, which may echo the rejected credential — log the same
        # scrubbed text the wire gets ("no secrets in logs" rule).
        safe_message = _safe_error_message(exc)
        request_target = request.model or f"tier:{request.tier}"
        logger.warning(
            "Chat stream failed: model=%s, category=%s, error=%s",
            request_target,
            code.value,
            safe_message,
        )
        yield _sse_frame(ChatErrorEvent(message=safe_message, category=code.value))


@router.post("/chat", responses={503: {"description": "Service Unavailable"}})
async def chat_stream(
    request: ChatRequest,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)] = None,
) -> StreamingResponse:
    """Stream a chat completion from an explicit model or capability tier.

    Model requests route straight to ``get_chat_model``. Tier requests resolve
    the existing configured candidate/fallback chain and emit a ``route`` SSE
    event naming the selected model before output tokens.
    The ``tenant`` dependency is resolved for its auth side effect, matching
    every other ``/api`` route.
    """
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from ...langchain.models import get_chat_model, get_model_candidates_for_tier
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LangChain extras not installed — cannot serve chat: {exc}",
        ) from exc

    request_target = request.model or f"tier:{request.tier}"
    logger.info(
        "Chat request: target=%s, messages=%d", request_target, len(request.messages)
    )
    message_types: dict[str, Any] = {
        "system": SystemMessage,
        "user": HumanMessage,
        "assistant": AIMessage,
    }
    return StreamingResponse(
        _chat_event_stream(
            request,
            get_chat_model,
            message_types,
            get_model_candidates_for_tier,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
