"""Tests for the centralized CI calculator (Sprint 9, Task 9.1).

Verifies:
  - compute_ci arithmetic: perfect scores, zero scores, partial, custom weights, missing dims
  - compute_ci geometric: perfect, zero collapse, partial
  - compute_ci validation: invalid method raises ValueError
  - check_gate: all pass, low dimension, insufficient sources, contradictions, regression, reason string
  - GateResult is frozen (immutable)
  - get_recency_window: known domains, unknown domain -> default
  - Immutable constants (MappingProxyType)
  - Exponential recency decay
  - Config-driven recency windows
"""

from __future__ import annotations

import dataclasses
import math

import pytest
from agentic_v2.workflows.lib.ci_calculator import (
    DEFAULT_WEIGHTS,
    DOMAIN_RECENCY_DAYS,
    RESEARCH_DIMENSIONS,
    check_gate,
    compute_ci,
    get_recency_window,
    load_recency_windows,
    recency_decay,
)

# ---------------------------------------------------------------------------
# compute_ci — arithmetic
# ---------------------------------------------------------------------------


class TestComputeCiArithmetic:
    """Arithmetic (weighted mean) CI computation."""

    def test_all_perfect_scores(self) -> None:
        scores = {dim: 1.0 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci(scores) == pytest.approx(1.0)

    def test_all_zero_scores(self) -> None:
        scores = {dim: 0.0 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci(scores) == pytest.approx(0.0)

    def test_partial_scores(self) -> None:
        scores = {dim: 0.5 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci(scores) == pytest.approx(0.5)

    def test_custom_weights(self) -> None:
        scores = {
            "coverage": 1.0,
            "source_quality": 0.0,
            "agreement": 0.0,
            "verification": 0.0,
            "recency": 0.0,
        }
        # Equal weights: 1.0 * 0.20 / 1.0 = 0.20
        equal_weights = {dim: 0.20 for dim in RESEARCH_DIMENSIONS}
        result = compute_ci(scores, weights=equal_weights)
        assert result == pytest.approx(0.20)

    def test_missing_dimensions_treated_as_zero(self) -> None:
        """Missing dimensions default to 0.0 score."""
        scores = {"coverage": 1.0}  # only one dimension
        result = compute_ci(scores)
        # Only coverage contributes: 1.0 * 0.25 / 1.0 = 0.25
        assert result == pytest.approx(0.25)

    def test_clamped_above_one(self) -> None:
        scores = {dim: 5.0 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci(scores) <= 1.0

    def test_clamped_below_zero(self) -> None:
        scores = {dim: -5.0 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci(scores) >= 0.0

    def test_single_dimension_with_default_weights(self) -> None:
        """Coverage alone with default weight 0.25 => CI = 0.25."""
        scores = {"coverage": 1.0}
        assert compute_ci(scores) == pytest.approx(0.25)

    def test_known_value(self) -> None:
        """Verify exact calculation: sum(s_i * w_i) / sum(w_i)."""
        scores = {
            "coverage": 0.8,
            "source_quality": 0.6,
            "agreement": 0.9,
            "verification": 0.7,
            "recency": 0.5,
        }
        # Manual: 0.8*0.25 + 0.6*0.20 + 0.9*0.20 + 0.7*0.20 + 0.5*0.15
        # = 0.20 + 0.12 + 0.18 + 0.14 + 0.075 = 0.715
        expected = 0.715
        assert compute_ci(scores) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# compute_ci — geometric
# ---------------------------------------------------------------------------


class TestComputeCiGeometric:
    """Geometric (weighted geometric mean) CI computation."""

    def test_all_perfect_scores(self) -> None:
        scores = {dim: 1.0 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci(scores, method="geometric") == pytest.approx(1.0)

    def test_one_zero_collapses_to_zero(self) -> None:
        """Geometric mean with any zero input should be 0.0."""
        scores = {dim: 0.8 for dim in RESEARCH_DIMENSIONS}
        scores["verification"] = 0.0
        assert compute_ci(scores, method="geometric") == pytest.approx(0.0)

    def test_partial_scores(self) -> None:
        """All 0.5 -> geometric mean should equal 0.5."""
        scores = {dim: 0.5 for dim in RESEARCH_DIMENSIONS}
        result = compute_ci(scores, method="geometric")
        # prod(0.5^w_i)^(1/sum_w) = 0.5^(sum_w/sum_w) = 0.5
        assert result == pytest.approx(0.5)

    def test_mixed_scores(self) -> None:
        """Geometric mean should be less than arithmetic mean for unequal inputs."""
        scores = {
            "coverage": 0.9,
            "source_quality": 0.3,
            "agreement": 0.8,
            "verification": 0.7,
            "recency": 0.6,
        }
        arithmetic = compute_ci(scores, method="arithmetic")
        geometric = compute_ci(scores, method="geometric")
        assert geometric < arithmetic

    def test_all_equal_scores(self) -> None:
        """When all scores are equal, geometric == arithmetic."""
        scores = {dim: 0.7 for dim in RESEARCH_DIMENSIONS}
        arith = compute_ci(scores, method="arithmetic")
        geo = compute_ci(scores, method="geometric")
        assert geo == pytest.approx(arith, abs=1e-9)


# ---------------------------------------------------------------------------
# compute_ci — validation
# ---------------------------------------------------------------------------


class TestComputeCiValidation:
    def test_invalid_method_raises_value_error(self) -> None:
        scores = {dim: 0.5 for dim in RESEARCH_DIMENSIONS}
        with pytest.raises(ValueError, match="method"):
            compute_ci(scores, method="harmonic")

    def test_arithmetic_method_accepted(self) -> None:
        scores = {dim: 0.5 for dim in RESEARCH_DIMENSIONS}
        compute_ci(scores, method="arithmetic")  # should not raise

    def test_geometric_method_accepted(self) -> None:
        scores = {dim: 0.5 for dim in RESEARCH_DIMENSIONS}
        compute_ci(scores, method="geometric")  # should not raise


# ---------------------------------------------------------------------------
# check_gate
# ---------------------------------------------------------------------------


class TestCheckGate:
    def _all_high_scores(self) -> dict[str, float]:
        return {dim: 0.80 for dim in RESEARCH_DIMENSIONS}

    def test_all_pass(self) -> None:
        result = check_gate(
            self._all_high_scores(),
            recent_source_count=5,
            min_recent_sources=3,
        )
        assert result.passed is True
        assert result.all_dimensions_high is True
        assert result.sources_floor_passed is True
        assert result.no_critical_contradictions is True
        assert result.no_regression is True
        assert result.reason == ""

    def test_low_dimension_fails(self) -> None:
        scores = self._all_high_scores()
        scores["verification"] = 0.30  # below 0.75 threshold
        result = check_gate(
            scores,
            recent_source_count=5,
            min_recent_sources=3,
        )
        assert result.passed is False
        assert result.all_dimensions_high is False
        assert "verification" in result.reason

    def test_insufficient_sources_fails(self) -> None:
        result = check_gate(
            self._all_high_scores(),
            recent_source_count=2,
            min_recent_sources=3,
        )
        assert result.passed is False
        assert result.sources_floor_passed is False
        assert "source" in result.reason.lower()

    def test_contradictions_fail(self) -> None:
        result = check_gate(
            self._all_high_scores(),
            recent_source_count=5,
            min_recent_sources=3,
            critical_contradictions=1,
        )
        assert result.passed is False
        assert result.no_critical_contradictions is False
        assert "contradiction" in result.reason.lower()

    def test_regression_fails(self) -> None:
        result = check_gate(
            self._all_high_scores(),
            recent_source_count=5,
            min_recent_sources=3,
            previous_ci=0.85,
            current_ci=0.70,
        )
        assert result.passed is False
        assert result.no_regression is False
        assert "regression" in result.reason.lower()

    def test_no_regression_when_ci_improves(self) -> None:
        result = check_gate(
            self._all_high_scores(),
            recent_source_count=5,
            min_recent_sources=3,
            previous_ci=0.70,
            current_ci=0.85,
        )
        assert result.no_regression is True

    def test_no_regression_when_no_previous(self) -> None:
        """First round has no previous CI to compare against."""
        result = check_gate(
            self._all_high_scores(),
            recent_source_count=5,
            min_recent_sources=3,
            previous_ci=None,
            current_ci=0.85,
        )
        assert result.no_regression is True

    def test_custom_high_threshold(self) -> None:
        scores = {dim: 0.80 for dim in RESEARCH_DIMENSIONS}
        # With higher threshold, 0.80 should fail
        result = check_gate(
            scores, high_threshold=0.90, recent_source_count=5, min_recent_sources=3
        )
        assert result.passed is False
        assert result.all_dimensions_high is False

    def test_reason_populated_on_first_failure(self) -> None:
        scores = self._all_high_scores()
        scores["coverage"] = 0.10
        result = check_gate(
            scores,
            recent_source_count=5,
            min_recent_sources=3,
        )
        assert result.reason != ""


# ---------------------------------------------------------------------------
# GateResult is frozen
# ---------------------------------------------------------------------------


class TestGateResultFrozen:
    def test_gate_result_is_frozen_dataclass(self) -> None:
        result = check_gate(
            {dim: 0.80 for dim in RESEARCH_DIMENSIONS},
            recent_source_count=5,
            min_recent_sources=3,
        )
        assert dataclasses.is_dataclass(result)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_recency_window
# ---------------------------------------------------------------------------


class TestGetRecencyWindow:
    @pytest.mark.parametrize(
        "domain, expected",
        [
            ("ai_ml", 90),
            ("cloud_infrastructure", 180),
            ("programming_languages", 365),
            ("academic_research", 730),
            ("default", 183),
        ],
    )
    def test_known_domain_windows(self, domain: str, expected: int) -> None:
        assert get_recency_window(domain) == expected

    def test_unknown_domain_returns_default(self) -> None:
        assert get_recency_window("nonexistent_domain") == 183

    def test_no_argument_returns_default(self) -> None:
        assert get_recency_window() == 183

    def test_config_windows_override(self) -> None:
        custom = {"ai_ml": 45, "default": 183}
        assert get_recency_window("ai_ml", config_windows=custom) == 45

    def test_all_domains_have_positive_values(self) -> None:
        for domain, days in DOMAIN_RECENCY_DAYS.items():
            assert days > 0, f"Domain '{domain}' has non-positive recency window"


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


class TestConstants:
    def test_research_dimensions_count(self) -> None:
        assert len(RESEARCH_DIMENSIONS) == 5

    def test_default_weights_sum_to_one(self) -> None:
        total = sum(DEFAULT_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_default_weights_cover_all_dimensions(self) -> None:
        for dim in RESEARCH_DIMENSIONS:
            assert dim in DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# Enhancement 1: Immutable constants (MappingProxyType)
# ---------------------------------------------------------------------------


class TestImmutableConstants:
    def test_default_weights_is_immutable(self) -> None:
        """DEFAULT_WEIGHTS should reject item assignment."""
        with pytest.raises(TypeError):
            DEFAULT_WEIGHTS["coverage"] = 0.99  # type: ignore[index]

    def test_domain_recency_days_is_immutable(self) -> None:
        """DOMAIN_RECENCY_DAYS should reject item assignment."""
        with pytest.raises(TypeError):
            DOMAIN_RECENCY_DAYS["ai_ml"] = 1  # type: ignore[index]

    def test_default_weights_still_readable(self) -> None:
        """MappingProxyType should still support .get() and iteration."""
        assert DEFAULT_WEIGHTS.get("coverage") == 0.25
        assert len(DEFAULT_WEIGHTS) == 5
        assert set(DEFAULT_WEIGHTS.keys()) == set(RESEARCH_DIMENSIONS)

    def test_domain_recency_days_still_readable(self) -> None:
        assert DOMAIN_RECENCY_DAYS.get("ai_ml") == 90
        assert "default" in DOMAIN_RECENCY_DAYS


# ---------------------------------------------------------------------------
# Enhancement 2: Exponential recency decay
# ---------------------------------------------------------------------------


class TestRecencyDecay:
    def test_age_zero_returns_one(self) -> None:
        """A brand-new source should have recency score 1.0."""
        assert recency_decay(0.0) == pytest.approx(1.0)

    def test_at_half_life_returns_half(self) -> None:
        """At exactly the half-life, score should be 0.5."""
        half_life = 90.0
        assert recency_decay(90.0, half_life_days=half_life) == pytest.approx(0.5)

    def test_at_double_half_life_returns_quarter(self) -> None:
        """At 2x half-life, score should be 0.25."""
        assert recency_decay(180.0, half_life_days=90.0) == pytest.approx(0.25)

    def test_very_old_approaches_zero(self) -> None:
        """Very old sources should have near-zero recency."""
        score = recency_decay(10000.0, half_life_days=90.0)
        assert score < 0.001

    def test_negative_age_returns_one(self) -> None:
        """Negative age (future source) clamps to 1.0."""
        assert recency_decay(-10.0) == pytest.approx(1.0)

    def test_domain_derived_half_life(self) -> None:
        """When half_life_days is None, uses domain recency window."""
        # ai_ml domain = 90 days; at 90 days should be 0.5
        score = recency_decay(90.0, domain="ai_ml")
        assert score == pytest.approx(0.5)

    def test_academic_domain_slower_decay(self) -> None:
        """Academic research (730 days) decays much slower than AI/ML (90 days)."""
        age = 365.0  # 1 year old
        ai_score = recency_decay(age, domain="ai_ml")
        academic_score = recency_decay(age, domain="academic_research")
        assert academic_score > ai_score

    def test_explicit_half_life_overrides_domain(self) -> None:
        """Explicit half_life_days takes precedence over domain lookup."""
        score_explicit = recency_decay(90.0, half_life_days=90.0)
        score_domain = recency_decay(90.0, domain="academic_research")
        assert score_explicit == pytest.approx(0.5)
        assert score_domain > 0.5  # 730-day half-life = slower decay

    def test_zero_half_life_edge_case(self) -> None:
        """Zero half-life: age=0 → 1.0, age>0 → 0.0."""
        assert recency_decay(0.0, half_life_days=0.0) == pytest.approx(1.0)
        assert recency_decay(1.0, half_life_days=0.0) == pytest.approx(0.0)

    def test_config_windows_passthrough(self) -> None:
        """Config-driven windows should override module defaults."""
        custom_windows = {"ai_ml": 30, "default": 183}
        # With 30-day half-life, 30 days old = 0.5
        score = recency_decay(30.0, domain="ai_ml", config_windows=custom_windows)
        assert score == pytest.approx(0.5)

    def test_decay_is_monotonically_decreasing(self) -> None:
        """Score should decrease as age increases."""
        scores = [
            recency_decay(float(d), half_life_days=90.0) for d in range(0, 500, 50)
        ]
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i - 1]

    def test_mathematical_correctness(self) -> None:
        """Verify against manual exp(-ln(2)/hl * age) calculation."""
        age = 45.0
        hl = 90.0
        expected = math.exp(-math.log(2) / hl * age)
        assert recency_decay(age, half_life_days=hl) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Enhancement 4: Config-driven recency windows
# ---------------------------------------------------------------------------


class TestLoadRecencyWindows:
    def test_returns_defaults_when_key_absent(self) -> None:
        result = load_recency_windows({})
        assert result["ai_ml"] == 90
        assert result["default"] == 183

    def test_returns_defaults_when_not_dict(self) -> None:
        cfg = {"evaluation": {"deep_research": {"recency_windows": "invalid"}}}
        result = load_recency_windows(cfg)
        assert result["ai_ml"] == 90

    def test_overrides_specific_domain(self) -> None:
        cfg = {"evaluation": {"deep_research": {"recency_windows": {"ai_ml": 30}}}}
        result = load_recency_windows(cfg)
        assert result["ai_ml"] == 30
        # Other domains should keep defaults
        assert result["academic_research"] == 730

    def test_adds_new_domain(self) -> None:
        cfg = {"evaluation": {"deep_research": {"recency_windows": {"fintech": 60}}}}
        result = load_recency_windows(cfg)
        assert result["fintech"] == 60

    def test_result_is_immutable(self) -> None:
        cfg = {"evaluation": {"deep_research": {"recency_windows": {"ai_ml": 30}}}}
        result = load_recency_windows(cfg)
        with pytest.raises(TypeError):
            result["ai_ml"] = 999  # type: ignore[index]

    def test_ignores_non_integer_values(self) -> None:
        cfg = {
            "evaluation": {
                "deep_research": {
                    "recency_windows": {"ai_ml": "not_a_number", "default": 100}
                }
            }
        }
        result = load_recency_windows(cfg)
        # ai_ml should keep original default since override is invalid
        assert result["ai_ml"] == 90
        # default should be overridden since 100 is valid
        assert result["default"] == 100

    def test_ignores_non_positive_values(self) -> None:
        """Zero and negative integers must be rejected; domain falls back to default."""
        cfg_zero = {"evaluation": {"deep_research": {"recency_windows": {"ai_ml": 0}}}}
        assert load_recency_windows(cfg_zero)["ai_ml"] == 90

        cfg_negative = {
            "evaluation": {"deep_research": {"recency_windows": {"ai_ml": -30}}}
        }
        assert load_recency_windows(cfg_negative)["ai_ml"] == 90

    def test_get_recency_window_with_config(self) -> None:
        """Integration: get_recency_window accepts config_windows kwarg."""
        custom = {"ai_ml": 30, "default": 183}
        assert get_recency_window("ai_ml", config_windows=custom) == 30
        assert get_recency_window("unknown", config_windows=custom) == 183
