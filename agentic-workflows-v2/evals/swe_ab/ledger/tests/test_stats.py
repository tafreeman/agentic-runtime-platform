"""Tests for ledger.stats: Wilson, McNemar, bootstrap, Cochran's Q (with
its hand-implemented chi-square tail), Holm correction, and the paired
sign-flip permutation test.

No database involved -- every function under test is pure.
"""

from __future__ import annotations

import math

import pytest

from ledger.stats import (
    ConfidenceInterval,
    QResult,
    chi2_sf,
    cochrans_q,
    holm_correction,
    mcnemar_exact,
    paired_bootstrap,
    permutation_test_paired,
    wilson,
)

# ---------------------------------------------------------------------
# wilson
# ---------------------------------------------------------------------


def test_wilson_zero_total_is_degenerate() -> None:
    ci = wilson(0, 0)
    assert ci == ConfidenceInterval(point=0.0, low=0.0, high=0.0)


def test_wilson_point_estimate_is_the_naive_rate() -> None:
    ci = wilson(3, 10)
    assert ci.point == pytest.approx(0.3)
    assert 0.0 <= ci.low < ci.point < ci.high <= 1.0


def test_wilson_interval_stays_inside_unit_range_at_extremes() -> None:
    ci_all_pass = wilson(5, 5)
    assert ci_all_pass.point == 1.0
    assert ci_all_pass.high == 1.0
    assert ci_all_pass.low > 0.0  # Wilson never collapses to a point at n=5

    ci_all_fail = wilson(0, 5)
    assert ci_all_fail.point == 0.0
    assert ci_all_fail.low == 0.0
    assert ci_all_fail.high < 1.0


def test_wilson_matches_hand_computed_interval() -> None:
    # successes=1, total=1: phat=1, z=1.959963984540054.
    # denom = 1 + z^2/1 = 4.841064...
    # centre = (1 + z^2/2) / denom
    z = 1.959963984540054
    denom = 1 + z * z
    centre = (1 + z * z / 2) / denom
    margin = z * math.sqrt(0 + z * z / 4) / denom
    ci = wilson(1, 1)
    assert ci.low == pytest.approx(max(0.0, centre - margin), abs=1e-12)
    assert ci.high == pytest.approx(min(1.0, centre + margin), abs=1e-12)


def test_wilson_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError):
        wilson(-1, 5)
    with pytest.raises(ValueError):
        wilson(6, 5)
    with pytest.raises(ValueError):
        wilson(1, -1)


# ---------------------------------------------------------------------
# mcnemar_exact
# ---------------------------------------------------------------------


def test_mcnemar_exact_zero_discordant_is_p_one() -> None:
    assert mcnemar_exact(0, 0) == 1.0


def test_mcnemar_exact_known_discordant_table_by_hand() -> None:
    # b=1, c=9: n=10, k=min(b,c)=1.
    # tail = (C(10,0) + C(10,1)) / 2**10 = (1 + 10) / 1024 = 11/1024
    # p = min(1, 2 * 11/1024) = 22/1024 = 0.021484375
    assert mcnemar_exact(1, 9) == pytest.approx(22 / 1024, abs=1e-12)
    assert mcnemar_exact(9, 1) == pytest.approx(
        22 / 1024, abs=1e-12
    )  # symmetric in b, c


def test_mcnemar_exact_balanced_discordance_is_p_one() -> None:
    # b == c is the least informative case there is; the two-sided exact
    # test must not manufacture significance out of a perfect split.
    assert mcnemar_exact(5, 5) == 1.0


def test_mcnemar_exact_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        mcnemar_exact(-1, 0)
    with pytest.raises(ValueError):
        mcnemar_exact(0, -1)


# ---------------------------------------------------------------------
# paired_bootstrap
# ---------------------------------------------------------------------


def test_paired_bootstrap_empty_is_degenerate() -> None:
    ci = paired_bootstrap([])
    assert ci == ConfidenceInterval(point=0.0, low=0.0, high=0.0)


