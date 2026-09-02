"""Pure statistics for the SWE-AB ledger: no SQL, no I/O.

Every function here operates on plain Python values (ints, floats,
sequences) so it is unit-testable without a database and reusable by
`queries.py` without either module importing the other's concerns.

`wilson`, `mcnemar_exact` and `paired_bootstrap` are ports of the
known-good implementations in `evals/swe_ab/analyze.py`; their reasoning
is preserved in the docstrings below, not just their arithmetic.

Standard library only.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

__all__ = [
    "Z_95",
    "DEFAULT_CI_LEVEL",
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_PERMUTATION_SAMPLES",
    "DEFAULT_SEED",
    "ConfidenceInterval",
    "QResult",
    "wilson",
    "mcnemar_exact",
    "paired_bootstrap",
    "cochrans_q",
    "chi2_sf",
    "holm_correction",
    "permutation_test_paired",
]

#: z-score for a two-sided 95% normal interval, hand-pinned to 15
#: significant figures so this module never needs scipy/numpy.
Z_95: Final[float] = 1.959963984540054

#: Confidence level `Z_95` corresponds to; carried on `ConfidenceInterval`
#: so a caller never has to assume which level produced an interval.
DEFAULT_CI_LEVEL: Final[float] = 0.95

#: Bootstrap resample count for `paired_bootstrap`. 10k resamples puts the
#: Monte Carlo error on a 95% interval well under one part in a thousand.
DEFAULT_BOOTSTRAP_SAMPLES: Final[int] = 10_000

#: Sign-flip resample count for `permutation_test_paired`.
DEFAULT_PERMUTATION_SAMPLES: Final[int] = 10_000

#: Shared default seed for every randomized test in this module, so a
#: verdict computed twice from the same ledger rows is byte-identical.
#: Carried over from `analyze.py::paired_bootstrap`'s default.
DEFAULT_SEED: Final[int] = 20260827


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    """A point estimate with a two-sided interval around it.

    For `wilson`, `low`/`high` are the Wilson score bounds at `level`.
    For `paired_bootstrap`, they are the empirical 2.5th/97.5th percentile
    of the bootstrap distribution -- an approximate `level`-confidence
    interval, not an exact one, as is standard for the percentile
    bootstrap.
    """

    point: float
    low: float
    high: float
    level: float = DEFAULT_CI_LEVEL


@dataclass(frozen=True, slots=True)
class QResult:
    """Cochran's Q omnibus statistic with its chi-square reference."""

    q: float
    df: int
    p_value: float


