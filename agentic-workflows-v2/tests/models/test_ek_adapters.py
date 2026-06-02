"""ADR-023 Phase 4: conformance suite for ``agentic_v2.models.ek_adapters``.

Proves that the pure mapper between the Phase-3-canonical runtime dict and
the ExecutionKit ``LLMResponse`` / ``ToolCall`` / error contracts is
loss-less across all currently-supported backends.

This module is the **only** import site of ``ek_adapters`` in the repo —
the hot path remains untouched until Phase 5.

Runs offline with ``AGENTIC_NO_LLM=1`` — no live keys, no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ExecutionKit value types + error tree (ADR-023 Option A′: single package).
# Guard the import (and the downstream ``ek_adapters`` import, which itself
# depends on ``executionkit``) so this conformance suite skips gracefully when
# run in an environment where ExecutionKit is not installed.
try:
    from executionkit.errors import (
        PermanentError,
        ProviderError,
        RateLimitError,
    )

    from agentic_v2.models.ek_adapters import (
        dict_to_llm_response,
        llm_response_to_dict,
        map_http_error,
    )
except ImportError:  # pragma: no cover - guarded for isolated environments
    pytest.skip(
        "executionkit not installed (ADR-023 dependency); "
        "Phase 4 conformance suite is skipped in this environment.",
        allow_module_level=True,
    )

FIXTURE_DIR = (
    Path(__file__).parent.parent / "fixtures" / "backend_responses"
)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enforce the offline-only contract for this module."""
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")


def _load(name: str) -> dict[str, Any]:
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Fixture canonicalization helpers
# ---------------------------------------------------------------------------
#
# The JSON fixtures pin the *pre*-Phase-3 raw adapter shape for regression. To
# feed them through the EK adapter (which assumes the post-Phase-3 canonical
# OpenAI-flavoured dict) we apply the documented Phase-3 normalization here.
# The mapping logic mirrors what ``backends_cloud.AnthropicBackend`` and
# ``backends_cloud.GeminiBackend`` already do at the seam.

_ANTHROPIC_STOP_REASON_MAP = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}

_GEMINI_FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "OTHER": "stop",
}


def _canonicalize_anthropic(raw: dict[str, Any]) -> dict[str, Any]:
    """Map the pre-Phase-3 Anthropic fixture to the Phase-3 canonical shape."""
    out = dict(raw)
    raw_tool_calls = raw.get("tool_calls") or []
    canonical: list[dict[str, Any]] | None
    if raw_tool_calls:
        canonical = [
            {
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {})),
                },
            }
            for block in raw_tool_calls
        ]
    else:
        canonical = None
    out["tool_calls"] = canonical
    out["finish_reason"] = _ANTHROPIC_STOP_REASON_MAP.get(
        raw.get("finish_reason", "end_turn"), raw.get("finish_reason", "stop")
    )
    # Anthropic usage already uses input_tokens/output_tokens — leave as-is.
    return out


def _canonicalize_gemini(raw: dict[str, Any]) -> dict[str, Any]:
    """Map the pre-Phase-3 Gemini fixture to the Phase-3 canonical shape."""
    out = dict(raw)
    raw_finish = raw.get("finish_reason", "STOP")
    out["finish_reason"] = _GEMINI_FINISH_REASON_MAP.get(
        raw_finish, raw_finish.lower() if isinstance(raw_finish, str) else "stop"
    )
    raw_usage = raw.get("usage", {}) or {}
    out["usage"] = {
        "prompt_tokens": raw_usage.get("promptTokenCount", 0),
        "completion_tokens": raw_usage.get("candidatesTokenCount", 0),
        "total_tokens": raw_usage.get("totalTokenCount", 0),
    }
    return out


def _canonical(name: str) -> dict[str, Any]:
    raw = _load(name)
    if name == "anthropic_basic.json":
        return _canonicalize_anthropic(raw)
    if name == "gemini_basic.json":
        return _canonicalize_gemini(raw)
    # OpenAI and Ollama fixtures are already in the canonical shape.
    return raw


# ---------------------------------------------------------------------------
# Parameterized round-trip tests
# ---------------------------------------------------------------------------


ALL_FIXTURES = [
    "openai_basic.json",
    "anthropic_basic.json",
    "gemini_basic.json",
    "ollama_basic.json",
    "ollama_thinking.json",
]


