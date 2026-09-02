"""Tests for the provider-inventory redaction helper."""

from __future__ import annotations

from typing import Any

from tools.llm._redact import REDACTED, redact_inventory


class TestRedactInventory:
    """Tests for redact_inventory."""

    def test_sensitive_scalar_is_redacted(self) -> None:
        """An exact-match sensitive key is replaced."""
        assert redact_inventory({"api_key": "sk-live-123"})["api_key"] == REDACTED

    def test_substring_match_is_redacted(self) -> None:
        """A key merely containing a sensitive marker is replaced."""
        result = redact_inventory({"openai_api_key": "sk-1", "bearer_token": "t"})
        assert result["openai_api_key"] == REDACTED
        assert result["bearer_token"] == REDACTED

    def test_prefixed_endpoint_is_redacted_like_the_bare_key(self) -> None:
        """Provider URLs can carry the key in a query string."""
        result = redact_inventory({"ollama_endpoint": "https://host/v1?key=abc"})
        assert result["ollama_endpoint"] == REDACTED

    def test_non_sensitive_values_survive(self) -> None:
        """Ordinary report fields are passed through untouched."""
        payload = {"model": "gpt-4o-mini", "ok": True, "latency_s": 1.5}
        assert redact_inventory(payload) == payload

    def test_sensitive_dict_value_is_redacted_wholesale(self) -> None:
        """A dict parked under a sensitive key is not walked into and emitted."""
        result = redact_inventory({"credentials_token": {"value": "sk-live-123"}})
        assert result["credentials_token"] == REDACTED

    def test_sensitive_list_value_is_redacted_wholesale(self) -> None:
        """A list under a sensitive key is replaced, not iterated."""
        result = redact_inventory({"endpoints": ["https://host/v1?key=abc"]})
        assert result["endpoints"] == REDACTED

    def test_nested_dict_is_scrubbed(self) -> None:
        """Sensitive keys are found at depth."""
        result = redact_inventory({"providers": {"openai": {"api_key": "sk-1"}}})
        assert result["providers"]["openai"]["api_key"] == REDACTED

    def test_dicts_inside_lists_are_scrubbed(self) -> None:
        """List elements that are dicts are recursed into."""
        payload = {"results": [{"model": "m", "api_key": "sk-1"}]}
        result = redact_inventory(payload)
        assert result["results"][0]["api_key"] == REDACTED
        assert result["results"][0]["model"] == "m"

    def test_input_is_not_mutated(self) -> None:
        """Redaction returns a new object and leaves the caller's dict alone."""
        payload: dict[str, Any] = {"providers": {"openai": {"api_key": "sk-1"}}}
        redact_inventory(payload)
        assert payload["providers"]["openai"]["api_key"] == "sk-1"

    def test_excessive_depth_fails_closed(self) -> None:
        """Past the depth guard, values are redacted rather than emitted raw."""
        payload: dict[str, Any] = {"secret_value": "sk-live-123"}
        for _ in range(15):
            payload = {"nested": payload}

        result = redact_inventory(payload)
        for _ in range(10):
            result = result["nested"]
        assert result["nested"] == REDACTED