def wilson(successes: int, total: int) -> ConfidenceInterval:
    """95% Wilson score interval for a binomial proportion.

    The Wilson interval is preferred over the naive normal (Wald)
    interval because it stays inside [0, 1] and remains well-behaved at
    small `n` and at proportions near 0 or 1, where the Wald interval is
    known to undercover badly. Ported verbatim from `analyze.py::wilson`.

    Returns a degenerate `ConfidenceInterval(0.0, 0.0, 0.0)` when
    `total == 0` -- there is no data to estimate a rate from, and 0.0 is
    the least presumptive answer available (not, e.g., 0.5).

    Raises `ValueError` if `total < 0`, `successes < 0`, or
    `successes > total`.
    """
    if total < 0 or successes < 0 or successes > total:
        raise ValueError(
            f"invalid successes/total: successes={successes}, total={total}"
        )
    if total == 0:
        return ConfidenceInterval(point=0.0, low=0.0, high=0.0)
    z = Z_95
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total))
        / denominator
    )
    low = max(0.0, centre - margin)
    high = min(1.0, centre + margin)
    return ConfidenceInterval(point=phat, low=low, high=high)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on the discordant pairs.

    `b` = cases only arm A solved, `c` = cases only arm B solved.
    Concordant pairs (both-pass, both-fail) carry no information about
    which arm is better, so callers pass in only the discordant counts --
    that exclusion is the whole point of a paired test. Ported verbatim
    from `analyze.py::mcnemar_exact`.

    Raises `ValueError` if `b < 0` or `c < 0`.
    """
    if b < 0 or c < 0:
        raise ValueError(f"discordant counts must be non-negative: b={b}, c={c}")
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail: float = sum(math.comb(n, i) for i in range(0, k + 1)) / (2**n)
    return min(1.0, 2 * tail)


def paired_bootstrap(
    deltas: Sequence[float],
    *,
    samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed: int = DEFAULT_SEED,
) -> ConfidenceInterval:
    """Percentile bootstrap interval on the mean of paired deltas.

    Resamples `deltas` with replacement `samples` times, takes the mean
    of each resample, and reports the 2.5th/97.5th percentile of that
    distribution as `low`/`high`. Ported from
    `analyze.py::paired_bootstrap`, generalized from `list[int]` to
    `Sequence[float]` since callers here may pass real-valued deltas
    (e.g. proportion differences from `repeat_aggregate`), not just the
    {-1, 0, 1} of a binary paired comparison.

    Returns a degenerate `ConfidenceInterval(0.0, 0.0, 0.0)` for an empty
    input -- there is no delta to resample.
    """
    if not deltas:
        return ConfidenceInterval(point=0.0, low=0.0, high=0.0)
    rng = random.Random(seed)
    size = len(deltas)
    point = statistics.fmean(deltas)
    means = [
        statistics.fmean(deltas[rng.randrange(size)] for _ in range(size))
        for _ in range(samples)
    ]
    means.sort()
    low_idx = int(0.025 * samples)
    high_idx = int(0.975 * samples)
    return ConfidenceInterval(point=point, low=means[low_idx], high=means[high_idx])


# ---------------------------------------------------------------------
# Regularized incomplete gamma function (Numerical Recipes gser/gcf),
# used only to evaluate the chi-square upper tail without a scipy
# dependency. See `chi2_sf` for the identity and the accuracy note.
# ---------------------------------------------------------------------

_GAMMA_MAX_ITER: Final[int] = 500
#: One order of magnitude above double precision's ~2.22e-16 epsilon --
#: tight enough that both series below converge to the last representable
#: bit long before `_GAMMA_MAX_ITER` is reached for any (a, x) this module
#: calls them with.
_GAMMA_EPS: Final[float] = 3e-16
_GAMMA_FPMIN: Final[float] = 1e-300


def _lower_incomplete_gamma_series(a: float, x: float) -> float:
    """Regularized lower incomplete gamma `P(a, x)` via its power series.

    Converges quickly for `x < a + 1`; `chi2_sf` is the only caller and
    picks between this and `_upper_incomplete_gamma_cf` based on that
    threshold, per Numerical Recipes' `gser`/`gcf` split.
    """
    if x <= 0.0:
        return 0.0
    gln = math.lgamma(a)
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(_GAMMA_MAX_ITER):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * _GAMMA_EPS:
            break
    return total * math.exp(-x + a * math.log(x) - gln)


def _upper_incomplete_gamma_cf(a: float, x: float) -> float:
    """Regularized upper incomplete gamma `Q(a, x)` via a continued
    fraction (Lentz's method). Converges quickly for `x >= a + 1`; see
    `chi2_sf`.
    """
    gln = math.lgamma(a)
    b = x + 1.0 - a
    c = 1.0 / _GAMMA_FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, _GAMMA_MAX_ITER + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _GAMMA_FPMIN:
            d = _GAMMA_FPMIN
        c = b + an / c
        if abs(c) < _GAMMA_FPMIN:
            c = _GAMMA_FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _GAMMA_EPS:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi2_sf(x: float, df: int) -> float:
    """Upper-tail (survival) probability of the chi-square distribution.

    `P(X > x)` for `X ~ chi2(df)`, computed via the standard identity
    `chi2_sf(x, df) == Q(df / 2, x / 2)`, the regularized *upper*
    incomplete gamma function. The stdlib has no chi-square or
    incomplete-gamma function (`math.gamma`/`math.lgamma` give only the
    *complete* gamma function), so this implements the regularized
    incomplete gamma itself via the Numerical Recipes `gser` (power
    series, for `x < a + 1`) / `gcf` (continued fraction via Lentz's
    method, for `x >= a + 1`) split -- the standard method for evaluating
    it to near machine precision without a special-functions library.

    Accuracy: both the series and the continued fraction iterate to a
    relative tolerance of `_GAMMA_EPS` (3e-16, about one order of
    magnitude above double precision's ~2.22e-16 epsilon) or
    `_GAMMA_MAX_ITER` (500) terms, whichever comes first -- for every
    (df, x) this module is exercised with, convergence happens in well
    under 100 terms. `tests/test_stats.py` cross-checks the result
    against three published chi-square critical values (the 0.05-level
    critical values for df=1, 2, 3) and against the df=1 identity
    `chi2_sf(x, 1) == 2 * (1 - Phi(sqrt(x)))` (chi-square with one degree
    of freedom is a squared standard normal), both to within 1e-9 --
    several orders tighter than any published table this would be
    compared against.

    Raises `ValueError` if `df < 1` or `x < 0`.
    """
    if df < 1:
        raise ValueError(f"df must be >= 1, got {df}")
    if x < 0:
        raise ValueError(f"x must be >= 0, got {x}")
    if x == 0.0:
        return 1.0
    a = df / 2.0
    half_x = x / 2.0
    if half_x < a + 1.0:
        return 1.0 - _lower_incomplete_gamma_series(a, half_x)
    return _upper_incomplete_gamma_cf(a, half_x)


def cochrans_q(table: Sequence[Sequence[int]]) -> QResult:
    """Cochran's Q omnibus test across k >= 2 arms on the same instances.

    `table[i][j]` is the 0/1 outcome of instance `i` under arm `j` -- one
    row per instance, one column per arm, built by a caller (typically
    `queries.omnibus`) after restricting to instances every arm has a
    verdict for. Under the null that every arm has the same success
    probability, `Q ~ chi2(k - 1)`.

    Uses the standard computational form

        Q = (k-1) * (k * sum(T_j**2) - sum(T_j)**2)
            / (k * sum(L_i) - sum(L_i**2))

    where `T_j` is column j's total and `L_i` is row i's total -- exactly
    the textbook form `k(k-1) * sum((T_j - T_bar)**2) / sum(L_i*(k-L_i))`
    after expanding the sums of squares, but touching each cell once.
    When every row is constant (every instance is all-pass or all-fail
    across arms, i.e. no row varies) the denominator is 0 and there is no
    discriminating information between arms; this returns
    `Q=0.0, p_value=1.0` rather than dividing by zero.

    Raises `ValueError` if `table` is empty, has fewer than 2 columns,
    has ragged rows, or contains a cell that is not 0 or 1.
    """
    if not table:
        raise ValueError("cochrans_q requires at least one instance (row)")
    k = len(table[0])
    if k < 2:
        raise ValueError(f"cochrans_q requires k >= 2 arms (columns), got {k}")
    for row in table:
        if len(row) != k:
            raise ValueError("every row of `table` must have the same length")
        for cell in row:
            if cell not in (0, 1):
                raise ValueError(f"table cells must be 0 or 1, got {cell!r}")

    column_totals = [sum(row[j] for row in table) for j in range(k)]
    row_totals = [sum(row) for row in table]
    sum_t = sum(column_totals)
    sum_t_sq = sum(t * t for t in column_totals)
    sum_l = sum(row_totals)
    sum_l_sq = sum(l_ * l_ for l_ in row_totals)

    df = k - 1
    denominator = k * sum_l - sum_l_sq
    if denominator == 0:
        return QResult(q=0.0, df=df, p_value=1.0)

    q = (k - 1) * (k * sum_t_sq - sum_t * sum_t) / denominator
    p_value = chi2_sf(q, df)
    return QResult(q=q, df=df, p_value=p_value)


def holm_correction(pvalues: Sequence[float]) -> tuple[float, ...]:
    """Holm-Bonferroni step-down adjustment, returned in input order.

    Sorts p-values ascending, multiplies the i-th smallest (0-indexed,
    rank `i`) by `(m - i)`, enforces monotonicity by carrying the running
    maximum forward as rank increases, and caps every adjusted value at
    1.0. This controls the family-wise error rate at least as tightly as
    the single-step Bonferroni correction (`m * p`) while being uniformly
    more powerful, since only the smallest p-value is multiplied by the
    full `m`.

    Returns `()` for an empty input.

    Raises `ValueError` if any p-value is outside `[0, 1]`.
    """
    m = len(pvalues)
    if m == 0:
        return ()
    for p in pvalues:
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"p-values must be in [0, 1], got {p}")

    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running_max = 0.0
    for rank, idx in enumerate(order):
        factor = m - rank
        value = min(1.0, factor * pvalues[idx])
        running_max = max(running_max, value)
        adjusted[idx] = running_max
    return tuple(adjusted)


def permutation_test_paired(
    pairs: Sequence[tuple[float, float]],
    *,
    samples: int = DEFAULT_PERMUTATION_SAMPLES,
    seed: int = DEFAULT_SEED,
) -> float:
    """Two-sided sign-flip permutation p-value on paired proportions.

    `pairs` is `(arm_a_proportion, arm_b_proportion)` per matched
    instance -- e.g. `queries.repeat_aggregate`'s per-task success
    proportions for two arms, for the non-deterministic-arm case where
    "outcome" is itself a rate across repeated runs rather than a single
    pass/fail bit, so `mcnemar_exact` does not apply.

    Under the null that the two arms are exchangeable, the sign of each
    paired difference `b - a` is equally likely to be positive or
    negative. This resamples that null `samples` times by flipping each
    difference's sign independently with probability 0.5, and reports
    the two-sided p-value as the fraction of resamples whose `|mean|` is
    at least as extreme as the one observed. Uses the `(count + 1) /
    (samples + 1)` form (rather than `count / samples`) so the p-value is
    never reported as exactly 0 -- a finite permutation test can only
    ever show "no resample was this extreme," never "the true p-value is
    zero."

    Returns 1.0 for an empty `pairs` (no evidence either way).
    """
    if not pairs:
        return 1.0
    deltas = [b - a for a, b in pairs]
    observed = abs(statistics.fmean(deltas))
    rng = random.Random(seed)
    at_least_as_extreme = 0
    for _ in range(samples):
        flipped_mean = statistics.fmean(d if rng.random() < 0.5 else -d for d in deltas)
        if abs(flipped_mean) >= observed - 1e-12:
            at_least_as_extreme += 1
    return (at_least_as_extreme + 1) / (samples + 1)
