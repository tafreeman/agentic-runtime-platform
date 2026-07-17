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

import base64
import binascii
import re
from typing import Annotated, Any, Literal, Self, Union, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictInt,
    TypeAdapter,
    field_validator,
)

ChatRole = Literal["system", "user", "assistant"]

_IMAGE_DATA_URL_RE = re.compile(
    r"^data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/=\r\n]+)$"
)
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _validate_image_data_url(value: str) -> str:
    """Validate a bounded, raster-only image data URL.

    Playground attachments remain request-local and are never written to
    disk. SVG is deliberately excluded because it is active content in a
    browser.
    """
    match = _IMAGE_DATA_URL_RE.fullmatch(value)
    if match is None:
        raise ValueError("image must be a base64 PNG, JPEG, WebP, or GIF data URL")
    try:
        payload = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image data URL contains invalid base64") from exc
    if not payload:
        raise ValueError("image attachment is empty")
    if len(payload) > _MAX_IMAGE_BYTES:
        raise ValueError("image attachment exceeds the 5 MiB limit")
    return value


class ChatTextPart(BaseModel):
    """Text content inside a multimodal conversation turn."""

    type: Literal["text"] = "text"
    text: str = Field(max_length=100_000)


class ChatImagePart(BaseModel):
    """A request-local raster image sent to a vision-capable model."""

    type: Literal["image_url"] = "image_url"
    url: str = Field(max_length=7_100_000)
    detail: Literal["auto", "low", "high"] = "auto"

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Reject anything but a bounded, well-formed raster data URL."""
        return _validate_image_data_url(value)


ChatContentPart = Annotated[
    Union[ChatTextPart, ChatImagePart], Field(discriminator="type")
]


class ChatMessage(BaseModel):
    """One conversation turn submitted to the chat playground.

    ``content`` is capped well above any real chat turn so a single request
    cannot buffer unbounded memory through the sanitization middleware.
    """

    role: ChatRole
    content: (
        Annotated[str, Field(max_length=100_000)]
        | Annotated[list[ChatContentPart], Field(min_length=1, max_length=12)]
    ) = Field(description="Plain text or provider-neutral text/image content blocks")


class _ChatRequestBase(BaseModel):
    """Fields shared by both chat routing constructors."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    messages: list[ChatMessage] = Field(
        min_length=1,
        max_length=100,
        description="Conversation history, oldest first",
    )
    temperature: float = Field(
        default=0.2, ge=0.0, le=2.0, description="Sampling temperature"
    )


class ModelChatRequest(_ChatRequestBase):
    """Direct-model constructor for ``POST /api/chat``."""

    model: str = Field(
        min_length=1,
        max_length=200,
        description="Full prefixed model id to chat with directly",
    )


class TierChatRequest(_ChatRequestBase):
    """Tier-routed constructor for ``POST /api/chat``."""

    tier: StrictInt = Field(
        ge=1,
        le=5,
        description="Capability tier to resolve through the model router (1-5)",
    )


ChatRequestValue = Union[ModelChatRequest, TierChatRequest]


class ChatRequest(RootModel[ChatRequestValue]):
    """Overloaded request body for ``POST /api/chat``.

    Exactly one routing constructor is accepted:

    * ``for_model`` / ``model`` builds one FULL prefixed model id directly;
    * ``for_tier`` / ``tier`` resolves the configured tier and fallback chain.

    HTTP clients use the equivalent JSON union by sending either ``model`` or
    ``tier``. Supplying both or neither is rejected by the two strict variants.
    """

    @property
    def model(self) -> str | None:
        """Explicit model id, or ``None`` for the tier constructor."""
        return self.root.model if isinstance(self.root, ModelChatRequest) else None

    @property
    def tier(self) -> int | None:
        """Requested tier, or ``None`` for the direct-model constructor."""
        return self.root.tier if isinstance(self.root, TierChatRequest) else None

    @property
    def messages(self) -> list[ChatMessage]:
        """Conversation history shared by both constructors."""
        # cast: with --follow-imports=skip the ratchet sees the union
        # variants' inherited attributes as Any.
        return cast("list[ChatMessage]", self.root.messages)

    @property
    def temperature(self) -> float:
        """Sampling temperature shared by both constructors."""
        return cast("float", self.root.temperature)

    @classmethod
    def for_model(
        cls,
        model: str,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
    ) -> Self:
        """Construct a request targeting one explicit provider/model id."""
        return cls(
            root=ModelChatRequest(
                model=model,
                messages=messages,
                temperature=temperature,
            )
        )

    @classmethod
    def for_tier(
        cls,
        tier: int,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
    ) -> Self:
        """Construct a request whose model is selected by capability tier."""
        return cls(
            root=TierChatRequest(
                tier=tier,
                messages=messages,
                temperature=temperature,
            )
        )


class ChatTokenEvent(BaseModel):
    """Incremental text delta streamed from the model reply."""

    type: Literal["token"] = "token"
    delta: str


class ChatRouteEvent(BaseModel):
    """Selected model for a tier-routed request, emitted before output tokens."""

    type: Literal["route"] = "route"
    requested_tier: int = Field(ge=1, le=5)
    model: str


class ChatMediaEvent(BaseModel):
    """A safe image emitted by a multimodal model response."""

    type: Literal["media"] = "media"
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "image/gif"]
    url: str = Field(max_length=7_100_000)
    alt: str = Field(default="Model-generated image", max_length=300)


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
        ChatRouteEvent,
        ChatTokenEvent,
        ChatMediaEvent,
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
