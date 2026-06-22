"""Tests for Ollama cloud discovery (``_probe_ollama_cloud``).

Cloud models are served by ollama.com and require ``OLLAMA_API_KEY``; the
local ``/api/tags`` probe never returns them. These tests pin two behaviours:

- No key configured => a passive, no-network entry (``configured`` False).
- Key configured => the hosted ``/api/tags`` is queried with a bearer token
  and returned models are prefixed ``ollama:`` like the local probe.

Network is always mocked — no live calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tools.llm.probe_discovery_providers import _probe_ollama_cloud


def _mock_tags_response(payload: dict) -> MagicMock:
    """Build a context-manager mock mimicking urlopen's response."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestProbeOllamaCloud:
    def test_no_key_is_passive_and_makes_no_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without OLLAMA_API_KEY the probe is configured=False and never calls out."""
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

        with patch(
            "tools.llm.probe_discovery_providers.urllib.request.urlopen"
        ) as mock_urlopen:
            result = _probe_ollama_cloud()

        mock_urlopen.assert_not_called()
        assert result["configured"] is False
        assert result["available"] == []
        assert result["count"] == 0
        assert result["error"] is None
        assert "OLLAMA_API_KEY" in result["notes"]

    def test_with_key_lists_and_prefixes_cloud_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With a key, hosted models are returned prefixed with ``ollama:``."""
        monkeypatch.setenv("OLLAMA_API_KEY", "test-key-123")
        payload = {
            "models": [
                {"name": "gpt-oss:120b-cloud"},
                {"name": "qwen3-coder:480b-cloud"},
                {"name": ""},  # malformed entry must be skipped
            ]
        }

        with patch(
            "tools.llm.probe_discovery_providers.urllib.request.urlopen",
            return_value=_mock_tags_response(payload),
        ):
            result = _probe_ollama_cloud()

        assert result["configured"] is True
        assert result["error"] is None
        assert result["available"] == [
            "ollama:gpt-oss:120b-cloud",
            "ollama:qwen3-coder:480b-cloud",
        ]
        assert result["count"] == 2
        assert result["host"] == "https://ollama.com"

    def test_with_key_sends_bearer_authorization_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The request must carry an Authorization: Bearer <key> header."""
        monkeypatch.setenv("OLLAMA_API_KEY", "secret-abc")

        with patch(
            "tools.llm.probe_discovery_providers.urllib.request.urlopen",
            return_value=_mock_tags_response({"models": []}),
        ) as mock_urlopen:
            _probe_ollama_cloud()

        req = mock_urlopen.call_args.args[0]
        # urllib lowercases header keys on the Request object.
        assert req.get_header("Authorization") == "Bearer secret-abc"
        assert req.full_url == "https://ollama.com/api/tags"

    def test_network_failure_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transport error becomes a probe ``error`` string, never an exception."""
        monkeypatch.setenv("OLLAMA_API_KEY", "test-key-123")

        with patch(
            "tools.llm.probe_discovery_providers.urllib.request.urlopen",
            side_effect=ConnectionError("boom"),
        ):
            result = _probe_ollama_cloud()

        assert result["configured"] is True
        assert result["available"] == []
        assert result["error"] is not None
        assert "ollama.com" in result["error"]
