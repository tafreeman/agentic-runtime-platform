"""Tests for Docker Model Runner discovery (ARP-IMPROVEMENTS F2).

Network is always mocked at ``httpx.get``, mirroring
tests/models/test_ollama_discovery.py.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentic_v2.models import docker_model_runner_discovery as dmr
from agentic_v2.models.docker_model_runner_discovery import (
    discover_docker_model_runner_models,
)

_DEFAULT_URL = "http://localhost:12434/engines/v1/models"


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

    monkeypatch.setattr(dmr.httpx, "get", _fake_get)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_MODEL_RUNNER_BASE_URL", raising=False)


@pytest.mark.unit
def test_parses_openai_style_data_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_get(
        monkeypatch,
        {
            _DEFAULT_URL: {
                "data": [
                    {"id": "nemotron-3.5-lightning"},
                    {"id": "qwen3-embedding"},
                    {"id": "muse-glimmer"},
                ]
            }
        },
    )

    result = discover_docker_model_runner_models()

    assert [m.id for m in result] == [
        "docker-model-runner:nemotron-3.5-lightning",
        "docker-model-runner:qwen3-embedding",
        "docker-model-runner:muse-glimmer",
    ]


@pytest.mark.unit
def test_unreachable_engine_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_get(monkeypatch, {})
    assert discover_docker_model_runner_models() == []


@pytest.mark.unit
def test_env_base_url_override_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_MODEL_RUNNER_BASE_URL", "http://127.0.0.1:9999")
    _install_fake_get(
        monkeypatch,
        {"http://127.0.0.1:9999/engines/v1/models": {"data": [{"id": "qwen3"}]}},
    )
    result = discover_docker_model_runner_models()
    assert [m.id for m in result] == ["docker-model-runner:qwen3"]
