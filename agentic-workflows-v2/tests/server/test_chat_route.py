"""Route tests for ``POST /api/chat`` — the direct model chat playground.

Covers:
  * happy path under ``AGENTIC_NO_LLM=1`` (deterministic placeholder stream);
  * exact-model bypass — the route builds the requested id verbatim, proving
    no ``SmartModelRouter`` tier selection happens;
  * provider failures surfacing as scrubbed in-stream ``error`` frames on a
    200 response (never HTTP 5xx);
  * mid-stream failures (token frames, then a terminal ``error`` frame);
  * list-of-content-block chunks and empty-delta skipping;
  * FastAPI-native 422 validation and the 503 missing-LangChain guard;
  * ``ChatStreamEvent`` union round-trips (contract unit tests).
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator, Iterable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

# The route degrades to 503 without langchain-core, so every streaming test
# needs it importable (mirrors tests/langchain/test_no_llm_mode_langchain.py).
pytest.importorskip("langchain_core")

import agentic_v2.langchain.models as lc_models
from agentic_v2.contracts.chat import (
    ChatDoneEvent,
    ChatErrorEvent,
    ChatMediaEvent,
    ChatMessage,
    ChatRequest,
    ChatRouteEvent,
    ChatTokenEvent,
    validate_chat_stream_event,
)
from agentic_v2.models.backends import PLACEHOLDER_RESPONSE_TEXT
from agentic_v2.server.routes.chat import _MAX_ERROR_MESSAGE_LEN, _safe_error_message

FULL_MODEL_ID = "openrouter:meta-llama/llama-3.1-8b-instruct:free"

_SSE_DATA_PREFIX = "data: "

_ERROR_CATEGORIES = {"rate_limited", "auth_error", "not_found", "transient", "unknown"}


def _chat_payload(**overrides: Any) -> dict[str, Any]:
    """Return a valid ``/api/chat`` request body; override fields per test."""
    payload: dict[str, Any] = {
        "model": FULL_MODEL_ID,
        "messages": [{"role": "user", "content": "ping"}],
    }
    return {**payload, **overrides}


def _tier_chat_payload(tier: int = 2, **overrides: Any) -> dict[str, Any]:
    """Return the tier-routed overload of the chat request body."""
    payload = _chat_payload(**overrides)
    payload.pop("model", None)
    payload["tier"] = tier
    return payload


def _parse_sse_events(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Parse ``data: <json>`` SSE lines into event dicts (skips blank lines)."""
    return [
        json.loads(line.removeprefix(_SSE_DATA_PREFIX))
        for line in lines
        if line.startswith(_SSE_DATA_PREFIX)
    ]


def _post_chat_events(
    client: TestClient, payload: dict[str, Any]
) -> tuple[int, dict[str, str], list[dict[str, Any]]]:
    """POST ``/api/chat`` and drain the SSE body into parsed event dicts."""
    with client.stream("POST", "/api/chat", json=payload) as response:
        status = response.status_code
        headers = dict(response.headers)
        events = _parse_sse_events(response.iter_lines())
    return status, headers, events


class _FakeChunk:
    """Stand-in for a LangChain ``AIMessageChunk`` — only ``.content`` is read."""

    def __init__(self, content: Any) -> None:
        self.content = content


class _FakeStreamingModel:
    """Minimal chat model exposing ``astream``; optionally raises mid-stream."""

    def __init__(
        self, chunks: list[_FakeChunk], error: Exception | None = None
    ) -> None:
        self._chunks = chunks
        self._error = error
        self.seen_messages: list[Any] | None = None

    async def astream(self, messages: list[Any]) -> AsyncIterator[_FakeChunk]:
        self.seen_messages = list(messages)
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error


def _install_fake_model(
    monkeypatch: pytest.MonkeyPatch, fake_model: _FakeStreamingModel
) -> list[tuple[str, float]]:
    """Patch ``get_chat_model`` to return *fake_model*; return the call log.

    The route imports ``get_chat_model`` from ``agentic_v2.langchain.models``
    lazily (per request), so patching the module attribute intercepts it.
    """
    calls: list[tuple[str, float]] = []

    def _fake_get_chat_model(
        model_id: str, temperature: float = 0.0
    ) -> _FakeStreamingModel:
        calls.append((model_id, temperature))
        return fake_model

    monkeypatch.setattr(lc_models, "get_chat_model", _fake_get_chat_model)
    return calls


