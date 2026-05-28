"""Tests for scoring profile definitions and the get_profile helper."""

from __future__ import annotations

import pytest
from agentic_v2.server.scoring_profiles import (
    DEFAULT_PROFILE_ID,
    SCORING_PROFILES,
    ScoringProfile,
    get_profile,
)


class TestScoringProfileImmutability:
    """Verify that ScoringProfile is truly immutable after construction."""

    def test_weights_is_not_a_plain_dict(self) -> None:
        profile = SCORING_PROFILES["A"]
        with pytest.raises(TypeError):
            profile.weights["objective_tests"] = 9.9  # type: ignore[index]

    def test_extra_gates_is_tuple(self) -> None:
        profile = SCORING_PROFILES["A"]
        assert isinstance(profile.extra_gates, tuple)

    def test_frozen_attribute_reassignment_raises(self) -> None:
        profile = SCORING_PROFILES["B"]
        with pytest.raises(AttributeError):
            profile.profile_id = "X"  # type: ignore[misc]


class TestAllProfilesValid:
    """Smoke-test every registered profile."""

    @pytest.mark.parametrize("pid", list(SCORING_PROFILES))
    def test_weight_sum_is_one(self, pid: str) -> None:
        profile = SCORING_PROFILES[pid]
        assert sum(profile.weights.values()) == pytest.approx(
            1.0, abs=1e-9
        ), f"Profile {pid!r} weights do not sum to 1.0"

    @pytest.mark.parametrize("pid", list(SCORING_PROFILES))
    def test_profile_id_matches_key(self, pid: str) -> None:
        assert SCORING_PROFILES[pid].profile_id == pid

    @pytest.mark.parametrize("pid", list(SCORING_PROFILES))
    def test_description_is_non_empty(self, pid: str) -> None:
        assert SCORING_PROFILES[pid].description.strip()

    @pytest.mark.parametrize("pid", list(SCORING_PROFILES))
    def test_weights_all_positive(self, pid: str) -> None:
        for dim, w in SCORING_PROFILES[pid].weights.items():
            assert w > 0, f"Profile {pid!r} weight for {dim!r} is not positive"


class TestProfileE:
    """Detailed tests for the ADR-007 deep-research profile."""

    profile = SCORING_PROFILES["E"]

    def test_profile_id(self) -> None:
        assert self.profile.profile_id == "E"

    def test_weight_sum(self) -> None:
        assert sum(self.profile.weights.values()) == pytest.approx(1.0)

    def test_coverage_weight(self) -> None:
        assert self.profile.weights["coverage"] == pytest.approx(0.25)

    def test_verification_weight(self) -> None:
        assert self.profile.weights["verification"] == pytest.approx(0.20)

    def test_recency_weight(self) -> None:
        assert self.profile.weights["recency"] == pytest.approx(0.15)

    def test_extra_gates_contains_all_dimensions_high(self) -> None:
        assert "all_dimensions_high" in self.profile.extra_gates

    def test_extra_gates_contains_no_critical_contradictions(self) -> None:
        assert "no_critical_contradictions" in self.profile.extra_gates

    def test_extra_gates_contains_sources_floor(self) -> None:
        assert "sources_floor" in self.profile.extra_gates

    def test_extra_gates_is_tuple(self) -> None:
        assert isinstance(self.profile.extra_gates, tuple)

    def test_weights_immutable(self) -> None:
        with pytest.raises(TypeError):
            self.profile.weights["coverage"] = 0.99  # type: ignore[index]


class TestGetProfile:
    def test_returns_default_for_none(self) -> None:
        assert get_profile(None).profile_id == DEFAULT_PROFILE_ID

    def test_returns_default_for_empty_string(self) -> None:
        assert get_profile("").profile_id == DEFAULT_PROFILE_ID

    def test_returns_default_for_unknown_id(self) -> None:
        assert get_profile("ZZZZ").profile_id == DEFAULT_PROFILE_ID

    def test_returns_correct_profile_for_a(self) -> None:
        assert get_profile("A").profile_id == "A"

    def test_returns_correct_profile_for_e(self) -> None:
        assert get_profile("E").profile_id == "E"

    def test_returns_scoring_profile_instance(self) -> None:
        assert isinstance(get_profile("B"), ScoringProfile)
