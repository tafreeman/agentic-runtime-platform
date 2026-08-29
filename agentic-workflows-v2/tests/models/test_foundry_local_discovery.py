"""Tests for Foundry Local discovery (ARP-IMPROVEMENTS F2).

Network is always mocked at ``httpx.get``, mirroring
tests/models/test_ollama_discovery.py. Covers the naming-trap boundary: this
provider is ``foundry-local:``, never bare ``foundry:`` (that would collide
with Azure AI Foundry in agentic_v2.models.backends).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentic_v2.models import foundry_local_discovery as fl
from agentic_v2.models.foundry_local_discovery import discover_foundry_local_models

_DEFAULT_URL = "http://127.0.0.1:60160/v1/models"


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - trivial
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _install_fake_get(
    monkeypatch: pytest.MonkeyPatch, routes: dict[str, dict[str, Any]]
) -> None:
    def _fake_get(url: str, timeout: Any = None):
        if url not in routes:
            raise httpx.ConnectError(f"unreachable: {url}")
        return _FakeResponse(routes[url])

    monkeypatch.setattr(fl.httpx, "get", _fake_get)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOUNDRY_LOCAL_BASE_URL", raising=False)


@pytest.mark.unit
def test_parses_device_hint_and_uses_foundry_local_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_get(
        monkeypatch,
        {
            _DEFAULT_URL: {
                "data": [
                    {"id": "qwen2.5-coder-7b", "device": "NPU"},
                    {"id": "gpt-oss-20b", "executionProvider": "GPU"},
                    {"id": "phi-4"},
                ]
            }
        },
    )

    result = discover_foundry_local_models()

    assert [m.id for m in result] == [
        "foundry-local:qwen2.5-coder-7b",
        "foundry-local:gpt-oss-20b",
        "foundry-local:phi-4",
    ]
    assert result[0].device == "NPU"
    assert result[1].device == "GPU"
    assert result[2].device is None
    # never the bare "foundry:" prefix -- that is Azure AI Foundry
    assert all(not m.id.startswith("foundry:") for m in result)


@pytest.mark.unit
def test_unreachable_service_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_get(monkeypatch, {})
    assert discover_foundry_local_models() == []


@pytest.mark.unit
def test_env_base_url_override_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOUNDRY_LOCAL_BASE_URL", "http://127.0.0.1:9999")
    _install_fake_get(
        monkeypatch,
        {"http://127.0.0.1:9999/v1/models": {"data": [{"id": "deepseek-r1-7b"}]}},
    )
    result = discover_foundry_local_models()
    assert [m.id for m in result] == ["foundry-local:deepseek-r1-7b"]