class TestChatStreamHappyPath:
    """AGENTIC_NO_LLM=1 — the key-free deterministic baseline."""

    def test_placeholder_stream_tokens_then_single_done(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTIC_NO_LLM", "1")

        status, headers, events = _post_chat_events(client, _chat_payload())

        assert status == 200
        assert headers["content-type"].startswith("text/event-stream")
        assert headers["cache-control"] == "no-cache"
        assert headers["x-accel-buffering"] == "no"
        token_events = [e for e in events if e["type"] == "token"]
        done_events = [e for e in events if e["type"] == "done"]
        assert len(token_events) >= 1
        assert len(done_events) == 1
        assert events[-1]["type"] == "done"
        assert done_events[0]["model"] == FULL_MODEL_ID
        assert "".join(e["delta"] for e in token_events) == PLACEHOLDER_RESPONSE_TEXT

    def test_placeholder_stream_is_deterministic_across_requests(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTIC_NO_LLM", "1")

        _status_a, _headers_a, first = _post_chat_events(client, _chat_payload())
        _status_b, _headers_b, second = _post_chat_events(client, _chat_payload())

        assert first == second


class TestChatModelBypass:
    """The route builds the exact requested id — no tier routing."""

    def test_builds_exact_requested_model_id_and_temperature(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_model = _FakeStreamingModel([_FakeChunk("pong")])
        calls = _install_fake_model(monkeypatch, fake_model)

        payload = _chat_payload(temperature=0.7)
        status, _headers, events = _post_chat_events(client, payload)

        assert status == 200
        assert calls == [(FULL_MODEL_ID, 0.7)]
        assert [e["type"] for e in events] == ["token", "done"]
        assert events[0]["delta"] == "pong"
        assert events[1]["model"] == FULL_MODEL_ID

    def test_wire_messages_convert_to_langchain_roles(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        fake_model = _FakeStreamingModel([_FakeChunk("ok")])
        calls = _install_fake_model(monkeypatch, fake_model)

        payload = _chat_payload(
            messages=[
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "ping"},
                {"role": "assistant", "content": "pong"},
            ]
        )
        status, _headers, _events = _post_chat_events(client, payload)

        assert status == 200
        assert calls == [(FULL_MODEL_ID, 0.2)]  # default temperature forwarded
        assert fake_model.seen_messages is not None
        assert [type(m) for m in fake_model.seen_messages] == [
            SystemMessage,
            HumanMessage,
            AIMessage,
        ]
        assert [m.content for m in fake_model.seen_messages] == [
            "be brief",
            "ping",
            "pong",
        ]

    def test_multimodal_message_converts_to_text_and_image_blocks(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_model = _FakeStreamingModel([_FakeChunk("described")])
        _install_fake_model(monkeypatch, fake_model)
        image = "data:image/png;base64,aGVsbG8="

        status, _headers, events = _post_chat_events(
            client,
            _chat_payload(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "What is shown?"},
                            {"type": "image_url", "url": image, "detail": "low"},
                        ],
                    }
                ]
            ),
        )

        assert status == 200
        assert [event["type"] for event in events] == ["token", "done"]
        assert fake_model.seen_messages is not None
        assert fake_model.seen_messages[0].content == [
            {"type": "text", "text": "What is shown?"},
            {"type": "image_url", "image_url": {"url": image, "detail": "low"}},
        ]


