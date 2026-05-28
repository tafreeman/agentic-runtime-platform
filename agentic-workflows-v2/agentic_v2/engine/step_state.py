"""Step lifecycle state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StepState(str, Enum):
    """Lifecycle states for a workflow step."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS: dict[StepState, set[StepState]] = {
    StepState.PENDING: {StepState.READY, StepState.SKIPPED},
    StepState.READY: {StepState.RUNNING, StepState.CANCELLED},
    StepState.RUNNING: {
        StepState.SUCCESS,
        StepState.FAILED,
        StepState.RETRYING,
        StepState.SKIPPED,
        StepState.CANCELLED,
    },
    StepState.RETRYING: {StepState.RUNNING, StepState.FAILED, StepState.CANCELLED},
    StepState.SUCCESS: set(),
    StepState.FAILED: set(),
    StepState.SKIPPED: set(),
    StepState.CANCELLED: set(),
}


@dataclass
class StepStateManager:
    """Track and validate step state transitions.

    This manager enforces the valid lifecycle of a workflow step,
    preventing invalid transitions (e.g., from SUCCESS back to RUNNING).
    """

    _states: dict[str, StepState] = field(default_factory=dict)

    def get_state(self, step_name: str) -> StepState:
        """Get current state for a specific step.

        Returns StepState.PENDING if the step has not been recorded yet.
        """
        return self._states.get(step_name, StepState.PENDING)

    def set_state(self, step_name: str, new_state: StepState) -> StepState:
        """Set state without validation.

        WARNING: This bypasses the state machine logic. Use transition() instead
        unless you are force-setting a state (e.g., during initialization).
        """
        self._states[step_name] = new_state
        return new_state

    def transition(self, step_name: str, new_state: StepState) -> StepState:
        """Transition a step to a new state and validate.

        Args:
            step_name: The name of the step to update.
            new_state: The target State.

        Raises:
            ValueError: If the transition is not allowed by the _ALLOWED_TRANSITIONS map.
        """
        current = self.get_state(step_name)
        if not self.can_transition(current, new_state):
            raise ValueError(
                f"Invalid transition {current.value} -> {new_state.value} for {step_name}"
            )
        self._states[step_name] = new_state
        return new_state

    def can_transition(self, current: StepState, new_state: StepState) -> bool:
        """Check whether a transition from current to new_state is allowed."""
        return new_state in _ALLOWED_TRANSITIONS.get(current, set())

    def reset(self, step_name: str) -> None:
        """Reset a step to PENDING by removing it from tracked states."""
        self._states.pop(step_name, None)
