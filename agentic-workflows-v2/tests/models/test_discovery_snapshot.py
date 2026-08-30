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
    """Default every source to empty so each test only wires what it needs.

    Also clears every configurable-host env var discover_all_models reads
    directly (OLLAMA_API_KEY/OLLAMA_BASE_URL, LMSTUDIO_HOST,
    LEMONADE_BASE_URL, DOCKER_MODEL_RUNNER_BASE_URL, FOUNDRY_LOCAL_BASE_URL):
    an ambient key or non-loopback host on whatever machine runs the suite
    would silently change which branch a test actually exercises.
    """
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("LMSTUDIO_HOST", raising=False)
    monkeypatch.delenv("LEMONADE_BASE_URL", raising=False)
    monkeypatch.delenv("DOCKER_MODEL_RUNNER_BASE_URL", raising=False)
    monkeypatch.delenv("FOUNDRY_LOCAL_BASE_URL", raising=False)
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
def test_lemonade_docker_model_runner_foundry_local_downgrade_for_remote_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """These providers are only "local" when actually pointed at this
    machine -- an operator can configure any of them at a remote host, and
    the reported lane must reflect that, not assume "local" from the
    provider name alone (matches the Ollama fix applied to the same
    facade)."""
    monkeypatch.setenv("LEMONADE_BASE_URL", "http://lemonade-box.internal:13305")
    monkeypatch.setenv(
        "DOCKER_MODEL_RUNNER_BASE_URL", "http://dmr-box.internal:12434"
    )
    monkeypatch.setenv("FOUNDRY_LOCAL_BASE_URL", "http://foundry-box.internal:60160")
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
    assert by_id["lemonade:phi-4"].cost_lane == "free"
    assert by_id["lemonade:phi-4"].endpoint == "http://lemonade-box.internal:13305"
    assert by_id["docker-model-runner:qwen3"].cost_lane == "free"
    assert by_id["foundry-local:qwen2.5-coder-7b"].cost_lane == "free"


@pytest.mark.unit
def test_lmstudio_local_for_loopback_free_for_remote_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lmstudio_info = local_discovery.LocalModelInfo(id="lmstudio:phi-4")

    monkeypatch.setattr(
        local_discovery,
        "discover_lmstudio_catalog",
        lambda: local_discovery.LmStudioCatalog(models=(lmstudio_info,), api="v1"),
    )
    monkeypatch.setattr(
        local_discovery, "resolve_lmstudio_host", lambda: "http://127.0.0.1:1234"
    )
    result = discover_all_models()
    assert result[0].cost_lane == "local"

    monkeypatch.setattr(
        local_discovery,
        "resolve_lmstudio_host",
        lambda: "http://lmstudio-box.internal:1234",
    )
    result = discover_all_models()
    assert result[0].cost_lane == "free"
    assert result[0].endpoint == "http://lmstudio-box.internal:1234"


def _stub_ollama(
    monkeypatch: pytest.MonkeyPatch, infos: list[ollama_discovery.OllamaModelInfo]
) -> None:
    monkeypatch.setattr(ollama_discovery, "discover_ollama_models", lambda: infos)


@pytest.mark.unit
def test_ollama_no_key_stays_local_regardless_of_cloud_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without OLLAMA_API_KEY, build_ollama_model never reroutes (ADR-051) --
    so even a cloud=True record (e.g. a locally-listed :cloud-suffixed name
    with no remote_host stamp) stays at the local endpoint and "free" lane,
    not "paid"/CLOUD_HOST."""
    _stub_ollama(
        monkeypatch,
        [
            ollama_discovery.OllamaModelInfo(
                id="ollama:gemma4:31b", name="gemma4:31b", cloud=False
            ),
            ollama_discovery.OllamaModelInfo(
                id="ollama:deepseek-v4-flash:0731-cloud",
                name="deepseek-v4-flash:0731-cloud",
                cloud=True,
                remote_host=None,  # suffix-classified, not proxy-stamped
            ),
        ],
    )

    result = discover_all_models()
    by_id = {m.id: m for m in result}
    assert by_id["ollama:gemma4:31b"].cost_lane == "local"
    assert by_id["ollama:gemma4:31b"].endpoint == "http://localhost:11434"
    assert by_id["ollama:deepseek-v4-flash:0731-cloud"].cost_lane == "free"
    assert by_id["ollama:deepseek-v4-flash:0731-cloud"].endpoint == (
        "http://localhost:11434"
    )


@pytest.mark.unit
def test_ollama_keyed_and_locally_listed_stays_local_despite_cloud_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this test guards: cloud=True does not by itself mean "reached
    via CLOUD_HOST" -- _is_cloud() also classifies a LOCALLY-listed entry as
    cloud via its :cloud/-cloud name suffix alone, with no remote_host stamp.
    is_served_locally() (the same authority build_ollama_model itself
    consults) is what actually decides the endpoint, not the cloud flag."""
    monkeypatch.setenv("OLLAMA_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(
        ollama_discovery,
        "local_model_names",
        lambda: frozenset({"deepseek-v4-flash:0731-cloud"}),
    )
    _stub_ollama(
        monkeypatch,
        [
            ollama_discovery.OllamaModelInfo(
                id="ollama:deepseek-v4-flash:0731-cloud",
                name="deepseek-v4-flash:0731-cloud",
                cloud=True,
                remote_host=None,
            )
        ],
    )

    result = discover_all_models()
    assert result[0].endpoint == "http://localhost:11434"
    assert result[0].cost_lane == "free"  # still free -- it IS a cloud model


@pytest.mark.unit
def test_ollama_keyed_and_not_locally_listed_reroutes_to_cloud_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model genuinely absent from the local listing, with a key set, is
    the one case build_ollama_model actually reroutes -- endpoint must be
    CLOUD_HOST, not the local/configured one."""
    monkeypatch.setenv("OLLAMA_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(
        ollama_discovery, "local_model_names", lambda: frozenset()
    )
    _stub_ollama(
        monkeypatch,
        [
            ollama_discovery.OllamaModelInfo(
                id="ollama:gpt-oss:120b-cloud",
                name="gpt-oss:120b-cloud",
                cloud=True,
                remote_host=None,
            )
        ],
    )

    result = discover_all_models()
    assert result[0].endpoint == "https://ollama.com"
    assert result[0].cost_lane == "free"


@pytest.mark.unit
def test_ollama_remote_base_url_downgrades_lane_even_without_cloud_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-loopback OLLAMA_BASE_URL means every call already leaves this
    machine, regardless of key presence or the cloud classification --
    matching cost_lane_for's own downgrade for the curated-registry path."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama-box.internal:11434")
    _stub_ollama(
        monkeypatch,
        [
            ollama_discovery.OllamaModelInfo(
                id="ollama:qwen3-coder:30b", name="qwen3-coder:30b", cloud=False
            )
        ],
    )

    result = discover_all_models()
    assert result[0].cost_lane == "free"
    assert result[0].endpoint == "http://ollama-box.internal:11434"


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
