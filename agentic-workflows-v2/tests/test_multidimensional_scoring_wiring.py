"""Tests for Sprint 9 Task 9.2: Wiring multidimensional scoring through CI calculator.

Verifies that ``compute_ci_tiebreaker`` in ``server/multidimensional_scoring.py``
still works correctly after delegation to the centralized ``ci_calculator.compute_ci``.
"""

from __future__ import annotations

import pytest
from agentic_v2.server.multidimensional_scoring import (
    RESEARCH_DIMENSIONS,
    compute_ci_tiebreaker,
    evaluate_research_round,
)
from agentic_v2.workflows.lib.ci_calculator import (
    RESEARCH_DIMENSIONS as LIB_RESEARCH_DIMENSIONS,
)
from agentic_v2.workflows.lib.ci_calculator import (
    compute_ci,
)


class TestComputeCiTiebreakerDelegation:
    """Verify backward-compatible delegation from server module to lib."""

    def test_all_ones_matches_lib(self) -> None:
        scores = {dim: 1.0 for dim in RESEARCH_DIMENSIONS}
        server_result = compute_ci_tiebreaker(scores)
        lib_result = compute_ci(scores, method="arithmetic")
        assert server_result == pytest.approx(lib_result)

    def test_all_zeros_matches_lib(self) -> None:
        scores = {dim: 0.0 for dim in RESEARCH_DIMENSIONS}
        server_result = compute_ci_tiebreaker(scores)
        lib_result = compute_ci(scores, method="arithmetic")
        assert server_result == pytest.approx(lib_result)

    def test_partial_scores_match_lib(self) -> None:
        scores = {
            "coverage": 0.80,
            "source_quality": 0.60,
            "agreement": 0.90,
            "verification": 0.70,
            "recency": 0.50,
        }
        server_result = compute_ci_tiebreaker(scores)
        lib_result = compute_ci(scores, method="arithmetic")
        assert server_result == pytest.approx(lib_result)

    def test_custom_weights_match_lib(self) -> None:
        equal_w = {dim: 0.20 for dim in RESEARCH_DIMENSIONS}
        scores = {dim: 0.50 for dim in RESEARCH_DIMENSIONS}
        server_result = compute_ci_tiebreaker(scores, weights=equal_w)
        lib_result = compute_ci(scores, weights=equal_w, method="arithmetic")
        assert server_result == pytest.approx(lib_result)

    def test_existing_api_signature_unchanged(self) -> None:
        """The server function still accepts the same kwargs."""
        scores = {dim: 0.80 for dim in RESEARCH_DIMENSIONS}
        # Positional: scores only
        result1 = compute_ci_tiebreaker(scores)
        # With keyword weights
        result2 = compute_ci_tiebreaker(scores, weights=None)
        assert result1 == pytest.approx(result2)

    def test_evaluate_research_round_still_computes_ci(self) -> None:
        """Full integration: evaluate_research_round still populates ci_tiebreaker."""
        result = evaluate_research_round(
            coverage_score=0.80,
            source_quality_score=0.80,
            agreement_score=0.80,
            verification_score=0.80,
            recency_score=0.80,
            recent_sources_count=12,
            critical_contradictions=0,
        )
        assert 0.0 <= result.ci_tiebreaker <= 1.0
        assert result.ci_tiebreaker == pytest.approx(0.80)

    def test_dimensions_constant_consistent(self) -> None:
        """Both modules expose the same dimension names."""
        assert set(RESEARCH_DIMENSIONS) == set(LIB_RESEARCH_DIMENSIONS)
