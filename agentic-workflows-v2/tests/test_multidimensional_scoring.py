"""Tests for the ADR-007 multidimensional research scoring engine.

These tests run entirely in isolation — no network, no LLM calls, no disk I/O.
They verify:
  - Tier classification thresholds
  - Non-compensatory gate logic (one Low blocks the pass)
  - CI tiebreaker computation
  - coalesce() best-of-N selection
  - Feature-flag router (legacy vs multidimensional)
  - Step-output convenience wrapper
"""

from __future__ import annotations

import pytest
from agentic_v2.server.multidimensional_scoring import (
    RESEARCH_DIMENSIONS,
    MultidimensionalGateResult,
    ResearchTier,
    classify_dimension,
    coalesce_best_round,
    compute_ci_tiebreaker,
    evaluate_research_round,
    evaluate_research_round_from_step_outputs,
    is_multidimensional_engine_active,
    research_stop_gate,
)

# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------


class TestClassifyDimension:
    def test_elite_boundary(self) -> None:
        assert classify_dimension("coverage", 0.90) == ResearchTier.ELITE

    def test_elite_above(self) -> None:
        assert classify_dimension("coverage", 1.00) == ResearchTier.ELITE

    def test_high_lower_boundary(self) -> None:
        assert classify_dimension("coverage", 0.75) == ResearchTier.HIGH

    def test_high_just_below_elite(self) -> None:
        assert classify_dimension("coverage", 0.89) == ResearchTier.HIGH

    def test_medium_lower_boundary(self) -> None:
        assert classify_dimension("verification", 0.50) == ResearchTier.MEDIUM

    def test_medium_just_below_high(self) -> None:
        assert classify_dimension("agreement", 0.74) == ResearchTier.MEDIUM

    def test_low_just_below_medium(self) -> None:
        assert classify_dimension("recency", 0.49) == ResearchTier.LOW

    def test_low_zero(self) -> None:
        assert classify_dimension("source_quality", 0.0) == ResearchTier.LOW

    def test_unknown_dimension_uses_defaults(self) -> None:
        # Unknown dimension falls back to default thresholds
        tier = classify_dimension("nonexistent_dim", 0.80)
        assert tier == ResearchTier.HIGH

    @pytest.mark.parametrize("dim", RESEARCH_DIMENSIONS)
    def test_all_dimensions_classified(self, dim: str) -> None:
        assert classify_dimension(dim, 0.80) == ResearchTier.HIGH


# ---------------------------------------------------------------------------
# Tier rank / meets_minimum
# ---------------------------------------------------------------------------


class TestResearchTierRank:
    def test_elite_rank_is_highest(self) -> None:
        assert ResearchTier.ELITE.rank > ResearchTier.HIGH.rank

    def test_low_rank_is_lowest(self) -> None:
        assert ResearchTier.LOW.rank < ResearchTier.MEDIUM.rank

    def test_meets_minimum_same_tier(self) -> None:
        assert ResearchTier.HIGH.meets_minimum(ResearchTier.HIGH)

    def test_elite_meets_high(self) -> None:
        assert ResearchTier.ELITE.meets_minimum(ResearchTier.HIGH)

    def test_medium_fails_high(self) -> None:
        assert not ResearchTier.MEDIUM.meets_minimum(ResearchTier.HIGH)

    def test_low_fails_high(self) -> None:
        assert not ResearchTier.LOW.meets_minimum(ResearchTier.HIGH)


# ---------------------------------------------------------------------------
# evaluate_research_round — gate logic
# ---------------------------------------------------------------------------


def _all_high(**overrides: float) -> dict[str, float]:
    """Return keyword args for a passing all-High round."""
    defaults = {
        "coverage_score": 0.80,
        "source_quality_score": 0.80,
        "agreement_score": 0.80,
        "verification_score": 0.80,
        "recency_score": 0.80,
    }
    return {**defaults, **overrides}