def test_paired_bootstrap_constant_deltas_collapse_to_a_point() -> None:
    # Every resample of a constant sequence has the same mean, so the
    # interval must collapse to that single value with zero width.
    ci = paired_bootstrap([1.0, 1.0, 1.0, 1.0], samples=500, seed=1)
    assert ci.point == 1.0
    assert ci.low == pytest.approx(1.0)
    assert ci.high == pytest.approx(1.0)


def test_paired_bootstrap_is_reproducible_given_the_same_seed() -> None:
    deltas = [1.0, 0.0, -1.0, 1.0, 0.0, -1.0, 1.0]
    first = paired_bootstrap(deltas, samples=2000, seed=42)
    second = paired_bootstrap(deltas, samples=2000, seed=42)
    assert first == second


def test_paired_bootstrap_interval_brackets_the_point() -> None:
    deltas = [1.0, 0.0, 0.0, 1.0, -1.0, 0.0, 1.0, 0.0]
    ci = paired_bootstrap(deltas, samples=2000, seed=7)
    assert ci.low <= ci.point <= ci.high


# ---------------------------------------------------------------------
# chi2_sf -- validated against three published chi-square critical
# values (0.05 significance level, df 1/2/3) plus two closed-form
# identities so the hand-rolled incomplete-gamma implementation is
# cross-checked by more than just table lookups.
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("df", "critical_value", "expected_p"),
    [
        # Standard chi-square table, alpha=0.05 row.
        (1, 3.841459, 0.05),
        (2, 5.991465, 0.05),
        (3, 7.814728, 0.05),
        (5, 11.070498, 0.05),
        # alpha=0.01 row, df=1, thrown in for a second significance level.
        (1, 6.634897, 0.01),
    ],
)
def test_chi2_sf_matches_published_critical_values(
    df: int, critical_value: float, expected_p: float
) -> None:
    assert chi2_sf(critical_value, df) == pytest.approx(expected_p, abs=1e-4)


def test_chi2_sf_df_two_has_a_closed_form() -> None:
    # chi2_sf(x, 2) == exp(-x/2) exactly -- the one df where the
    # incomplete-gamma reduces to an elementary function, so this checks
    # the implementation against real closed-form math, not a table.
    for x in (0.5, 2.0, 6.0, 15.0):
        assert chi2_sf(x, 2) == pytest.approx(math.exp(-x / 2), abs=1e-12)


def test_chi2_sf_df_one_matches_the_squared_normal_identity() -> None:
    # A chi-square variable with 1 degree of freedom is a squared
    # standard normal, so its survival function is exactly
    # 2 * (1 - Phi(sqrt(x))), independent of the gamma-function route
    # chi2_sf actually takes to get there.
    def normal_cdf(z: float) -> float:
        return 0.5 * (1 + math.erf(z / math.sqrt(2)))

    for x in (0.1, 1.0, 3.841459, 10.0):
        expected = 2 * (1 - normal_cdf(math.sqrt(x)))
        assert chi2_sf(x, 1) == pytest.approx(expected, abs=1e-9)


def test_chi2_sf_at_zero_is_one() -> None:
    assert chi2_sf(0.0, 3) == 1.0


def test_chi2_sf_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        chi2_sf(1.0, 0)
    with pytest.raises(ValueError):
        chi2_sf(-1.0, 1)


# ---------------------------------------------------------------------
# cochrans_q
# ---------------------------------------------------------------------


def test_cochrans_q_matches_hand_computed_statistic() -> None:
    # 3 arms, 4 instances.
    table = [
        [1, 1, 0],
        [1, 0, 0],
        [0, 1, 1],
        [1, 1, 1],
    ]
    # T = [3, 3, 2], sum_t=8, sum_t_sq=22
    # L = [2, 1, 2, 3], sum_l=8, sum_l_sq=18
    # denom = 3*8 - 18 = 6
    # Q = 2 * (3*22 - 64) / 6 = 2 * 2 / 6 = 2/3
    result = cochrans_q(table)
    assert result.q == pytest.approx(2 / 3, abs=1e-12)
    assert result.df == 2
    # df=2 has the closed-form survival exp(-x/2) -- reuse it here so
    # this is checked against real math, not just against chi2_sf itself.
    assert result.p_value == pytest.approx(math.exp(-1 / 3), abs=1e-12)


