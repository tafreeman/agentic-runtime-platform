"""Redact sensitive fields from provider-inventory dicts before serialization.

Provider inventories and probe results carry API keys, bearer tokens and
endpoint URLs. They are written to JSON reports and logged at INFO, so they
have to be scrubbed on the way out (CodeQL ``py/clear-text-storage-sensitive-data``
and ``py/clear-text-logging-sensitive-data``).
"""

from __future__ import annotations

from typing import Any

REDACTED = "[REDACTED]"

#: Maximum nesting depth to walk. Deeper structures are replaced wholesale
#: rather than emitted unscrubbed — the guard exists for pathological or
#: self-referential input, so it fails closed.
_MAX_DEPTH = 10

SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "api_key_present",
        "endpoint",
        "endpoints",
        "api_token",
        "secret",
        "password",
        "token",
        "authorization",
        "key",
    }
)

#: Substrings that mark a key as sensitive even when it is not an exact match
#: (``openai_api_key``, ``bearer_token``, ``secret_ref``, ``ollama_endpoint``…).
#: ``endpoint`` is included because provider URLs routinely carry the key in a
#: query string — treating the bare key as sensitive but not the prefixed one
#: would leak exactly the same value under a different name.
_SENSITIVE_SUBSTRINGS = (
    "secret",
    "token",
    "key",
    "password",
    "authorization",
    "endpoint",
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or any(
        marker in lowered for marker in _SENSITIVE_SUBSTRINGS
    )


def redact_inventory(data: dict[str, Any], _depth: int = 0) -> dict[str, Any]:
    """Return a copy of *data* with sensitive values replaced by ``[REDACTED]``.

    The input is never mutated. A sensitive key is redacted whatever its value
    type — the check runs *before* the recursion, so a dict or list parked under
    ``api_key`` is replaced wholesale instead of being walked into and emitted.
    """
    out: dict[str, Any] = {}
    for k, v in data.items():
        if _is_sensitive(k):
            out[k] = REDACTED
        elif _depth >= _MAX_DEPTH:
            out[k] = REDACTED
        elif isinstance(v, dict):
            out[k] = redact_inventory(v, _depth + 1)
        elif isinstance(v, list):
            out[k] = [
                redact_inventory(item, _depth + 1) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            out[k] = v
    return out