class TestEvaluateResearchRound:
    def test_all_high_passes(self) -> None:
        result = evaluate_research_round(
            **_all_high(),
            recent_sources_count=12,
            critical_contradictions=0,
        )
        assert result.gate_passed is True

    def test_all_elite_passes(self) -> None:
        result = evaluate_research_round(
            coverage_score=0.95,
            source_quality_score=0.95,
            agreement_score=0.95,
            verification_score=0.95,
            recency_score=0.95,
            recent_sources_count=15,
            critical_contradictions=0,
        )
        assert result.gate_passed is True

    def test_one_medium_fails_gate(self) -> None:
        """Non-compensatory: single Medium blocks the pass."""
        result = evaluate_research_round(
            **_all_high(verification_score=0.60),  # < 0.75 → Medium
            recent_sources_count=12,
            critical_contradictions=0,
        )
        assert result.gate_passed is False
        assert "verification" in result.failed_dimensions

    def test_one_low_fails_gate(self) -> None:
        result = evaluate_research_round(
            **_all_high(coverage_score=0.20),
            recent_sources_count=12,
            critical_contradictions=0,
        )
        assert result.gate_passed is False

    def test_high_scores_cannot_compensate_low_verification(self) -> None:
        """The key ADR-007 property: no compensability."""
        result = evaluate_research_round(
            coverage_score=0.95,  # Elite
            source_quality_score=0.95,  # Elite
            agreement_score=0.90,  # Elite
            verification_score=0.20,  # LOW ← failure
            recency_score=0.95,  # Elite
            recent_sources_count=20,
            critical_contradictions=0,
        )
        assert result.gate_passed is False
        assert "verification" in result.failed_dimensions

    def test_insufficient_recent_sources_fails(self) -> None:
        result = evaluate_research_round(
            **_all_high(),
            recent_sources_count=5,  # < 10
            critical_contradictions=0,
        )
        assert result.gate_passed is False
        assert result.sources_floor_passed is False

    def test_critical_contradiction_fails(self) -> None:
        result = evaluate_research_round(
            **_all_high(),
            recent_sources_count=12,
            critical_contradictions=1,
        )
        assert result.gate_passed is False
        assert result.no_critical_contradictions is False

    def test_consecutive_regression_fails(self) -> None:
        result = evaluate_research_round(
            **_all_high(),
            recent_sources_count=12,
            critical_contradictions=0,
            consecutive_regression=True,
        )
        assert result.gate_passed is False

    def test_ci_tiebreaker_present(self) -> None:
        result = evaluate_research_round(
            **_all_high(),
            recent_sources_count=12,
            critical_contradictions=0,
        )
        assert 0.0 <= result.ci_tiebreaker <= 1.0

    def test_to_dict_keys(self) -> None:
        result = evaluate_research_round(
            **_all_high(),
            recent_sources_count=12,
            critical_contradictions=0,
        )
        d = result.to_dict()
        assert "gate_passed" in d
        assert "ci_score" in d
        assert "dimension_matrix" in d
        assert "scoring_engine" in d
        assert d["scoring_engine"] == "multidimensional"
        assert d["ci_role"] == "tiebreaker_only"

    def test_custom_tier_thresholds_do_not_mutate_module(self) -> None:
        """ADR-007 bug fix: passing tier_thresholds must not bleed into
        subsequent calls that do *not* pass overrides."""
        custom = {"verification": (0.95, 0.90, 0.70)}  # stricter
        # First call uses stricter thresholds — 0.80 should be Medium, not High
        result_strict = evaluate_research_round(
            **_all_high(verification_score=0.80),
            recent_sources_count=12,
            critical_contradictions=0,
            tier_thresholds=custom,
        )
        # Under strict thresholds 0.80 < 0.90 (high_floor) → Medium → fails
        assert result_strict.gate_passed is False

        # Second call without overrides — should use default thresholds
        # 0.80 >= 0.75 (default high_floor) → High → passes
        result_default = evaluate_research_round(
            **_all_high(verification_score=0.80),
            recent_sources_count=12,
            critical_contradictions=0,
        )
        assert (
            result_default.gate_passed is True
        ), "Module-level _SCORE_THRESHOLDS was mutated by the previous call!"


# ---------------------------------------------------------------------------
# CI tiebreaker
# ---------------------------------------------------------------------------


