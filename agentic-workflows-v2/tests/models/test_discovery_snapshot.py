"""Tests for the unified discovery facade (ARP-IMPROVEMENTS F2).

Each source discovery function is patched at its home module (the facade
imports them lazily inside discover_all_models(), so patching the source
module's attribute is what the lazy import re-resolves at call time -- see
the ollama_discovery / local_discovery patching precedent in
tests/test_langchain_models_unit.py::TestEnumerateKnownModelsMerge).
"""

from __future__ import annotations

import pytest

from agentic_v2.models import (
    cloud_discovery,
    docker_model_runner_discovery,
    foundry_local_discovery,
    lemonade_discovery,
    local_discovery,
    ollama_discovery,
)
from agentic_v2.models.discovery_snapshot import discover_all_models


@pytest.fixture(autouse=True)
def _stub_all_sources_empty(monkeypatch: pytest.MonkeyPatch):
    """Default every source to empty so each test only wires what it needs."""
    monkeypatch.setattr(cloud_discovery, "discover_cloud_models", lambda: [])
    monkeypatch.setattr(ollama_discovery, "discover_ollama_models", lambda: [])
    monkeypatch.setattr(
        local_discovery,
        "discover_lmstudio_catalog",
        lambda: local_discovery.LmStudioCatalog(),
    )
    monkeypatch.setattr(local_discovery, "discover_onnx_models", lambda: [])
    monkeypatch.setattr(lemonade_discovery, "discover_lemonade_models", lambda: [])
    monkeypatch.setattr(
        docker_model_runner_discovery,
        "discover_docker_model_runner_models",
        lambda: [],
    )
    monkeypatch.setattr(
        foundry_local_discovery, "discover_foundry_local_models", lambda: []
    )


@pytest.mark.unit
def test_no_sources_returns_empty_list() -> None:
    assert discover_all_models() == []


@pytest.mark.unit
def test_verify_true_is_not_implemented() -> None:
    """F3 (real completion calls) is deferred; the schema/signature exist, the
    behavior does not -- this must raise, not silently do a partial job."""
    with pytest.raises(NotImplementedError, match="F3"):
        discover_all_models(verify=True)


@pytest.mark.unit
def test_local_lane_providers_are_all_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lemonade_discovery,
        "discover_lemonade_models",
        lambda: [lemonade_discovery.LemonadeModelInfo(id="lemonade:phi-4", name="phi-4")],
    )
    monkeypatch.setattr(
        docker_model_runner_discovery,
        "discover_docker_model_runner_models",
        lambda: [
            docker_model_runner_discovery.DockerModelRunnerInfo(
                id="docker-model-runner:qwen3", name="qwen3"
            )
        ],
    )
    monkeypatch.setattr(
        foundry_local_discovery,
        "discover_foundry_local_models",
        lambda: [
            foundry_local_discovery.FoundryLocalModelInfo(
                id="foundry-local:qwen2.5-coder-7b", name="qwen2.5-coder-7b", device="NPU"
            )
        ],
    )

    result = discover_all_models()

    by_id = {m.id: m for m in result}
    assert by_id["lemonade:phi-4"].cost_lane == "local"
    assert by_id["docker-model-runner:qwen3"].cost_lane == "local"
    assert by_id["foundry-local:qwen2.5-coder-7b"].cost_lane == "local"
    assert all(m.verified_by == "listing" for m in result)
    assert all(m.reachable is True for m in result)


@pytest.mark.unit
def test_ollama_cloud_flag_maps_to_free_local_maps_to_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ollama_discovery,
        "discover_ollama_models",
        lambda: [
            ollama_discovery.OllamaModelInfo(
                id="ollama:gemma4:31b", name="gemma4:31b", cloud=False
            ),
            ollama_discovery.OllamaModelInfo(
                id="ollama:deepseek-v4-flash:0731-cloud",
                name="deepseek-v4-flash:0731-cloud",
                cloud=True,
            ),
        ],
    )

    result = discover_all_models()
    by_id = {m.id: m for m in result}
    assert by_id["ollama:gemma4:31b"].cost_lane == "local"
    assert by_id["ollama:deepseek-v4-flash:0731-cloud"].cost_lane == "free"


@pytest.mark.unit
def test_nim_curated_free_endpoint_is_free_uncurated_id_fails_closed_to_paid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A NIM id curated in model_registry.yaml as a free-endpoint entry
    (``tiers: []``, ``cost_lane: free``) reports "free"; an id with no
    registry entry at all fails closed to "paid" -- both via the same
    model_registry.cost_lane_for the facade uses for every cloud provider."""
    monkeypatch.setattr(
        cloud_discovery,
        "discover_cloud_models",
        lambda: [
            cloud_discovery.CloudModelInfo(id="nvidia:minimaxai/minimax-m3"),
            cloud_discovery.CloudModelInfo(id="nvidia:some/uncurated-model"),
        ],
    )

    result = discover_all_models()
    by_id = {m.id: m for m in result}
    assert by_id["nvidia:minimaxai/minimax-m3"].cost_lane == "free"
    assert by_id["nvidia:some/uncurated-model"].cost_lane == "paid"


@pytest.mark.unit
def test_cloud_provider_uses_registry_cost_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cloud_discovery,
        "discover_cloud_models",
        lambda: [cloud_discovery.CloudModelInfo(id="anthropic:claude-opus-4-6")],
    )

    result = discover_all_models()
    assert result[0].provider == "anthropic"
    assert result[0].cost_lane == "paid"  # curated in model_registry.yaml
    assert result[0].verified_by == "listing"
    assert result[0].latency_ms is None


@pytest.mark.unit
def test_records_are_json_serialisable() -> None:
    from agentic_v2.models.discovery_snapshot import DiscoveredModel

    record = DiscoveredModel(
        id="ollama:phi-4",
        provider="ollama",
        endpoint="http://localhost:11434",
        cost_lane="local",
        reachable=True,
        verified_by="listing",
        latency_ms=None,
        probed_at="2026-08-27T00:00:00+00:00",
    )
    assert record.to_dict()["id"] == "ollama:phi-4"
