"""Tests for StepState lifecycle state machine.

Covers:
- State transitions
- Valid/invalid transition validation
- State manager operations
"""

import pytest
from agentic_v2.engine.step_state import StepState, StepStateManager


class TestStepState:
    """Tests for the StepState enum."""

    @pytest.mark.parametrize(
        "member,value",
        [
            (StepState.PENDING, "pending"),
            (StepState.READY, "ready"),
            (StepState.RUNNING, "running"),
            (StepState.RETRYING, "retrying"),
            (StepState.SUCCESS, "success"),
            (StepState.FAILED, "failed"),
            (StepState.SKIPPED, "skipped"),
            (StepState.CANCELLED, "cancelled"),
        ],
    )
    def test_state_values(self, member, value):
        """All expected states exist with correct string values (str enum)."""
        assert member.value == value
        # StepState inherits from str for JSON serialization
        assert isinstance(member, str)
        assert member == value


class TestStepStateManager:
    """Tests for the StepStateManager."""

    def test_get_state_default_pending(self):
        """Unknown steps default to PENDING state."""
        manager = StepStateManager()
        assert manager.get_state("unknown_step") == StepState.PENDING

    def test_set_state_bypasses_validation(self):
        """set_state bypasses transition validation."""
        manager = StepStateManager()
        # This would be invalid via transition(), but set_state allows it
        manager.set_state("step1", StepState.SUCCESS)
        assert manager.get_state("step1") == StepState.SUCCESS

    @pytest.mark.parametrize(
        "transitions,expected_final",
        [
            ([StepState.READY], StepState.READY),
            ([StepState.READY, StepState.RUNNING], StepState.RUNNING),
            (
                [StepState.READY, StepState.RUNNING, StepState.SUCCESS],
                StepState.SUCCESS,
            ),
            ([StepState.READY, StepState.RUNNING, StepState.FAILED], StepState.FAILED),
            (
                [StepState.READY, StepState.RUNNING, StepState.RETRYING],
                StepState.RETRYING,
            ),
            (
                [
                    StepState.READY,
                    StepState.RUNNING,
                    StepState.RETRYING,
                    StepState.RUNNING,
                ],
                StepState.RUNNING,
            ),
            ([StepState.SKIPPED], StepState.SKIPPED),
        ],
        ids=[
            "pending_to_ready",
            "ready_to_running",
            "running_to_success",
            "running_to_failed",
            "running_to_retrying",
            "retrying_to_running",
            "pending_to_skipped",
        ],
    )
    def test_valid_transitions(self, transitions, expected_final):
        """Valid state transitions reach the expected final state."""
        manager = StepStateManager()
        for target in transitions:
            result = manager.transition("step1", target)
        assert result == expected_final
        assert manager.get_state("step1") == expected_final

    def test_invalid_transition_pending_to_success(self):
        """PENDING → SUCCESS is invalid (must go through RUNNING)."""
        manager = StepStateManager()
        with pytest.raises(ValueError, match="Invalid transition"):
            manager.transition("step1", StepState.SUCCESS)

    def test_invalid_transition_success_to_anything(self):
        """SUCCESS is terminal - no transitions allowed."""
        manager = StepStateManager()
        manager.set_state("step1", StepState.SUCCESS)
        with pytest.raises(ValueError, match="Invalid transition"):
            manager.transition("step1", StepState.RUNNING)

    def test_invalid_transition_failed_to_anything(self):
        """FAILED is terminal - no transitions allowed."""
        manager = StepStateManager()
        manager.set_state("step1", StepState.FAILED)
        with pytest.raises(ValueError, match="Invalid transition"):
            manager.transition("step1", StepState.RUNNING)

    def test_can_transition_true(self):
        """can_transition returns True for valid transitions."""
        manager = StepStateManager()
        assert manager.can_transition(StepState.PENDING, StepState.READY) is True
        assert manager.can_transition(StepState.READY, StepState.RUNNING) is True
        assert manager.can_transition(StepState.RUNNING, StepState.SUCCESS) is True

    def test_can_transition_false(self):
        """can_transition returns False for invalid transitions."""
        manager = StepStateManager()
        assert manager.can_transition(StepState.PENDING, StepState.SUCCESS) is False
        assert manager.can_transition(StepState.SUCCESS, StepState.RUNNING) is False
        assert manager.can_transition(StepState.FAILED, StepState.SUCCESS) is False

    def test_reset_clears_state(self):
        """Reset returns step to PENDING."""
        manager = StepStateManager()
        manager.set_state("step1", StepState.SUCCESS)
        manager.reset("step1")
        assert manager.get_state("step1") == StepState.PENDING

    def test_reset_nonexistent_step_no_error(self):
        """Reset on nonexistent step doesn't raise."""
        manager = StepStateManager()
        manager.reset("never_existed")  # Should not raise
        assert manager.get_state("never_existed") == StepState.PENDING

    def test_multiple_steps_independent(self):
        """Different steps have independent state."""
        manager = StepStateManager()
        manager.transition("step1", StepState.READY)
        manager.transition("step2", StepState.SKIPPED)

        assert manager.get_state("step1") == StepState.READY
        assert manager.get_state("step2") == StepState.SKIPPED
        assert manager.get_state("step3") == StepState.PENDING