@pytest.mark.unit
@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_dict_to_llm_response_preserves_core_fields(fixture_name: str) -> None:
    """content, tool_calls cardinality+names, finish_reason, usage survive."""
    canonical = _canonical(fixture_name)
    resp = dict_to_llm_response(canonical)

    # content
    assert resp.content == (canonical.get("content") or "")

    # tool_calls cardinality + names
    raw_tcs = canonical.get("tool_calls") or []
    assert len(resp.tool_calls) == len(raw_tcs)
    for ek_call, raw_call in zip(resp.tool_calls, raw_tcs, strict=True):
        expected_name = raw_call.get("function", {}).get("name", "")
        assert ek_call.name == expected_name

    # finish_reason
    expected_finish = canonical.get("finish_reason") or "stop"
    assert resp.finish_reason == expected_finish

    # usage frozen and equal in key/value content
    assert dict(resp.usage) == (canonical.get("usage") or {})


@pytest.mark.unit
def test_openai_input_tokens_via_prompt_tokens() -> None:
    """openai_basic: ``input_tokens`` derived from ``prompt_tokens``."""
    resp = dict_to_llm_response(_canonical("openai_basic.json"))
    # Fixture has prompt_tokens=9, completion_tokens=9.
    assert resp.input_tokens == 9
    assert resp.output_tokens == 9


@pytest.mark.unit
def test_anthropic_input_tokens_via_input_tokens_key() -> None:
    """anthropic_basic: ``input_tokens`` derived from native ``input_tokens``."""
    resp = dict_to_llm_response(_canonical("anthropic_basic.json"))
    # Fixture has input_tokens=12, output_tokens=10.
    assert resp.input_tokens == 12
    assert resp.output_tokens == 10


@pytest.mark.unit
def test_gemini_input_tokens_via_prompt_tokens_post_p3() -> None:
    """gemini_basic: post-P3 ``input_tokens`` derived from normalized ``prompt_tokens``."""
    resp = dict_to_llm_response(_canonical("gemini_basic.json"))
    # Fixture has promptTokenCount=8, candidatesTokenCount=9 — post-P3
    # normalization rewrites these to prompt_tokens / completion_tokens.
    assert resp.input_tokens == 8
    assert resp.output_tokens == 9


@pytest.mark.unit
@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_round_trip_field_equivalence(fixture_name: str) -> None:
    """``llm_response_to_dict(dict_to_llm_response(fx))`` matches fx on core fields."""
    canonical = _canonical(fixture_name)
    resp = dict_to_llm_response(canonical)
    out = llm_response_to_dict(resp)

    # content
    assert out["content"] == (canonical.get("content") or "")

    # finish_reason
    assert out["finish_reason"] == (canonical.get("finish_reason") or "stop")

    # usage
    assert out["usage"] == (canonical.get("usage") or {})

    # tool_calls — structural equivalence on id/name and parsed arguments.
    raw_tcs = canonical.get("tool_calls")
    if not raw_tcs:
        assert out["tool_calls"] is None
    else:
        assert out["tool_calls"] is not None
        assert len(out["tool_calls"]) == len(raw_tcs)
        for got, expected in zip(out["tool_calls"], raw_tcs, strict=True):
            assert got["id"] == expected["id"]
            assert got["type"] == "function"
            assert got["function"]["name"] == expected["function"]["name"]
            # arguments is JSON-string on both sides; compare parsed payloads
            # so key ordering inside the JSON string does not matter.
            assert json.loads(got["function"]["arguments"]) == json.loads(
                expected["function"]["arguments"]
            )


# ---------------------------------------------------------------------------
# HTTP status -> error class mapping
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_map_http_error_429_is_rate_limit() -> None:
    assert map_http_error(429) is RateLimitError


@pytest.mark.unit
@pytest.mark.parametrize("status", [401, 403, 404])
def test_map_http_error_permanent(status: int) -> None:
    assert map_http_error(status) is PermanentError


@pytest.mark.unit
@pytest.mark.parametrize("status", [500, 502, 503, 504, 400, 408, 409, 422])
def test_map_http_error_provider_catchall(status: int) -> None:
    assert map_http_error(status) is ProviderError


@pytest.mark.unit
def test_map_http_error_accepts_retry_after_signature() -> None:
    """``retry_after`` is accepted for call-shape symmetry; does not change class."""
    assert map_http_error(429, retry_after=1.5) is RateLimitError
    assert map_http_error(500, retry_after=None) is ProviderError
