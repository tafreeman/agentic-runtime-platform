"""Tests for the curated single-source model registry (ADR-040).

Phase 1 scope: the data file loads and self-validates, the accessors return the
curated values, pricing is computed (or correctly withheld), and the validator
rejects the failure modes the registry exists to prevent (dangling references,
unknown providers). Drift-detection tests live alongside the probe in
``test_langchain_models_unit`` once that hook lands.
"""

from __future__ import annotations

import logging

import pytest

from agentic_v2.models import model_registry as mr


def _base_registry_dict() -> dict:
    """A minimal, internally-consistent registry payload for validator tests."""
    return {
        "version": 1,
        "models": [
            {"id": "gemini:gemini-2.5-flash", "provider": "gemini", "tiers": [1]},
            {"id": "ollama:qwen3:8b", "provider": "ollama", "tiers": [1]},
        ],
        "tiers": {
            t: ["gemini:gemini-2.5-flash", "ollama:qwen3:8b"] for t in range(1, 6)
        },
        "special": {
            "judge_default": "gemini:gemini-2.5-flash",
            "notebooklm_fallback": "gemini:gemini-2.5-flash",
            "tier_ultimate_fallback": "ollama:qwen3:8b",
        },
    }


# ---------------------------------------------------------------------------
# Production file integrity
# ---------------------------------------------------------------------------


def test_production_registry_loads():
    registry = mr.load_registry()
    assert registry.version == 1
    assert registry.models
    # every tier 1-5 has a non-empty chain
    for tier in range(1, 6):
        assert registry.tiers.get(tier), f"tier {tier} chain is empty"


def test_production_registry_has_no_dangling_references():
    """Every id referenced anywhere must have a models: entry (belt-and-suspenders
    over the loader's own _validate; this is the test that catches a tier chain
    pinning an id that was never declared)."""
    registry = mr.load_registry()
    ids = mr.all_ids()
    for tier, chain in registry.tiers.items():
        for model_id in chain:
            assert model_id in ids, f"tiers[{tier}] -> undeclared {model_id}"
    for slot in ("judge_default", "notebooklm_fallback", "tier_ultimate_fallback"):
        assert getattr(registry.special, slot) in ids


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def test_tier_chain_order_and_escalation():
    assert mr.tier_chain(1)[0] == "gemini:gemini-2.5-flash-lite"
    # tier 5 escalates to the reasoning models (ADR-040 reconciliation)
    assert "anthropic:claude-opus-4-6" in mr.tier_chain(5)
    assert "gemini:gemini-2.5-pro" in mr.tier_chain(5)
    assert mr.tier_chain(99) == ()


def test_special_accessor():
    assert mr.special("judge_default") == "gh:openai/gpt-4o"
    assert mr.special("tier_ultimate_fallback") == "ollama:qwen3:8b"
    with pytest.raises(AttributeError):
        mr.special("not_a_slot")


def test_provider_for_known_and_unknown():
    assert mr.provider_for("gemini:gemini-2.5-flash") == "gemini"
    # unknown id falls back to prefix parsing
    assert mr.provider_for("openai:some-future-model") == "openai"


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def test_price_for_unknown_returns_none_pair():
    # cloud models ship with null prices until a follow-up populates them
    assert mr.price_for("gemini:gemini-2.5-flash") == (None, None)
    assert mr.price_for("model-not-in-registry") == (None, None)


def test_compute_spend_uses_formula(monkeypatch: pytest.MonkeyPatch):
    price_in, price_out = 3.0, 15.0
    monkeypatch.setattr(mr, "price_for", lambda _mid: (price_in, price_out))
    prompt_tokens, completion_tokens = 1_000_000, 2_000_000
    expected = (
        prompt_tokens / 1_000_000 * price_in + completion_tokens / 1_000_000 * price_out
    )
    assert mr.compute_spend("any", prompt_tokens, completion_tokens) == expected


def test_compute_spend_unknown_price_returns_none_and_warns_once(
    caplog: pytest.LogCaptureFixture,
):
    mr.clear_cache()  # reset the warn-once guard
    with caplog.at_level(logging.WARNING, logger="agentic_v2.models.model_registry"):
        assert mr.compute_spend("gemini:gemini-2.5-flash", 100, 100) is None
        assert mr.compute_spend("gemini:gemini-2.5-flash", 100, 100) is None
    warnings = [r for r in caplog.records if "no curated price" in r.message]
    assert len(warnings) == 1  # warned once, not twice


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_accepts_clean_registry():
    registry = mr.Registry.model_validate(_base_registry_dict())
    mr._validate(registry)  # must not raise


def test_validate_rejects_dangling_tier_reference():
    payload = _base_registry_dict()
    payload["tiers"][1] = ["gemini:gemini-2.5-flash", "gemini:ghost-model"]
    registry = mr.Registry.model_validate(payload)
    with pytest.raises(ValueError, match="dangling"):
        mr._validate(registry)


def test_validate_rejects_unknown_provider():
    payload = _base_registry_dict()
    payload["models"].append({"id": "bogus:thing", "provider": "bogus", "tiers": []})
    registry = mr.Registry.model_validate(payload)
    with pytest.raises(ValueError, match="unknown providers"):
        mr._validate(registry)


def test_validate_rejects_missing_tier():
    """A registry missing a tier chain fails loudly at load, not as a later
    KeyError in ModelRouter.get_chain's DEFAULT_CHAINS[TIER_2] fallback."""
    payload = _base_registry_dict()
    del payload["tiers"][2]
    registry = mr.Registry.model_validate(payload)
    with pytest.raises(ValueError, match="missing a non-empty fallback chain"):
        mr._validate(registry)


# ---------------------------------------------------------------------------
# load_registry error contract (malformed YAML / invalid schema -> ValueError)
# ---------------------------------------------------------------------------


def test_load_registry_raises_valueerror_on_malformed_yaml(tmp_path, monkeypatch):
    bad = tmp_path / "model_registry.yaml"
    bad.write_text("version: 1\nmodels: [unclosed\n", encoding="utf-8")
    monkeypatch.setattr(mr, "_resolve_registry_path", lambda _root: bad)
    mr.clear_cache()
    with pytest.raises(ValueError, match="[Mm]alformed YAML"):
        mr.load_registry()


def test_load_registry_raises_valueerror_on_invalid_schema(tmp_path, monkeypatch):
    bad = tmp_path / "model_registry.yaml"
    # valid YAML, but missing the required tiers/special sections
    bad.write_text("version: 1\nmodels: []\n", encoding="utf-8")
    monkeypatch.setattr(mr, "_resolve_registry_path", lambda _root: bad)
    mr.clear_cache()
    with pytest.raises(ValueError, match="invalid model registry schema"):
        mr.load_registry()
