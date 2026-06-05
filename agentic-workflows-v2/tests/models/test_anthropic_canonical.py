"""ADR-023 Phase 3: canonicalized AnthropicBackend.complete_chat shape.

Verifies that ``AnthropicBackend.complete_chat`` emits the OpenAI-flavoured
canonical dict shape (``finish_reason`` mapped, ``tool_calls`` reshaped to
``{id, type, function: {name, arguments}}``) while preserving the raw
Anthropic payload under ``_raw_anthropic``.

The pre-Phase-3 fixture (``anthropic_basic.json``) captures the *adapter
return* shape from before the canonicalization landed. We use it as the
source-of-truth for the underlying upstream response so we can reconstruct
a realistic Anthropic API payload, feed it through the adapter via a mocked
``httpx`` client, and assert the new canonical shape.

Runs with ``AGENTIC_NO_LLM=1`` — no live keys, no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "backend_responses"
    / "anthropic_basic.json"
)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enforce the offline-only contract for this module."""
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _build_raw_anthropic_response(
    *,
    text: str,
    tool_uses: list[dict[str, Any]],
    stop_reason: str,
    model: str,
    usage: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct a raw Anthropic /v1/messages response payload."""
    content_blocks: list[dict[str, Any]] = []
    if text:
        content_blocks.append({"type": "text", "text": text})
    for tu in tool_uses:
        content_blocks.append(
            {
                "type": "tool_use",
                "id": tu["id"],
                "name": tu["name"],
                "input": tu["input"],
            }
        )
    return {
        "id": "msg_test_canonical",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": stop_reason,
        "usage": usage,
    }


def _patch_anthropic_client(monkeypatch: pytest.MonkeyPatch, raw_response: dict[str, Any]):
    """Patch AnthropicBackend._get_client to return a mock that yields raw_response."""
    from agentic_v2.models import backends_cloud

    mock_response = MagicMock()
    mock_response.json = MagicMock(return_value=raw_response)
    mock_response.raise_for_status = MagicMock(return_value=None)

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    async def _fake_get_client(self):  # type: ignore[no-untyped-def]
        return mock_client

    monkeypatch.setattr(
        backends_cloud.AnthropicBackend, "_get_client", _fake_get_client
    )
    return mock_client


@pytest.mark.unit
async def test_finish_reason_tool_calls_when_tools_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tool_use stop_reason maps to OpenAI 'tool_calls'."""
    from agentic_v2.models.backends_cloud import AnthropicBackend

    fixture = _load_fixture()
    raw = _build_raw_anthropic_response(
        text=fixture["content"],
        tool_uses=[
            {"id": tc["id"], "name": tc["name"], "input": tc["input"]}
            for tc in fixture["tool_calls"]
        ],
        # In Phase 3 we test the mapping: when a tool_use block is present
        # upstream, the real Anthropic stop_reason would be "tool_use".
        stop_reason="tool_use",
        model=fixture["model"],
        usage=fixture["usage"],
    )
    _patch_anthropic_client(monkeypatch, raw)

    backend = AnthropicBackend(api_key="test-key-not-real")
    result = await backend.complete_chat(
        model="anthropic:claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "Hello!"}],
    )

    assert result["finish_reason"] == "tool_calls"


@pytest.mark.unit
async def test_finish_reason_stop_when_end_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """end_turn stop_reason maps to OpenAI 'stop'."""
    from agentic_v2.models.backends_cloud import AnthropicBackend

    raw = _build_raw_anthropic_response(
        text="Hello! How can I help you today?",
        tool_uses=[],
        stop_reason="end_turn",
        model="claude-3-5-sonnet-20241022",
        usage={"input_tokens": 12, "output_tokens": 10},
    )
    _patch_anthropic_client(monkeypatch, raw)

    backend = AnthropicBackend(api_key="test-key-not-real")
    result = await backend.complete_chat(
        model="anthropic:claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "Hello!"}],
    )

    assert result["finish_reason"] == "stop"
    assert result["tool_calls"] is None


@pytest.mark.unit
async def test_tool_calls_are_openai_shaped(monkeypatch: pytest.MonkeyPatch) -> None:
    """tool_use blocks are reshaped to OpenAI's tool_calls dict shape."""
    from agentic_v2.models.backends_cloud import AnthropicBackend

    fixture = _load_fixture()
    raw = _build_raw_anthropic_response(
        text=fixture["content"],
        tool_uses=[
            {"id": tc["id"], "name": tc["name"], "input": tc["input"]}
            for tc in fixture["tool_calls"]
        ],
        stop_reason="tool_use",
        model=fixture["model"],
        usage=fixture["usage"],
    )
    _patch_anthropic_client(monkeypatch, raw)

    backend = AnthropicBackend(api_key="test-key-not-real")
    result = await backend.complete_chat(
        model="anthropic:claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "Hello!"}],
    )

    tool_calls = result["tool_calls"]
    assert isinstance(tool_calls, list)
    assert len(tool_calls) == 1
    call = tool_calls[0]
    # OpenAI-canonical keys.
    assert set(call.keys()) == {"id", "type", "function"}
    assert call["type"] == "function"
    assert call["id"] == "toolu_01A09q90qw90lq917835lq9"
    # function sub-dict.
    assert set(call["function"].keys()) == {"name", "arguments"}
    assert call["function"]["name"] == "get_weather"
    # arguments must be a JSON STRING, not a dict (OpenAI shape).
    assert isinstance(call["function"]["arguments"], str)
    assert json.loads(call["function"]["arguments"]) == {
        "location": "San Francisco, CA"
    }


@pytest.mark.unit
async def test_usage_keys_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic usage is passed through unchanged (input_tokens/output_tokens)."""
    from agentic_v2.models.backends_cloud import AnthropicBackend

    raw = _build_raw_anthropic_response(
        text="Hi.",
        tool_uses=[],
        stop_reason="end_turn",
        model="claude-3-5-sonnet-20241022",
        usage={"input_tokens": 42, "output_tokens": 7},
    )
    _patch_anthropic_client(monkeypatch, raw)

    backend = AnthropicBackend(api_key="test-key-not-real")
    result = await backend.complete_chat(
        model="anthropic:claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "hi"}],
    )

    usage = result["usage"]
    assert "input_tokens" in usage
    assert "output_tokens" in usage
    assert usage["input_tokens"] == 42
    assert usage["output_tokens"] == 7


@pytest.mark.unit
async def test_raw_anthropic_payload_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The original upstream payload is retrievable under _raw_anthropic."""
    from agentic_v2.models.backends_cloud import AnthropicBackend

    raw = _build_raw_anthropic_response(
        text="Hi.",
        tool_uses=[{"id": "toolu_x", "name": "echo", "input": {"v": 1}}],
        stop_reason="tool_use",
        model="claude-3-5-sonnet-20241022",
        usage={"input_tokens": 1, "output_tokens": 2},
    )
    _patch_anthropic_client(monkeypatch, raw)

    backend = AnthropicBackend(api_key="test-key-not-real")
    result = await backend.complete_chat(
        model="anthropic:claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert "_raw_anthropic" in result
    assert result["_raw_anthropic"]["stop_reason"] == "tool_use"
    # Raw content block list is preserved (vs the OpenAI-shaped tool_calls).
    raw_content = result["_raw_anthropic"]["content"]
    assert any(b.get("type") == "tool_use" for b in raw_content)


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_stop_reason,expected_finish_reason",
    [
        ("end_turn", "stop"),
        ("max_tokens", "length"),
        ("tool_use", "tool_calls"),
        ("stop_sequence", "stop"),
        ("unknown_future_value", "unknown_future_value"),  # fallback pass-through
    ],
)
async def test_stop_reason_mapping(
    monkeypatch: pytest.MonkeyPatch,
    raw_stop_reason: str,
    expected_finish_reason: str,
) -> None:
    """Every documented Anthropic stop_reason value maps as specified."""
    from agentic_v2.models.backends_cloud import AnthropicBackend

    raw = _build_raw_anthropic_response(
        text="x",
        tool_uses=[],
        stop_reason=raw_stop_reason,
        model="claude-3-5-sonnet-20241022",
        usage={"input_tokens": 1, "output_tokens": 1},
    )
    _patch_anthropic_client(monkeypatch, raw)

    backend = AnthropicBackend(api_key="test-key-not-real")
    result = await backend.complete_chat(
        model="anthropic:claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "x"}],
    )

    assert result["finish_reason"] == expected_finish_reason
