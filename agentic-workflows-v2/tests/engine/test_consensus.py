"""Unit tests for the consensus / voting primitives (LLM-free)."""

from __future__ import annotations

import itertools

import pytest

from agentic_v2.engine.consensus import (
    ConsensusResult,
    canonical_key,
    majority_vote,
    self_consistency,
)


class TestMajorityVote:
    """Deterministic majority-voting behavior."""

    def test_clear_majority_three_two(self):
        """A 3-2 split picks the 3-vote winner with agreement 0.6."""
        result = majority_vote(["a", "a", "a", "b", "b"])

        assert isinstance(result, ConsensusResult)
        assert result.winner == "a"
        assert result.total_samples == 5
        assert result.agreement == pytest.approx(0.6)
        assert result.tied is False
        assert result.votes == {"a": 3, "b": 2}

    def test_unanimous_agreement_is_one(self):
        """Unanimous samples yield agreement 1.0 and no tie."""
        result = majority_vote(["yes", "yes", "yes"])

        assert result.winner == "yes"
        assert result.agreement == pytest.approx(1.0)
        assert result.tied is False

    def test_tie_breaks_to_first_seen_and_flags_tied(self):
        """A tie resolves to the first-seen bucket and sets tied=True."""
        result = majority_vote(["b", "a", "a", "b"])

        assert result.winner == "b"  # 'b' bucket was seen first
        assert result.tied is True
        assert result.agreement == pytest.approx(0.5)

    def test_min_agreement_not_met_flags_threshold_false(self):
        """Below-threshold agreement reports meets_threshold=False, no raise."""
        result = majority_vote(["a", "b", "c"], min_agreement=0.5)

        assert result.agreement == pytest.approx(1 / 3)
        assert result.meets_threshold is False
        assert result.tied is True

    def test_min_agreement_met_flags_threshold_true(self):
        """Agreement at/above threshold reports meets_threshold=True."""
        result = majority_vote(["a", "a", "b"], min_agreement=0.6)

        assert result.agreement == pytest.approx(2 / 3)
        assert result.meets_threshold is True

    def test_string_canonicalization_collapses_case_and_whitespace(self):
        """'Yes ' and 'yes' land in the same bucket."""
        result = majority_vote(["Yes ", "yes", "  YES"])

        assert result.agreement == pytest.approx(1.0)
        assert len(result.votes) == 1

    def test_dict_canonicalization_ignores_key_order(self):
        """Dicts with the same content but different key order collide."""
        result = majority_vote([{"a": 1, "b": 2}, {"b": 2, "a": 1}])

        assert result.agreement == pytest.approx(1.0)
        assert len(result.votes) == 1

    def test_extract_applied_before_voting_raw_preserved(self):
        """Extract pulls the answer out; raw samples are still preserved."""
        samples = [
            {"reasoning": "...", "answer": "ship"},
            {"reasoning": "diff", "answer": "ship"},
            {"reasoning": "x", "answer": "hold"},
        ]
        result = majority_vote(samples, extract=lambda s: s["answer"])

        assert result.winner == samples[0]  # raw sample, not "ship"
        assert result.agreement == pytest.approx(2 / 3)
        assert result.samples == tuple(samples)

    def test_empty_samples_yields_zero_agreement(self):
        """Empty input yields a winner-less zero-agreement result."""
        result = majority_vote([])

        assert result.winner is None
        assert result.total_samples == 0
        assert result.agreement == 0.0
        assert result.tied is False

    def test_custom_key_function(self):
        """A custom key buckets by a derived attribute."""
        result = majority_vote([1, 2, 3, 4], key=lambda n: str(n % 2))

        assert result.agreement == pytest.approx(0.5)
        assert result.votes == {"1": 2, "0": 2}

    def test_result_is_frozen(self):
        """ConsensusResult is immutable."""
        result = majority_vote(["a"])
        with pytest.raises((AttributeError, TypeError)):
            result.winner = "b"  # type: ignore[misc]


class TestCanonicalKey:
    """Canonicalization rules."""

    def test_str_casefold_strip(self):
        assert canonical_key("  Hello ") == "hello"

    def test_list_sorted_keys(self):
        assert canonical_key([2, 1]) == "[2, 1]"

    def test_non_serializable_falls_back_to_repr(self):
        obj = object()
        assert canonical_key(obj) == repr(obj)


class TestSelfConsistency:
    """Async self-consistency sampling."""

    @pytest.mark.asyncio
    async def test_majority_over_stubbed_generator(self):
        """Counts modal answer across n deterministic samples (no sleeps)."""
        answers = itertools.cycle(["approve", "approve", "reject"])

        async def generate() -> str:
            return next(answers)

        result = await self_consistency(generate, n=3)

        assert result.winner == "approve"
        assert result.total_samples == 3
        assert result.failed_samples == 0
        assert result.agreement == pytest.approx(2 / 3)

    @pytest.mark.asyncio
    async def test_failures_counted_vote_over_survivors(self):
        """Raising samples are counted and excluded; survivors are voted."""
        counter = itertools.count()

        async def generate() -> str:
            i = next(counter)
            if i % 2 == 0:
                raise RuntimeError("boom")
            return "ok"

        result = await self_consistency(generate, n=4)

        assert result.winner == "ok"
        assert result.failed_samples == 2
        assert result.total_samples == 2
        assert result.agreement == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_all_failures_raises_value_error(self):
        """When every sample fails, a ValueError is raised."""

        async def generate() -> str:
            raise RuntimeError("always fails")

        with pytest.raises(ValueError, match="all 3 samples failed"):
            await self_consistency(generate, n=3)

    @pytest.mark.asyncio
    async def test_n_one_degenerate(self):
        """N=1 produces a unanimous single-sample result."""

        async def generate() -> str:
            return "solo"

        result = await self_consistency(generate, n=1)

        assert result.winner == "solo"
        assert result.agreement == pytest.approx(1.0)
        assert result.total_samples == 1

    @pytest.mark.asyncio
    async def test_n_less_than_one_raises(self):
        """N < 1 is rejected."""

        async def generate() -> str:
            return "x"

        with pytest.raises(ValueError, match="n >= 1"):
            await self_consistency(generate, n=0)

    @pytest.mark.asyncio
    async def test_return_exceptions_false_propagates(self):
        """With return_exceptions=False the first error propagates."""

        async def generate() -> str:
            raise KeyError("propagate me")

        with pytest.raises(KeyError):
            await self_consistency(generate, n=2, return_exceptions=False)
