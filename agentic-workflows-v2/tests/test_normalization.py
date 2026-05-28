"""Tests for score normalization formulas and reliability adjustment."""

from __future__ import annotations

import pytest
from agentic_v2.server.normalization import adjust_for_sample_size, normalize_score


def test_binary_normalization():
    assert normalize_score(0, "binary") == 0.0
    assert normalize_score(1, "binary") == 1.0


def test_likert_1_5_normalization():
    assert normalize_score(1, "likert_1_5") == pytest.approx(0.0)
    assert normalize_score(3, "likert_1_5") == pytest.approx(0.5)
    assert normalize_score(5, "likert_1_5") == pytest.approx(1.0)


def test_likert_neg2_2_normalization():
    assert normalize_score(-2, "likert_neg2_2") == pytest.approx(0.0)
    assert normalize_score(0, "likert_neg2_2") == pytest.approx(0.5)
    assert normalize_score(2, "likert_neg2_2") == pytest.approx(1.0)


def test_lower_is_better_normalization():
    assert normalize_score(
        8, "lower_is_better", slo_good=8, slo_bad=30
    ) == pytest.approx(1.0)
    assert normalize_score(
        30, "lower_is_better", slo_good=8, slo_bad=30
    ) == pytest.approx(0.0)


def test_zero_one_passthrough_clamps():
    assert normalize_score(1.5, "zero_one") == pytest.approx(1.0)
    assert normalize_score(-0.5, "zero_one") == pytest.approx(0.0)
    assert normalize_score(0.7, "zero_one") == pytest.approx(0.7)


def test_pairwise_normalization():
    assert normalize_score(None, "pairwise", wins=3, ties=1, losses=1) == pytest.approx(
        0.7
    )


def test_unknown_formula_id_raises():
    with pytest.raises(KeyError, match="Unknown normalization formula"):
        normalize_score(0.5, "does_not_exist")


def test_reliability_adjustment_pulls_toward_prior():
    adjusted = adjust_for_sample_size(0.9, n=5)
    assert adjusted < 0.9
    assert adjusted > 0.5


def test_reliability_adjustment_large_n_negligible():
    adjusted = adjust_for_sample_size(0.9, n=1000)
    assert adjusted == pytest.approx(0.9, abs=0.01)
