"""Phase 3 (ADR-023 Option A): canonical Ollama complete_chat dict shape.

The reasoning-model open decision (``ollama-thinking-marker``) is resolved
in favour of a separate top-level ``thinking`` key.  ``content`` MUST stay
empty when the underlying Ollama response only populated ``message.thinking``
(qwen3 / deepseek-r1 / phi4-reasoning style "thinking-only" turn).  The raw
upstream payload is preserved under ``_raw_ollama`` for round-trip oracles.

Run with ``AGENTIC_NO_LLM=1`` — no live keys, no network (the httpx client
is mocked).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.models.backends_local import OllamaBackend

# Path to the synthetic regression-oracle fixture pinned in Phase 0.
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "backend_responses"
    / "ollama_thinking.json"
)


class _StubResponse:
    """Minimal stand-in for ``httpx.Response`` exposing only what the
    ``OllamaBackend.complete_chat`` code path touches: ``raise_for_status``
    and ``json()``.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - trivial
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _StubAsyncClient:
    """Minimal stand-in for ``httpx.AsyncClient`` returning a canned
    ``/api/chat`` payload.  Only ``post`` and ``is_closed`` are used by the
    code under test in this scenario.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.is_closed = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, json: dict[str, Any]) -> _StubResponse:
        self.calls.append((url, json))
        return _StubResponse(self._payload)

    async def aclose(self) -> None:  # pragma: no cover - trivial
        self.is_closed = True


def _load_fixture() -> dict[str, Any]:
    with _FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _raw_ollama_thinking_payload(canonical_fixture: dict[str, Any]) -> dict[str, Any]:
    """Synthesize the raw ``/api/chat`` payload Ollama would have returned to
    produce the canonical fixture: ``message.content`` empty, ``message.thinking``
    populated with the reasoning text.
    """
    return {
        "model": canonical_fixture["model"],
        "message": {
            "role": "assistant",
            "content": "",
            "thinking": canonical_fixture["thinking"],
        },
        "done": True,
    }


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
    raw = _raw_ollama_thinking_payload(canonical)

    backend = OllamaBackend()
    backend._client = _StubAsyncClient(raw)  # type: ignore[assignment]

    result = await backend.complete_chat(
        model="ollama:qwen3:8b",
        messages=[{"role": "user", "content": "hi"}],
    )

    # Separation guarantee (the open-decision resolution).
    assert "thinking" in result, "canonical shape must expose a top-level 'thinking' key"
    assert result["thinking"] == canonical["thinking"], (
        "thinking text must round-trip verbatim from message.thinking"
    )
    assert result["thinking"] != "", "fixture is a thinking-only response; thinking must be non-empty"

    # Content stays empty — no silent fold-in of thinking into content.
    assert result["content"] == "", (
        f"content must remain empty for a thinking-only response (got {result['content']!r}); "
        "ADR-023 Phase 3 forbids inline-marker fold-in"
    )

    # Other canonical fields preserved.
    assert result["tool_calls"] is None
    assert result["finish_reason"] == "stop"
    assert result["model"] == "qwen3:8b"

    # Raw upstream payload preserved for Phase 4 round-trip oracles.
    assert result["_raw_ollama"] == raw


@pytest.mark.unit
async def test_complete_chat_normal_response_thinking_is_empty_string() -> None:
    """Non-reasoning-model response: ``message.content`` populated, no
    ``message.thinking`` field.  ``thinking`` must default to ``""`` (not None,
    not missing) so downstream consumers can read the key unconditionally.
    """
    raw = {
        "model": "llama3.2",
        "message": {
            "role": "assistant",
            "content": "Hello! How can I help you today?",
        },
        "done": True,
    }

    backend = OllamaBackend()
    backend._client = _StubAsyncClient(raw)  # type: ignore[assignment]

    result = await backend.complete_chat(
        model="ollama:llama3.2",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result["content"] == "Hello! How can I help you today?"
    assert result["thinking"] == "", (
        "thinking key must always be present; absent upstream field => empty string"
    )
    assert result["tool_calls"] is None
    assert result["finish_reason"] == "stop"
    assert result["model"] == "llama3.2"
