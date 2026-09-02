"""Tests for Lemonade discovery (ARP-IMPROVEMENTS F2).

Network is always mocked at ``httpx.get``, mirroring
tests/models/test_ollama_discovery.py.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentic_v2.models import lemonade_discovery
from agentic_v2.models.lemonade_discovery import discover_lemonade_models

_DEFAULT_URL = "http://localhost:13305/api/v1/models"


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

    monkeypatch.setattr(lemonade_discovery.httpx, "get", _fake_get)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEMONADE_BASE_URL", raising=False)


@pytest.mark.unit
def test_parses_models_list_with_recipe_and_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_get(
        monkeypatch,
        {
            _DEFAULT_URL: {
                "models": [
                    {
                        "id": "CodeLlama-7b-Instruct-hf-Hybrid",
                        "recipe": "ryzenai-llm",
                        "labels": ["coding"],
                    },
                    {"checkpoint": "Gemma-4-E2B-it-GGUF", "recipe": "llamacpp"},
                ]
            }
        },
    )

    result = discover_lemonade_models()

    assert [m.id for m in result] == [
        "lemonade:CodeLlama-7b-Instruct-hf-Hybrid",
        "lemonade:Gemma-4-E2B-it-GGUF",
    ]
    assert result[0].recipe == "ryzenai-llm"
    assert result[0].labels == ("coding",)
    assert result[1].recipe == "llamacpp"


@pytest.mark.unit
def test_unreachable_server_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_get(monkeypatch, {})
    assert discover_lemonade_models() == []


@pytest.mark.unit
def test_malformed_payload_degrades_to_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_get(monkeypatch, {_DEFAULT_URL: {"unexpected": "shape"}})
    assert discover_lemonade_models() == []


@pytest.mark.unit
def test_env_base_url_override_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMONADE_BASE_URL", "http://127.0.0.1:9999")
    _install_fake_get(
        monkeypatch,
        {"http://127.0.0.1:9999/api/v1/models": {"models": [{"id": "phi-4"}]}},
    )
    result = discover_lemonade_models()
    assert [m.id for m in result] == ["lemonade:phi-4"]


@pytest.mark.unit
def test_deduplicates_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_get(
        monkeypatch,
        {_DEFAULT_URL: {"models": [{"id": "phi-4"}, {"id": "phi-4"}]}},
    )
    result = discover_lemonade_models()
    assert len(result) == 1
