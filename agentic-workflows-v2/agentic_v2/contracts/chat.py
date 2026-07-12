"""Typed wire format for the ``POST /api/chat`` model playground endpoint.

The server route (``agentic_v2/server/routes/chat.py``) validates request
bodies against :class:`ChatRequest` and emits SSE frames whose JSON payloads
are the :data:`ChatStreamEvent` discriminated union. The client TypeScript
mirrors (``ui/src/api/chat_request.generated.ts`` and
``ui/src/api/chat_stream_event.generated.ts``) are generated from these
models — see ``scripts/generate_ts_types.py`` and the ``wire-format-drift``
CI job.

Stream contract: every stream terminates with exactly one ``done`` OR one
``error`` frame. Model/provider failures surface as in-stream ``error``
frames on the HTTP 200 response, never as HTTP 4xx/5xx.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union, cast

from pydantic import BaseModel, Field, TypeAdapter

ChatRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """One conversation turn submitted to the chat playground.

    ``content`` is capped well above any real chat turn so a single request
    cannot buffer unbounded memory through the sanitization middleware.
    """

    role: ChatRole
    content: str = Field(max_length=100_000)


class ChatRequest(BaseModel):
    """Request body for ``POST /api/chat``.

    ``model`` is a FULL prefixed model id (e.g.
    ``openrouter:meta-llama/llama-3.1-8b-instruct:free``). The endpoint
    builds exactly that model via ``langchain.models.get_chat_model``,
    bypassing ``SmartModelRouter`` tier selection.
    """

    model: str = Field(
        max_length=200, description="Full prefixed model id to chat with"
    )
    messages: list[ChatMessage] = Field(
        min_length=1,
        max_length=100,
        description="Conversation history, oldest first",
    )
    temperature: float = Field(
        default=0.2, ge=0.0, le=2.0, description="Sampling temperature"
    )


class ChatTokenEvent(BaseModel):
    """Incremental text delta streamed from the model reply."""

    type: Literal["token"] = "token"
    delta: str


class ChatDoneEvent(BaseModel):
    """Terminal frame: the reply for ``model`` completed normally."""

    type: Literal["done"] = "done"
    model: str


class ChatErrorEvent(BaseModel):
    """Terminal frame: the stream failed.

    ``category`` is an :class:`agentic_v2.core.errors.ErrorCode` value
    derived via ``classify_error`` (e.g. ``auth_error``, ``rate_limited``).
    ``message`` is scrubbed of bearer tokens and API keys server-side before
    it reaches the wire.
    """

    type: Literal["error"] = "error"
    message: str
    category: str


ChatStreamEvent = Annotated[
    Union[
        ChatTokenEvent,
        ChatDoneEvent,
        ChatErrorEvent,
    ],
    Field(discriminator="type"),
]

_adapter: TypeAdapter[ChatStreamEvent] = TypeAdapter(ChatStreamEvent)


def validate_chat_stream_event(payload: dict[str, Any]) -> ChatStreamEvent:
    """Validate a raw dict against the ChatStreamEvent union.

    Raises pydantic.ValidationError (a ValueError subclass) on mismatch.
    """
    return cast("ChatStreamEvent", _adapter.validate_python(payload))
