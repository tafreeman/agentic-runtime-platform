"""Tests for NVIDIA Free Endpoint classification (``_probe_nvidia``).

The build.nvidia.com Free Endpoint catalog describes the hosted API only. These
tests pin when the probe may classify against it:

- Hosted origin, successful ``/models`` => entries split into
  ``free_available`` (served) and ``free_catalog_only`` (not served), with
  catalog slugs mapped through ``NVIDIA_NIM_CATALOG_ALIASES``.
- Hosted origin, failed ``/models`` => free status unknown, no lists.
- Self-hosted NIM => free status unknown, even when its models resemble the
  catalog.

Network is always mocked; no live calls.
"""

from __future__ import annotations

import json
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tools.llm.probe_config import (
    NVIDIA_NIM_CATALOG_ALIASES,
    NVIDIA_NIM_FREE_ENDPOINT_CATALOG,
)
from tools.llm.probe_discovery_providers import _probe_nvidia

HOSTED = "https://integrate.api.nvidia.com/v1"
SELF_HOSTED = "http://10.0.0.5:8000/v1"
URLOPEN = "tools.llm.probe_discovery_providers.urllib.request.urlopen"


@pytest.fixture(autouse=True)
def _nvidia_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test with one key and no ambient NVIDIA host."""
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "test-key")
    for i in range(10):
        monkeypatch.delenv(f"NVIDIA_NIM_API_KEY_{i}", raising=False)


def _models_response(ids: list[str]) -> MagicMock:
    payload: dict[str, Any] = {
        "object": "list",
        "data": [{"id": mid, "object": "model"} for mid in ids],
    }
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_hosted_success_classifies_and_maps_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NVIDIA_NIM_HOST", HOSTED)
    served = ["z-ai/glm-5.3", "nvidia/nemotron-3-embed-1b", "some/unrelated-model"]

    with patch(URLOPEN, return_value=_models_response(served)):
        result = _probe_nvidia()

    assert result["free_status"] == "classified"
    assert result["reachable"] is True
    # The catalog slug is z-ai/glm-5-3; the served id is z-ai/glm-5.3.
    assert NVIDIA_NIM_CATALOG_ALIASES["z-ai/glm-5-3"] == "z-ai/glm-5.3"
    assert "nvidia:z-ai/glm-5.3" in result["free_available"]
    assert "nvidia:z-ai/glm-5-3" not in result["free_available"]
    assert "nvidia:nvidia/nemotron-3-embed-1b" in result["free_available"]
    assert "nvidia:some/unrelated-model" not in result["free_available"]
    assert "nvidia:nvidia/kumo-tabular" in result["free_catalog_only"]
    assert len(result["free_available"]) + len(result["free_catalog_only"]) == len(
        NVIDIA_NIM_FREE_ENDPOINT_CATALOG
    )


@pytest.mark.parametrize(
    "error",
    [urllib.error.URLError("refused"), TimeoutError("slow")],
    ids=["unreachable", "timeout"],
)
def test_hosted_failed_probe_is_unknown(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setenv("NVIDIA_NIM_HOST", HOSTED)

    with patch(URLOPEN, side_effect=error):
        result = _probe_nvidia()

    assert result["free_status"] == "unknown"
    assert result["reachable"] is False
    assert result["free_available"] == []
    assert result["free_catalog_only"] == []
    assert result["error"] is not None


def test_self_hosted_nim_is_unknown_even_with_catalog_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NVIDIA_NIM_HOST", SELF_HOSTED)
    # The on-prem NIM serves a catalog id; it must not be labelled free.
    local = ["nvidia/nemotron-3-embed-1b", "local/only-model"]

    with patch(URLOPEN, return_value=_models_response(local)):
        result = _probe_nvidia()

    assert result["reachable"] is True
    assert result["free_status"] == "unknown"
    assert result["free_available"] == []
    assert result["free_catalog_only"] == []
    assert result["available"] == [
        "nvidia:nvidia/nemotron-3-embed-1b",
        "nvidia:local/only-model",
    ]


def test_host_not_set_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NVIDIA_NIM_HOST", raising=False)

    with patch(URLOPEN) as opened:
        result = _probe_nvidia()

    opened.assert_not_called()
    assert result["configured"] is False
    assert result["free_status"] == "unknown"


@pytest.mark.parametrize(
    "host",
    [
        "http://integrate.api.nvidia.com/v1",
        "https://integrate.api.nvidia.com:8443/v1",
        "https://proxy.example.com/integrate.api.nvidia.com/v1",
    ],
    ids=["plain-http", "other-port", "other-host"],
)
def test_lookalike_origins_are_unknown(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setenv("NVIDIA_NIM_HOST", host)

    with patch(URLOPEN, return_value=_models_response(["z-ai/glm-5.3"])):
        result = _probe_nvidia()

    assert result["reachable"] is True
    assert result["free_status"] == "unknown"
    assert result["free_available"] == []


def test_unset_host_reports_catalog_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NVIDIA_NIM_HOST", raising=False)

    result = _probe_nvidia()

    assert result["free_endpoint_catalog_count"] == len(
        NVIDIA_NIM_FREE_ENDPOINT_CATALOG
    )


def test_malformed_port_does_not_abort_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NVIDIA_NIM_HOST", "https://integrate.api.nvidia.com:bogus/v1")

    with patch(URLOPEN, return_value=_models_response(["z-ai/glm-5.3"])):
        result = _probe_nvidia()

    assert result["reachable"] is True
    assert result["free_status"] == "unknown"
    assert result["free_available"] == []
