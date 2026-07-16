"""Tests for LM Studio native v1 catalog discovery."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tools.llm.probe_discovery_providers import _probe_lmstudio


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def test_probe_uses_native_v1_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
    monkeypatch.delenv("LM_API_TOKEN", raising=False)

    with patch(
        "tools.llm.probe_discovery_providers.urllib.request.urlopen",
        return_value=_mock_response(
            {"models": [{"key": "google/gemma-3-12b"}, {"key": "nomic-embed"}]}
        ),
    ) as mock_urlopen:
        result = _probe_lmstudio()

    request = mock_urlopen.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:1234/api/v1/models"
    assert result["available"] == [
        "lmstudio:google/gemma-3-12b",
        "lmstudio:nomic-embed",
    ]


def test_probe_sends_lm_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234/api/v1")
    monkeypatch.setenv("LM_API_TOKEN", "test-token")

    with patch(
        "tools.llm.probe_discovery_providers.urllib.request.urlopen",
        return_value=_mock_response({"models": []}),
    ) as mock_urlopen:
        _probe_lmstudio()

    request = mock_urlopen.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:1234/api/v1/models"
    assert request.get_header("Authorization") == "Bearer test-token"
