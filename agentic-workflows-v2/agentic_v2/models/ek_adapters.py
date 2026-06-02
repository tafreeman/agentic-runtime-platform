"""ADR-023 Phase 4: pure adapter between runtime backend dicts and EK contracts.

This module is **isolated** — nothing inside ``agentic_v2`` imports it. It is
referenced only by ``tests/models/test_ek_adapters.py`` so that the round-trip
mapping between the canonicalized runtime ``complete_chat`` dict (Phase 3) and
the ExecutionKit value types (``executionkit.provider``) can be proven
loss-less *before* Phase 5 wires it into the hot path.

Hard constraints (ADR-023 functionality-preservation):

* No I/O. No global state. No network. Pure functions only.
* No imports from anywhere inside ``agentic_v2`` — this file deliberately
  depends only on stdlib + ``executionkit``. That keeps the conformance suite
  trivially isolatable.
* ``LLMResponse`` / ``ToolCall`` are frozen value types owned by EK; we never
  mutate them. ``usage`` is wrapped in ``MappingProxyType`` to match EK's
  contract.
* Additive-only. Unknown fields on the input dict are preserved verbatim under
  ``LLMResponse.raw`` so a future consumer can recover provider-specific
  data (e.g. ``_raw_anthropic``, ``_raw_gemini``).
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Any

from executionkit.errors import (
    ExecutionKitError as ExecutionKitError,
)
from executionkit.errors import (
    LLMError,
    PermanentError,
    ProviderError,
    RateLimitError,
)
from executionkit.provider import LLMResponse, ToolCall

__all__ = [
    "dict_to_llm_response",
    "llm_response_to_dict",
    "map_http_error",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_arguments(raw_arguments: Any) -> dict[str, Any]:
    """Coerce a tool-call ``arguments`` field to a dict.

    The Phase 3 canonical OpenAI-flavoured shape stores ``arguments`` as a
    **JSON string** (matching the OpenAI ``/chat/completions`` wire format).
    EK's ``ToolCall.arguments`` is ``dict[str, Any]``, so we parse here.

    Already-dict inputs (e.g. from a future backend that bypasses the JSON
    encode) pass through unchanged. Empty / whitespace strings parse to ``{}``.
    Malformed JSON falls back to ``{"_raw": <original>}`` so the round-trip
    stays loss-less rather than raising — the conformance suite is not the
    right place to enforce vendor-side schema strictness.
    """
    if raw_arguments is None:
        return {}
    if isinstance(raw_arguments, dict):
        return dict(raw_arguments)
    if isinstance(raw_arguments, str):
        stripped = raw_arguments.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return {"_raw": raw_arguments}
        if isinstance(parsed, dict):
            return parsed
        return {"_value": parsed}
    # Unknown container — wrap so we don't raise inside a pure mapper.
    return {"_value": raw_arguments}


def _extract_tool_calls(payload: dict[str, Any]) -> tuple[ToolCall, ...]:
    """Map ``payload['tool_calls']`` (canonical OpenAI shape or None) to EK tuple.

    Canonical Phase 3 shape (per ``backends_cloud.AnthropicBackend`` and
    ``backends_cloud.OpenAIBackend``)::

        [
            {
                "id": "<call id>",
                "type": "function",
                "function": {
                    "name": "<tool name>",
                    "arguments": "<JSON string>",
                },
            },
            ...
        ]

    ``None`` / missing / empty list -> empty tuple.
    """
    raw = payload.get("tool_calls")
    if not raw:
        return ()

    calls: list[ToolCall] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        call_id = str(entry.get("id", ""))
        function = entry.get("function", {})
        if isinstance(function, dict):
            name = str(function.get("name", ""))
            arguments = _coerce_arguments(function.get("arguments"))
        else:
            # Defensive: pre-canonical Anthropic-style ``{name, input}`` block.
            name = str(entry.get("name", ""))
            arguments = _coerce_arguments(entry.get("input"))
        calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
    return tuple(calls)


def _freeze_usage(usage: Any) -> MappingProxyType[str, Any]:
    """Wrap a usage mapping in ``MappingProxyType`` (EK's contract)."""
    if usage is None:
        return MappingProxyType({})
    if isinstance(usage, MappingProxyType):
        return usage
    if isinstance(usage, dict):
        return MappingProxyType(dict(usage))
    # Defensive fallback — never raise from a pure mapper.
    return MappingProxyType({})


# ---------------------------------------------------------------------------
# Public adapter functions
# ---------------------------------------------------------------------------


def dict_to_llm_response(payload: dict[str, Any]) -> LLMResponse:
    """Map a runtime ``complete_chat`` dict (canonicalized per Phase 3) to ``LLMResponse``.

    Loss-less when ``payload`` was produced by a Phase-3 backend. The original
    dict is preserved verbatim under ``LLMResponse.raw`` so any
    provider-specific keys (``_raw_anthropic``, ``_raw_gemini``, ``model``,
    ``thinking``, ...) survive the round trip.
    """
    content = payload.get("content", "")
    if content is None:
        content = ""
    finish_reason = payload.get("finish_reason") or "stop"

    return LLMResponse(
        content=str(content),
        tool_calls=_extract_tool_calls(payload),
        finish_reason=str(finish_reason),
        usage=_freeze_usage(payload.get("usage")),
        raw=payload,
    )


def llm_response_to_dict(resp: LLMResponse) -> dict[str, Any]:
    """Inverse of :func:`dict_to_llm_response`.

    Emits the canonical Phase 3 OpenAI-flavoured dict shape. ``arguments`` is
    re-serialised as a JSON string (the wire format runtime backends already
    use). Field-equivalent to the original on ``content`` / ``tool_calls`` /
    ``finish_reason`` / ``usage`` after the canonical-shape round trip.
    """
    if resp.tool_calls:
        tool_calls: list[dict[str, Any]] | None = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(dict(call.arguments), sort_keys=True),
                },
            }
            for call in resp.tool_calls
        ]
    else:
        tool_calls = None

    return {
        "content": resp.content,
        "tool_calls": tool_calls,
        "finish_reason": resp.finish_reason,
        "usage": dict(resp.usage),
    }


def map_http_error(
    status: int, retry_after: float | None = None
) -> type[LLMError]:
    """Classify an upstream HTTP status code to an EK error class.

    Mapping (per ADR-023 and the EK ``provider.py`` contract):

    * ``429`` -> :class:`RateLimitError` (retryable)
    * ``401`` / ``403`` / ``404`` -> :class:`PermanentError` (non-retryable)
    * other 4xx and all 5xx -> :class:`ProviderError` (retryable catch-all)

    ``retry_after`` is accepted for callable-shape symmetry with the EK
    ``RateLimitError`` constructor; it is *not* used to pick the class.
    """
    del retry_after  # signature-only; classification is status-driven.

    if status == 429:
        return RateLimitError
    if status in (401, 403, 404):
        return PermanentError
    return ProviderError
