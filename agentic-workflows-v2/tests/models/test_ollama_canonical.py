"""Phase 3 (ADR-023 Option A): canonical Ollama complete_chat dict shape.

The reasoning-model open decision (``ollama-thinking-marker``) is resolved
in favour of a separate top-level ``thinking`` key.  ``content`` MUST stay
empty when the underlying Ollama response only populated ``message.thinking``
(qwen3 / deepseek-r1 / phi4-reasoning style "thinking-only" turn).  The raw
upstream payload is preserved under ``_raw_ollama`` for round-trip oracles.

ADR-036: ``OllamaBackend`` is backed by the official ``ollama.AsyncClient``
rather than hand-rolled ``httpx`` calls. These tests stub the SDK client's
``chat``/``generate`` coroutines and feed canned ``ollama`` response models,
asserting the canonical output dict is unchanged by the transport swap.

Run with ``AGENTIC_NO_LLM=1`` — no live keys, no network (the SDK client is
replaced with a stub).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import ollama
import pytest

from agentic_v2.models.backends_local import OllamaBackend

# Path to the synthetic regression-oracle fixture pinned in Phase 0.
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "backend_responses"
    / "ollama_thinking.json"
)


class _StubAsyncClient:
    """Minimal stand-in for ``ollama.AsyncClient``.

    Exposes only the coroutines the code under test calls — ``chat`` and
    ``generate`` — returning a canned ``ollama`` response model and recording
    the keyword arguments it was invoked with (so tests can assert that, e.g.,
    ``think`` was forwarded).
    """

    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def chat(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


def _load_fixture() -> dict[str, Any]:
    with _FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _raw_chat_response(
    *, content: str, thinking: str, model: str
) -> ollama.ChatResponse:
    """Build the ``ChatResponse`` the SDK would return for the given message."""
    return ollama.ChatResponse(
        model=model,
        done=True,
        message=ollama.Message(role="assistant", content=content, thinking=thinking),
    )


@pytest.fixture(autouse=True)
def _force_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard-set AGENTIC_NO_LLM=1 for this module per ADR-023 test policy."""
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    assert os.environ["AGENTIC_NO_LLM"] == "1"


@pytest.mark.unit
async def test_complete_chat_separates_thinking_from_content() -> None:
    """Reasoning-model response: ``message.thinking`` populated, ``message.content``
    empty.  The canonical dict MUST surface ``thinking`` as its own top-level
    key and leave ``content`` empty rather than folding thinking into content.
    """
    canonical = _load_fixture()
    response = _raw_chat_response(
        content="", thinking=canonical["thinking"], model=canonical["model"]
    )

    backend = OllamaBackend()
    backend._client = _StubAsyncClient(response)  # type: ignore[assignment]

    result = await backend.complete_chat(
        model="ollama:qwen3:8b",
        messages=[{"role": "user", "content": "hi"}],
    )

    # Separation guarantee (the open-decision resolution).
    assert (
        "thinking" in result
    ), "canonical shape must expose a top-level 'thinking' key"
    assert (
        result["thinking"] == canonical["thinking"]
    ), "thinking text must round-trip verbatim from message.thinking"
    assert (
        result["thinking"] != ""
    ), "fixture is a thinking-only response; thinking must be non-empty"

    # Content stays empty — no silent fold-in of thinking into content.
    assert result["content"] == "", (
        f"content must remain empty for a thinking-only response (got {result['content']!r}); "
        "ADR-023 Phase 3 forbids inline-marker fold-in"
    )

    # Other canonical fields preserved.
    assert result["tool_calls"] is None
    assert result["finish_reason"] == "stop"
    assert result["model"] == "qwen3:8b"

    # Raw upstream payload preserved for Phase 4 round-trip oracles. ADR-036:
    # this is now the SDK model dump rather than the raw server JSON, but it
    # still carries the full upstream message verbatim.
    assert result["_raw_ollama"] == response.model_dump()


@pytest.mark.unit
async def test_complete_chat_normal_response_thinking_is_empty_string() -> None:
    """Non-reasoning-model response: ``message.content`` populated, no
    ``message.thinking`` field.  ``thinking`` must default to ``""`` (not None,
    not missing) so downstream consumers can read the key unconditionally.
    """
    response = ollama.ChatResponse(
        model="llama3.2",
        done=True,
        message=ollama.Message(
            role="assistant", content="Hello! How can I help you today?"
        ),
    )

    backend = OllamaBackend()
    backend._client = _StubAsyncClient(response)  # type: ignore[assignment]

    result = await backend.complete_chat(
        model="ollama:llama3.2",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result["content"] == "Hello! How can I help you today?"
    assert (
        result["thinking"] == ""
    ), "thinking key must always be present; absent upstream field => empty string"
    assert result["tool_calls"] is None
    assert result["finish_reason"] == "stop"
    assert result["model"] == "llama3.2"


@pytest.mark.unit
async def test_complete_chat_normalises_tool_calls_to_dicts() -> None:
    """SDK ``ToolCall`` objects must surface as JSON-able ``list[dict]`` with the
    historical ``{"function": {"name", "arguments"}}`` shape."""
    response = ollama.ChatResponse(
        model="qwen3:8b",
        done=True,
        message=ollama.Message(
            role="assistant",
            content="",
            tool_calls=[
                ollama.Message.ToolCall(
                    function=ollama.Message.ToolCall.Function(
                        name="get_weather", arguments={"city": "Paris"}
                    )
                )
            ],
        ),
    )

    backend = OllamaBackend()
    backend._client = _StubAsyncClient(response)  # type: ignore[assignment]

    result = await backend.complete_chat(
        model="ollama:qwen3:8b",
        messages=[{"role": "user", "content": "weather in Paris?"}],
        tools=[{"type": "function", "function": {"name": "get_weather"}}],
    )

    tool_calls = result["tool_calls"]
    assert isinstance(tool_calls, list) and len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert tool_calls[0]["function"]["arguments"] == {"city": "Paris"}


@pytest.mark.unit
async def test_complete_chat_forwards_think_opt_in() -> None:
    """When the backend is configured with ``think=True`` the parameter must be
    forwarded to the SDK ``chat`` call; the default leaves it ``None``."""
    response = ollama.ChatResponse(
        model="qwen3:8b",
        done=True,
        message=ollama.Message(role="assistant", content="ok"),
    )

    backend = OllamaBackend(think=True)
    stub = _StubAsyncClient(response)
    backend._client = stub  # type: ignore[assignment]

    await backend.complete_chat(
        model="ollama:qwen3:8b",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert stub.calls[0]["think"] is True


@pytest.mark.unit
async def test_complete_prompt_path_falls_back_to_thinking() -> None:
    """The raw-prompt ``complete()`` path returns ``response`` text, falling back to
    ``thinking`` when the answer text is blank (reasoning-only turn)."""
    response = ollama.GenerateResponse(
        model="qwen3:8b",
        done=True,
        response="",
        thinking="Let me reason about this.",
    )

    backend = OllamaBackend()
    backend._client = _StubAsyncClient(response)  # type: ignore[assignment]

    text = await backend.complete(model="ollama:qwen3:8b", prompt="hi")

    assert text == "Let me reason about this."