def test_cochrans_q_no_variation_returns_p_one_not_a_division_error() -> None:
    # Every instance passes under every arm: no row varies, so there is
    # no information to discriminate arms with.
    table = [[1, 1, 1], [1, 1, 1], [1, 1, 1]]
    result = cochrans_q(table)
    assert result.q == 0.0
    assert result.p_value == 1.0


def test_cochrans_q_rejects_bad_shapes_and_values() -> None:
    with pytest.raises(ValueError):
        cochrans_q([])
    with pytest.raises(ValueError):
        cochrans_q([[1]])  # only 1 column
    with pytest.raises(ValueError):
        cochrans_q([[1, 0], [1]])  # ragged
    with pytest.raises(ValueError):
        cochrans_q([[1, 2]])  # not 0/1


# ---------------------------------------------------------------------
# holm_correction
# ---------------------------------------------------------------------


def test_holm_correction_worked_example_in_sorted_order() -> None:
    # m=4. Sorted p: 0.01, 0.02, 0.03, 0.04.
    #   rank0: 4*0.01=0.04, running=0.04
    #   rank1: 3*0.02=0.06, running=0.06
    #   rank2: 2*0.03=0.06, running stays 0.06
    #   rank3: 1*0.04=0.04, running stays 0.06
    result = holm_correction([0.01, 0.02, 0.03, 0.04])
    assert result == pytest.approx((0.04, 0.06, 0.06, 0.06))


def test_holm_correction_preserves_input_order_when_unsorted() -> None:
    # Same four p-values as above, permuted; adjusted values must follow
    # their own p-value, not its position.
    result = holm_correction([0.03, 0.01, 0.04, 0.02])
    assert result == pytest.approx((0.06, 0.04, 0.06, 0.06))


def test_holm_correction_empty_is_empty() -> None:
    assert holm_correction([]) == ()


def test_holm_correction_caps_at_one() -> None:
    result = holm_correction([0.9, 0.9])
    assert result == (1.0, 1.0)


def test_holm_correction_rejects_out_of_range_pvalues() -> None:
    with pytest.raises(ValueError):
        holm_correction([1.5])
    with pytest.raises(ValueError):
        holm_correction([-0.1])


# ---------------------------------------------------------------------
# permutation_test_paired
# ---------------------------------------------------------------------


def test_permutation_test_paired_empty_is_p_one() -> None:
    assert permutation_test_paired([]) == 1.0


def test_permutation_test_paired_no_difference_is_p_one() -> None:
    pairs = [(0.5, 0.5), (0.8, 0.8), (0.0, 0.0)]
    assert permutation_test_paired(pairs, samples=200, seed=1) == 1.0


def test_permutation_test_paired_detects_a_consistent_difference() -> None:
    # b always beats a by a full point across every one of 10 instances:
    # only the (rare) all-same-sign-flip resamples are as extreme as the
    # observed mean, so the p-value should be small.
    pairs = [(0.0, 1.0)] * 10
    p = permutation_test_paired(pairs, samples=10_000, seed=20260827)
    assert p < 0.01


def test_permutation_test_paired_is_reproducible_given_the_same_seed() -> None:
    pairs = [(0.2, 0.9), (0.5, 0.4), (0.1, 0.6), (0.7, 0.7)]
    first = permutation_test_paired(pairs, samples=1000, seed=5)
    second = permutation_test_paired(pairs, samples=1000, seed=5)
    assert first == second


# ---------------------------------------------------------------------
# QResult / ConfidenceInterval are plain frozen dataclasses -- sanity
# check they behave like value objects.
# ---------------------------------------------------------------------


def test_confidence_interval_is_frozen_and_comparable() -> None:
    a = ConfidenceInterval(point=0.5, low=0.4, high=0.6)
    b = ConfidenceInterval(point=0.5, low=0.4, high=0.6)
    assert a == b
    with pytest.raises(AttributeError):
        a.point = 0.9  # type: ignore[misc]


def test_qresult_is_frozen_and_comparable() -> None:
    a = QResult(q=1.0, df=2, p_value=0.5)
    b = QResult(q=1.0, df=2, p_value=0.5)
    assert a == b
    with pytest.raises(AttributeError):
        a.q = 2.0  # type: ignore[misc]