class TestChatTierRouting:
    """Tier overload resolves the existing candidate chain server-side."""

    def test_tier_selects_model_and_emits_route_before_tokens(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        selected = "lmstudio:qwen2.5-0.5b-instruct"
        fake_model = _FakeStreamingModel([_FakeChunk("routed")])
        calls = _install_fake_model(monkeypatch, fake_model)
        monkeypatch.setattr(
            lc_models,
            "get_model_candidates_for_tier",
            lambda tier: [selected] if tier == 2 else [],
        )

        status, _headers, events = _post_chat_events(
            client, _tier_chat_payload(tier=2, temperature=0.4)
        )

        assert status == 200
        assert calls == [(selected, 0.4)]
        assert [event["type"] for event in events] == ["route", "token", "done"]
        assert events[0] == {
            "type": "route",
            "requested_tier": 2,
            "model": selected,
        }
        assert events[-1]["model"] == selected

    def test_tier_falls_through_constructor_failures(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = "openai:unavailable"
        second = "lmstudio:qwen2.5-0.5b-instruct"
        fake_model = _FakeStreamingModel([_FakeChunk("fallback")])
        calls: list[str] = []

        def _build(model_id: str, temperature: float = 0.0):
            calls.append(model_id)
            if model_id == first:
                raise ValueError("provider unavailable")
            return fake_model

        monkeypatch.setattr(lc_models, "get_chat_model", _build)
        monkeypatch.setattr(
            lc_models,
            "get_model_candidates_for_tier",
            lambda _tier: [first, second],
        )

        status, _headers, events = _post_chat_events(client, _tier_chat_payload())

        assert status == 200
        assert calls == [first, second]
        assert events[0]["type"] == "route"
        assert events[0]["model"] == second
        assert events[-1] == {"type": "done", "model": second}

    def test_tier_with_no_candidates_returns_safe_stream_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            lc_models, "get_model_candidates_for_tier", lambda _tier: []
        )

        status, _headers, events = _post_chat_events(client, _tier_chat_payload())

        assert status == 200
        assert [event["type"] for event in events] == ["error"]
        assert "No available model for tier 2" in events[0]["message"]


class TestChatChunkExtraction:
    """Chunk content may be a str or a list of content blocks."""

    def test_list_content_blocks_flattened_and_empty_deltas_skipped(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_model = _FakeStreamingModel(
            [
                _FakeChunk(
                    [{"type": "text", "text": "alpha"}, {"type": "tool_use"}, " beta"]
                ),
                _FakeChunk(""),
                _FakeChunk([]),
                _FakeChunk(None),
                _FakeChunk("gamma"),
            ]
        )
        _install_fake_model(monkeypatch, fake_model)

        status, _headers, events = _post_chat_events(client, _chat_payload())

        assert status == 200
        assert [e["type"] for e in events] == ["token", "token", "done"]
        assert [e["delta"] for e in events[:2]] == ["alpha beta", "gamma"]

    def test_safe_image_output_is_a_typed_media_event(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        image = "data:image/webp;base64,aGVsbG8="
        fake_model = _FakeStreamingModel(
            [
                _FakeChunk(
                    [
                        {"type": "text", "text": "rendered"},
                        {
                            "type": "image",
                            "source": {
                                "media_type": "image/webp",
                                "data": "aGVsbG8=",
                            },
                            "alt": "Generated chart",
                        },
                    ]
                )
            ]
        )
        _install_fake_model(monkeypatch, fake_model)

        status, _headers, events = _post_chat_events(client, _chat_payload())

        assert status == 200
        assert [event["type"] for event in events] == ["token", "media", "done"]
        assert events[1] == {
            "type": "media",
            "mime_type": "image/webp",
            "url": image,
            "alt": "Generated chart",
        }


class TestChatStreamErrors:
    """Provider failures surface as scrubbed in-stream error frames on 200."""

    def test_auth_failure_is_scrubbed_error_frame_on_200(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise_auth_error(model_id: str, temperature: float = 0.0) -> Any:
            # Bare Exception on purpose: provider SDKs raise arbitrary types.
            raise Exception("401 Unauthorized: Bearer sk-or-abcdefgh12345678 invalid")

        monkeypatch.setattr(lc_models, "get_chat_model", _raise_auth_error)

        status, _headers, events = _post_chat_events(client, _chat_payload())

        assert status == 200
        assert [e["type"] for e in events] == ["error"]
        error = events[0]
        assert error["category"] == "auth_error"
        assert "sk-or-abcdefgh12345678" not in error["message"]
        assert "Bearer sk-" not in error["message"]
        assert "401" in error["message"]  # actionable context is preserved

    def test_mid_stream_failure_yields_tokens_then_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_model = _FakeStreamingModel(
            [_FakeChunk("partial ")], error=ConnectionError("connection refused")
        )
        _install_fake_model(monkeypatch, fake_model)

        status, _headers, events = _post_chat_events(client, _chat_payload())

        assert status == 200
        assert [e["type"] for e in events] == ["token", "error"]
        assert events[0]["delta"] == "partial "
        assert events[1]["category"] == "transient"
        assert "connection refused" in events[1]["message"]

    def test_missing_provider_key_becomes_error_frame(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real missing-key ValueError from the builder stays in-stream."""
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        status, _headers, events = _post_chat_events(
            client, _chat_payload(model="gh:openai/gpt-4o-mini")
        )

        assert status == 200
        assert [e["type"] for e in events] == ["error"]
        assert "GITHUB_TOKEN" in events[0]["message"]
        assert events[0]["category"] in _ERROR_CATEGORIES


class TestSafeErrorMessage:
    """The outbound error scrubber redacts credentials and truncates."""

    def test_scrubs_bearer_and_api_keys_and_truncates(self) -> None:
        exc = RuntimeError(
            "Bearer abc.def.ghi rejected; key sk-proj-abcdef123456 bad; "
            + "x" * (2 * _MAX_ERROR_MESSAGE_LEN)
        )

        message = _safe_error_message(exc)

        assert message.startswith("RuntimeError:")
        assert "abc.def.ghi" not in message
        assert "sk-proj-abcdef123456" not in message
        assert "[redacted]" in message
        assert len(message) <= _MAX_ERROR_MESSAGE_LEN

    def test_scrubs_every_reachable_providers_key_shape(self) -> None:
        """The route fronts every prefix, so every provider's key shape scrubs.

        GitHub / NVIDIA / Google keys do not match the ``sk-`` pattern; a
        provider error echoing one bare (outside a Bearer header) must still
        be redacted before it reaches the wire or the server log.
        """
        secrets = (
            "ghp_abcdefghijklmnop1234",
            "github_pat_abcdefghijklmnopqrst_uv",
            "nvapi-abcdefghijklmnop1234",
            "AIzaSyabcdefghijklmnopqrstuvwxyz012345",
            "0123456789abcdef0123456789abcdef",  # 32-hex (Azure-style)
        )
        for secret in secrets:
            message = _safe_error_message(RuntimeError(f"key {secret} rejected"))
            assert secret not in message, f"leaked: {secret[:8]}..."
            assert "[redacted]" in message


class TestChatRequestValidation:
    """Malformed request bodies stay native FastAPI 422s."""

    def test_empty_messages_list_is_422(self, client: TestClient) -> None:
        response = client.post("/api/chat", json=_chat_payload(messages=[]))
        assert response.status_code == 422

    def test_out_of_range_temperature_is_422(self, client: TestClient) -> None:
        response = client.post("/api/chat", json=_chat_payload(temperature=3.0))
        assert response.status_code == 422

    def test_oversized_messages_list_is_422(self, client: TestClient) -> None:
        turns = [{"role": "user", "content": "hi"}] * 101
        response = client.post("/api/chat", json=_chat_payload(messages=turns))
        assert response.status_code == 422

    def test_oversized_model_id_is_422(self, client: TestClient) -> None:
        response = client.post("/api/chat", json=_chat_payload(model="x" * 201))
        assert response.status_code == 422

    def test_model_and_tier_together_are_422(self, client: TestClient) -> None:
        response = client.post("/api/chat", json=_chat_payload(tier=2))
        assert response.status_code == 422

    def test_model_and_tier_both_missing_are_422(self, client: TestClient) -> None:
        payload = _chat_payload()
        payload.pop("model")
        response = client.post("/api/chat", json=payload)
        assert response.status_code == 422

    @pytest.mark.parametrize("tier", [0, 6, True, "two"])
    def test_invalid_tier_is_422(self, client: TestClient, tier: Any) -> None:
        response = client.post("/api/chat", json=_tier_chat_payload(tier=tier))
        assert response.status_code == 422

    def test_unknown_role_is_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json=_chat_payload(messages=[{"role": "wizard", "content": "hi"}]),
        )
        assert response.status_code == 422

    def test_active_or_unsupported_image_data_is_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json=_chat_payload(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "url": "data:image/svg+xml;base64,PHN2Zz4=",
                            }
                        ],
                    }
                ]
            ),
        )
        assert response.status_code == 422


class TestChatLangchainUnavailable:
    """A missing LangChain install maps to the routes/models.py 503 pattern."""

    def test_unimportable_langchain_core_returns_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A None entry in sys.modules makes the lazy import raise ImportError.
        monkeypatch.setitem(sys.modules, "langchain_core.messages", None)

        response = client.post("/api/chat", json=_chat_payload())

        assert response.status_code == 503
        assert "LangChain" in response.json()["detail"]


class TestChatContracts:
    """ChatStreamEvent union and ChatRequest contract unit tests."""

    def test_union_round_trips_each_variant(self) -> None:
        route = validate_chat_stream_event(
            {"type": "route", "requested_tier": 2, "model": FULL_MODEL_ID}
        )
        token = validate_chat_stream_event({"type": "token", "delta": "hi"})
        done = validate_chat_stream_event({"type": "done", "model": FULL_MODEL_ID})
        error = validate_chat_stream_event(
            {"type": "error", "message": "boom", "category": "auth_error"}
        )
        media = validate_chat_stream_event(
            {
                "type": "media",
                "mime_type": "image/png",
                "url": "data:image/png;base64,aGVsbG8=",
                "alt": "result",
            }
        )

        assert isinstance(route, ChatRouteEvent)
        assert isinstance(token, ChatTokenEvent)
        assert isinstance(done, ChatDoneEvent)
        assert isinstance(error, ChatErrorEvent)
        assert isinstance(media, ChatMediaEvent)
        for event in (route, token, media, done, error):
            round_tripped = validate_chat_stream_event(
                json.loads(event.model_dump_json())
            )
            assert round_tripped == event

    def test_unknown_event_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_chat_stream_event({"type": "bogus", "delta": "hi"})

    def test_chat_request_defaults_and_bounds(self) -> None:
        request = ChatRequest.for_model(
            model=FULL_MODEL_ID,
            messages=[ChatMessage(role="user", content="ping")],
        )
        routed = ChatRequest.for_tier(
            tier=3,
            messages=[ChatMessage(role="user", content="ping")],
        )

        assert request.temperature == 0.2
        assert request.messages[0].role == "user"
        assert routed.model is None
        assert routed.tier == 3
        with pytest.raises(ValidationError):
            ChatRequest.model_validate(_chat_payload(temperature=-0.1))
        with pytest.raises(ValidationError):
            ChatRequest.model_validate(_chat_payload(messages=[]))
