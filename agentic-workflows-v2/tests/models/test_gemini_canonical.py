"""ADR-023 Phase 3 — GeminiBackend.complete_chat canonicalization tests.

Verifies that ``GeminiBackend.complete_chat`` emits the OpenAI-canonical dict
shape:

- ``finish_reason`` is the lowercase canonical token (``stop`` / ``length`` /
  ``content_filter``), not the raw UPPERCASE ``finishReason`` from Gemini.
- ``usage`` is a snake_case mapping with ``prompt_tokens`` /
  ``completion_tokens`` / ``total_tokens`` integer fields, not the raw
  camelCase ``usageMetadata`` block.
- ``tool_calls`` remains ``None`` (Gemini tool-use canonicalization is a
  separate later epic).
- The raw upstream payload survives under ``_raw_gemini`` so telemetry /
  debugging consumers are not regressed.

Runs offline with ``AGENTIC_NO_LLM=1`` — no network, no live keys.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_v2.models.backends_cloud import GeminiBackend

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "backend_responses"
    / "gemini_basic.json"
)


def _load_basic_fixture() -> dict[str, Any]:
    """Load the gemini_basic.json oracle (raw pre-canonicalization shape)."""
    with _FIXTURE_PATH.open(encoding="utf-8") as fp:
        return json.load(fp)


def _build_raw_gemini_api_payload(
    *,
    text: str,
    finish_reason: str,
    prompt_tokens: int,
    candidates_tokens: int,
    total_tokens: int,
) -> dict[str, Any]:
    """Shape an upstream Gemini ``generateContent`` JSON response."""
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text}], "role": "model"},
                "finishReason": finish_reason,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": candidates_tokens,
            "totalTokenCount": total_tokens,
        },
    }


def _patch_gemini_http(backend: GeminiBackend, raw_payload: dict[str, Any]) -> Any:
    """Return a context manager that stubs the Gemini HTTP call.

    Replaces ``backend._get_client`` so ``complete_chat`` never touches the
    network. The returned mock response yields ``raw_payload`` from ``.json()``
    and a no-op ``raise_for_status``.
    """
    mock_response = MagicMock()
    mock_response.json = MagicMock(return_value=raw_payload)
    mock_response.raise_for_status = MagicMock(return_value=None)

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    return patch.object(
        backend,
        "_get_client",
        new=AsyncMock(return_value=mock_client),
    )


@pytest.fixture(autouse=True)
def _force_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin AGENTIC_NO_LLM=1 and supply a dummy GEMINI_API_KEY.

    The dummy key satisfies ``GeminiBackend.__post_init__`` without exposing a
    live secret. The HTTP layer is patched out in every test, so the key is
    never sent anywhere.
    """
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-dummy-key-not-real")


@pytest.mark.unit
async def test_complete_chat_normalizes_finish_reason_and_usage_from_fixture() -> None:
    """The canonical shape uses lowercase finish_reason + snake_case usage.

    Drives the raw Gemini API response from the documented oracle so the test
    stays anchored to the same numbers as the fixture (8 / 9 / 17 tokens,
    ``STOP``).
    """
    oracle = _load_basic_fixture()
    raw_usage = oracle["usage"]
    raw_payload = _build_raw_gemini_api_payload(
        text=oracle["content"],
        finish_reason=oracle["finish_reason"],  # raw "STOP"
        prompt_tokens=raw_usage["promptTokenCount"],
        candidates_tokens=raw_usage["candidatesTokenCount"],
        total_tokens=raw_usage["totalTokenCount"],
    )

    backend = GeminiBackend()
    with _patch_gemini_http(backend, raw_payload):
        result = await backend.complete_chat(
            model="gemini:gemini-1.5-flash",
            messages=[{"role": "user", "content": "Hello!"}],
        )

    # finish_reason: lowercase canonical
    assert result["finish_reason"] == "stop"
    assert isinstance(result["finish_reason"], str)

    # usage: snake_case keys, int values
    usage = result["usage"]
    assert set(usage.keys()) >= {"prompt_tokens", "completion_tokens", "total_tokens"}
    assert isinstance(usage["prompt_tokens"], int)
    assert isinstance(usage["completion_tokens"], int)
    assert isinstance(usage["total_tokens"], int)
    assert usage["prompt_tokens"] == raw_usage["promptTokenCount"]
    assert usage["completion_tokens"] == raw_usage["candidatesTokenCount"]
    assert usage["total_tokens"] == raw_usage["totalTokenCount"]

    # tool_calls: Gemini tool support deferred to a later epic — stays None.
    assert result["tool_calls"] is None

    # Content + model pass-through preserved.
    assert result["content"] == oracle["content"]
    assert result["model"] == "gemini-1.5-flash"

    # Raw upstream survives for telemetry / debugging.
    assert "_raw_gemini" in result
    assert result["_raw_gemini"]["candidates"][0]["finishReason"] == "STOP"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw_reason", "expected"),
    [
        ("STOP", "stop"),
        ("MAX_TOKENS", "length"),
        ("SAFETY", "content_filter"),
        ("RECITATION", "content_filter"),
        ("OTHER", "stop"),
    ],
)
async def test_complete_chat_finish_reason_mapping(
    raw_reason: str, expected: str
) -> None:
    """Every documented Gemini finishReason maps to the OpenAI canonical token."""
    raw_payload = _build_raw_gemini_api_payload(
        text="hi",
        finish_reason=raw_reason,
        prompt_tokens=1,
        candidates_tokens=1,
        total_tokens=2,
    )

    backend = GeminiBackend()
    with _patch_gemini_http(backend, raw_payload):
        result = await backend.complete_chat(
            model="gemini:gemini-1.5-flash",
            messages=[{"role": "user", "content": "hi"}],
        )

    assert result["finish_reason"] == expected


@pytest.mark.unit
async def test_complete_chat_usage_defaults_to_zero_when_metadata_missing() -> None:
    """Missing ``usageMetadata`` yields snake_case zeros, not a raw dict."""
    raw_payload: dict[str, Any] = {
        "candidates": [
            {
                "content": {"parts": [{"text": "ok"}], "role": "model"},
                "finishReason": "STOP",
            }
        ],
        # usageMetadata intentionally absent
    }

    backend = GeminiBackend()
    with _patch_gemini_http(backend, raw_payload):
        result = await backend.complete_chat(
            model="gemini:gemini-1.5-flash",
            messages=[{"role": "user", "content": "hi"}],
        )

    assert result["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
