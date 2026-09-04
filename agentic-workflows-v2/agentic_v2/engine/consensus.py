"""Consensus / voting primitives -- ensemble and self-consistency patterns.

Deterministic, LLM-free building blocks for ensembling multiple samples into a
single answer.  These implement two classic patterns:

- **Majority voting** (:func:`majority_vote`) -- canonicalize a set of candidate
  answers into comparable buckets, count them, and return the most-voted bucket
  together with an agreement ratio.  Useful for ensembling several independent
  reviewers/judges, or several samples from the same model.
- **Self-consistency** (:func:`self_consistency`) -- run an async generator ``n``
  times concurrently, discard failures, then majority-vote the survivors.  This
  is the canonical "sample N chain-of-thought completions, take the modal answer"
  technique (Wang et al., 2022).

Design principles:

- **Deterministic where possible** -- canonicalization and tie-breaking are
  fully specified so the same inputs always produce the same winner.
- **Immutable results** -- :class:`ConsensusResult` is a frozen dataclass; inputs
  are never mutated.
- **Below-threshold is data, not an error** -- a low-agreement vote returns a
  result with ``meets_threshold=False`` rather than raising, so callers can gate
  downstream steps on it (e.g. ``when: meets_threshold``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.errors import ConfigurationError

__all__ = [
    "ConsensusResult",
    "canonical_key",
    "coerce_min_agreement",
    "majority_vote",
    "self_consistency",
]


@dataclass(frozen=True)
class ConsensusResult:
    """Immutable outcome of a consensus / voting operation.

    Attributes:
        winner: The raw (first-seen) sample whose canonical bucket won the vote.
        votes: Mapping of canonical-key -> vote count, in first-seen order.
        total_samples: Number of samples that were voted on (post-extraction,
            post-failure-filtering).
        agreement: ``winner_votes / total_samples`` in ``[0.0, 1.0]``; ``0.0``
            when there were no samples.
        tied: ``True`` when two or more canonical buckets share the top count.
        meets_threshold: ``True`` when ``agreement >= min_agreement``.
        failed_samples: Count of generator calls that raised (self-consistency
            only; always ``0`` for :func:`majority_vote`).
        samples: The raw input samples that were voted on, as a tuple.
    """

    winner: Any
    votes: dict[str, int]
    total_samples: int
    agreement: float
    tied: bool
    meets_threshold: bool
    failed_samples: int
    samples: tuple[Any, ...]


def canonical_key(value: Any) -> str:
    """Canonicalize a value into a comparable string bucket key.

    Rules (documented and stable):

    - ``str`` -> ``value.casefold().strip()`` so ``"Yes "`` and ``"yes"`` collide.
    - ``dict`` / ``list`` -> ``json.dumps(..., sort_keys=True)`` so key order and
      whitespace are irrelevant; falls back to ``repr`` if not JSON-serializable.
    - anything else -> ``repr(value)``.

    Args:
        value: The raw sample to canonicalize.

    Returns:
        A stable string key identifying the sample's equivalence bucket.
    """
    if isinstance(value, str):
        return value.casefold().strip()
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, sort_keys=True, default=repr)
        except (TypeError, ValueError):
            return repr(value)
    return repr(value)


def coerce_min_agreement(raw: Any) -> float:
    """Parse and validate a consensus threshold without failing open."""
    if raw is None:
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"consensus 'min_agreement' must be a number in [0.0, 1.0]; got "
            f"{raw!r} (unparseable). Refusing to fail open."
        ) from exc
    if not 0.0 <= value <= 1.0:
        raise ConfigurationError(
            f"consensus 'min_agreement' must be in [0.0, 1.0]; got {value}. "
            "Refusing to fail open."
        )
    return value


def _resolve_key_fn(key: Callable[[Any], str] | None) -> Callable[[Any], str]:
    """Return the canonicalization callable, defaulting to :func:`canonical_key`."""
    return key if key is not None else canonical_key


def _pick_winner(
    votes: dict[str, int],
    first_seen: dict[str, Any],
) -> tuple[Any, int, bool]:
    """Select the winning bucket.

    Tie-break rule: highest count wins; among buckets tied for the highest
    count, the one whose key was *seen first* wins.  ``votes`` and ``first_seen``
    are ordinary insertion-ordered dicts, so iterating them preserves first-seen
    order and makes the choice deterministic.

    Returns:
        ``(winner_sample, winner_votes, tied)``.
    """
    max_count = max(votes.values())
    top_keys = [key for key, count in votes.items() if count == max_count]
    winner_key = top_keys[0]  # first-seen among the tied top buckets
    return first_seen[winner_key], max_count, len(top_keys) > 1


def majority_vote(
    samples: Sequence[Any],
    *,
    key: Callable[[Any], str] | None = None,
    min_agreement: float = 0.0,
    extract: Callable[[Any], Any] | None = None,
) -> ConsensusResult:
    """Majority-vote a sequence of candidate samples into a single winner.

    Each sample is optionally passed through ``extract`` (e.g. to pull the final
    answer out of a chain-of-thought response), then canonicalized via ``key``
    (default :func:`canonical_key`) into a bucket.  The bucket with the most
    votes wins; ties break toward the first-seen bucket.

    Args:
        samples: Candidate answers to vote on.  Not mutated.
        key: Canonicalization function mapping a (possibly extracted) sample to a
            comparable string bucket.  Defaults to :func:`canonical_key`.
        min_agreement: Minimum ``agreement`` for ``meets_threshold`` to be
            ``True``.  Does not raise when unmet.
        extract: Optional transform applied to each sample *before* voting; raw
            samples are still preserved in :attr:`ConsensusResult.samples`.

    Returns:
        A :class:`ConsensusResult`.  An empty ``samples`` yields a zero-agreement
        result with ``winner=None``.
    """
    key_fn = _resolve_key_fn(key)
    raw_samples = tuple(samples)

    votes: dict[str, int] = {}
    first_seen: dict[str, Any] = {}
    for raw in raw_samples:
        candidate = extract(raw) if extract is not None else raw
        bucket = key_fn(candidate)
        votes[bucket] = votes.get(bucket, 0) + 1
        first_seen.setdefault(bucket, raw)

    total = len(raw_samples)
    if total == 0:
        return ConsensusResult(
            winner=None,
            votes={},
            total_samples=0,
            agreement=0.0,
            tied=False,
            meets_threshold=min_agreement <= 0.0,
            failed_samples=0,
            samples=raw_samples,
        )

    winner, winner_votes, tied = _pick_winner(votes, first_seen)
    agreement = winner_votes / total
    return ConsensusResult(
        winner=winner,
        votes=dict(votes),
        total_samples=total,
        agreement=agreement,
        tied=tied,
        meets_threshold=agreement >= min_agreement,
        failed_samples=0,
        samples=raw_samples,
    )


def _partition_results(
    results: list[Any],
) -> tuple[list[Any], int]:
    """Split ``asyncio.gather`` results into successes and a failure count."""
    successes = [r for r in results if not isinstance(r, BaseException)]
    failed = len(results) - len(successes)
    return successes, failed


async def self_consistency(
    generate: Callable[[], Awaitable[Any]],
    n: int,
    *,
    key: Callable[[Any], str] | None = None,
    min_agreement: float = 0.0,
    extract: Callable[[Any], Any] | None = None,
    return_exceptions: bool = True,
) -> ConsensusResult:
    """Run ``generate`` ``n`` times concurrently and majority-vote the survivors.

    Implements the self-consistency pattern: sample ``n`` independent
    completions, drop the ones that raised, then take the modal answer.  The
    surviving samples' ``failed_samples`` count is carried on the result.

    Args:
        generate: A zero-arg async callable producing one sample per invocation.
        n: Number of samples to draw concurrently.  Must be ``>= 1``.
        key: Canonicalization function (see :func:`majority_vote`).
        min_agreement: Minimum agreement for ``meets_threshold``.
        extract: Optional per-sample transform applied before voting.
        return_exceptions: When ``True`` (default), a raising ``generate`` call is
            counted as a failure and excluded; when ``False`` the first exception
            propagates.

    Returns:
        A :class:`ConsensusResult` over the successful samples.

    Raises:
        ValueError: If ``n < 1`` or every sample failed.
    """
    if n < 1:
        raise ValueError(f"self_consistency requires n >= 1, got {n}")

    results = await asyncio.gather(
        *(generate() for _ in range(n)),
        return_exceptions=return_exceptions,
    )
    successes, failed = _partition_results(list(results))

    if not successes:
        raise ValueError(
            f"self_consistency: all {n} samples failed; no consensus possible"
        )

    result = majority_vote(
        successes,
        key=key,
        min_agreement=min_agreement,
        extract=extract,
    )
    return ConsensusResult(
        winner=result.winner,
        votes=result.votes,
        total_samples=result.total_samples,
        agreement=result.agreement,
        tied=result.tied,
        meets_threshold=result.meets_threshold,
        failed_samples=failed,
        samples=result.samples,
    )