class TestComputeCiTiebreaker:
    def test_all_ones(self) -> None:
        scores = {dim: 1.0 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci_tiebreaker(scores) == pytest.approx(1.0)

    def test_all_zeros(self) -> None:
        scores = {dim: 0.0 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci_tiebreaker(scores) == pytest.approx(0.0)

    def test_known_value(self) -> None:
        # coverage=1.0(w=0.25), rest=0.0 → 0.25
        scores = {
            "coverage": 1.0,
            "source_quality": 0.0,
            "agreement": 0.0,
            "verification": 0.0,
            "recency": 0.0,
        }
        assert compute_ci_tiebreaker(scores) == pytest.approx(0.25)

    def test_equal_weights_override(self) -> None:
        equal_w = {dim: 0.20 for dim in RESEARCH_DIMENSIONS}
        scores = {dim: 0.50 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci_tiebreaker(scores, weights=equal_w) == pytest.approx(0.50)

    def test_clamped_above_one(self) -> None:
        scores = {dim: 2.0 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci_tiebreaker(scores) <= 1.0

    def test_clamped_below_zero(self) -> None:
        scores = {dim: -1.0 for dim in RESEARCH_DIMENSIONS}
        assert compute_ci_tiebreaker(scores) >= 0.0


# ---------------------------------------------------------------------------
# coalesce_best_round
# ---------------------------------------------------------------------------


class TestCoalesceBestRound:
    def _make(self, gate_passed: bool, ci: float) -> dict:
        return {"gate_passed": gate_passed, "ci_score": ci}

    def test_prefers_passing_round(self) -> None:
        rounds = [
            self._make(False, 0.90),  # higher CI but failed
            self._make(True, 0.78),  # lower CI but passed
        ]
        best = coalesce_best_round(rounds)
        assert best is not None
        assert best["gate_passed"] is True

    def test_among_passing_picks_highest_ci(self) -> None:
        rounds = [
            self._make(True, 0.78),
            self._make(True, 0.85),
            self._make(True, 0.80),
        ]
        best = coalesce_best_round(rounds)
        assert best is not None
        assert best["ci_score"] == pytest.approx(0.85)

    def test_all_fail_picks_highest_ci(self) -> None:
        rounds = [
            self._make(False, 0.50),
            self._make(False, 0.70),
            self._make(False, 0.60),
        ]
        best = coalesce_best_round(rounds)
        assert best is not None
        assert best["ci_score"] == pytest.approx(0.70)

    def test_empty_list_returns_none(self) -> None:
        assert coalesce_best_round([]) is None

    def test_none_entries_skipped(self) -> None:
        rounds = [None, self._make(True, 0.80), None]  # type: ignore[list-item]
        best = coalesce_best_round(rounds)  # type: ignore[arg-type]
        assert best is not None
        assert best["ci_score"] == pytest.approx(0.80)

    def test_same_ci_prefers_earlier_round(self) -> None:
        """Lexicographic tiebreak: earlier round wins when CI is identical."""
        r1 = self._make(True, 0.85)
        r1["round"] = "R1"
        r2 = self._make(True, 0.85)
        r2["round"] = "R2"
        best = coalesce_best_round([r1, r2])
        assert best is not None
        assert best["round"] == "R1"

    def test_failing_same_ci_prefers_earlier(self) -> None:
        """Among failing rounds with equal CI, earlier round wins."""
        r1 = self._make(False, 0.60)
        r1["round"] = "R1"
        r2 = self._make(False, 0.60)
        r2["round"] = "R2"
        best = coalesce_best_round([r1, r2])
        assert best is not None
        assert best["round"] == "R1"

    def test_passing_always_beats_failing_regardless_of_ci(self) -> None:
        """A passing round with low CI still beats a failing round with high CI."""
        rounds = [
            self._make(False, 0.99),
            self._make(True, 0.01),
        ]
        best = coalesce_best_round(rounds)
        assert best is not None
        assert best["gate_passed"] is True
        assert best["ci_score"] == pytest.approx(0.01)

    def test_single_round(self) -> None:
        """Single round should be returned regardless of gate status."""
        rounds = [self._make(False, 0.50)]
        best = coalesce_best_round(rounds)
        assert best is not None
        assert best["ci_score"] == pytest.approx(0.50)

    def test_lexicographic_four_rounds(self) -> None:
        """Full R1-R4 scenario: R2 passes first, R4 also passes with same CI."""
        r1 = {**self._make(False, 0.60), "round": "R1"}
        r2 = {**self._make(True, 0.80), "round": "R2"}
        r3 = {**self._make(False, 0.70), "round": "R3"}
        r4 = {**self._make(True, 0.80), "round": "R4"}
        best = coalesce_best_round([r1, r2, r3, r4])
        assert best is not None
        # R2 and R4 both pass with 0.80 CI — R2 wins (earlier index)
        assert best["round"] == "R2"


# ---------------------------------------------------------------------------
# Feature-flag router
# ---------------------------------------------------------------------------


class TestIsMultidimensionalEngineActive:
    def test_multidimensional_flag(self) -> None:
        cfg = {"evaluation": {"deep_research": {"scoring_engine": "multidimensional"}}}
        assert is_multidimensional_engine_active(cfg) is True

    def test_legacy_flag(self) -> None:
        cfg = {"evaluation": {"deep_research": {"scoring_engine": "legacy"}}}
        assert is_multidimensional_engine_active(cfg) is False

    def test_missing_key_defaults_legacy(self) -> None:
        assert is_multidimensional_engine_active({}) is False

    def test_case_insensitive(self) -> None:
        cfg = {"evaluation": {"deep_research": {"scoring_engine": "Multidimensional"}}}
        assert is_multidimensional_engine_active(cfg) is True


class TestResearchStopGate:
    """Round-trip tests through the engine router."""

    _step_output_high = {
        "coverage_score": 0.80,
        "source_quality_score": 0.80,
        "agreement_score": 0.80,
        "verification_score": 0.80,
        "recency_score": 0.80,
        "recent_source_count": 15,
        "critical_contradictions": 0,
        "ci_score": 0.80,
    }

    _cfg_new = {"evaluation": {"deep_research": {"scoring_engine": "multidimensional"}}}
    _cfg_legacy = {
        "evaluation": {"deep_research": {"scoring_engine": "legacy", "min_ci": 0.80}}
    }

    def test_new_engine_returns_gate_passed_true(self) -> None:
        result = research_stop_gate(self._step_output_high, self._cfg_new)
        assert result["gate_passed"] is True
        assert result["scoring_engine"] == "multidimensional"

    def test_new_engine_has_ci_score_key(self) -> None:
        result = research_stop_gate(self._step_output_high, self._cfg_new)
        assert "ci_score" in result

    def test_legacy_engine_passes_above_threshold(self) -> None:
        result = research_stop_gate(self._step_output_high, self._cfg_legacy)
        assert result["gate_passed"] is True
        assert result["scoring_engine"] == "legacy"

    def test_legacy_engine_fails_below_threshold(self) -> None:
        step = {**self._step_output_high, "ci_score": 0.70}
        result = research_stop_gate(step, self._cfg_legacy)
        assert result["gate_passed"] is False

    def test_new_engine_non_compensatory_fail(self) -> None:
        step = {**self._step_output_high, "verification_score": 0.30}
        result = research_stop_gate(step, self._cfg_new)
        assert result["gate_passed"] is False


# ---------------------------------------------------------------------------
# Step-output convenience wrapper
# ---------------------------------------------------------------------------


class TestEvaluateFromStepOutputs:
    def test_reads_from_dict(self) -> None:
        outputs = {
            "coverage_score": 0.85,
            "source_quality_score": 0.85,
            "agreement_score": 0.85,
            "verification_score": 0.85,
            "recency_score": 0.85,
            "recent_source_count": 12,
            "critical_contradictions": 0,
        }
        result = evaluate_research_round_from_step_outputs(outputs)
        assert isinstance(result, MultidimensionalGateResult)
        assert result.gate_passed is True

    def test_missing_keys_default_to_zero(self) -> None:
        result = evaluate_research_round_from_step_outputs({})
        assert result.gate_passed is False
        assert result.ci_tiebreaker == pytest.approx(0.0)

    def test_string_numeric_values_coerced(self) -> None:
        """Agent step outputs may return numbers as strings."""
        outputs = {
            "coverage_score": "0.80",
            "source_quality_score": "0.80",
            "agreement_score": "0.80",
            "verification_score": "0.80",
            "recency_score": "0.80",
            "recent_source_count": "12",
            "critical_contradictions": "0",
        }
        result = evaluate_research_round_from_step_outputs(outputs)
        assert result.gate_passed is True
