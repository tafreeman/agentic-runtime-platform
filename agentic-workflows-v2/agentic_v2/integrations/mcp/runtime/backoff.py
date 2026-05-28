"""Exponential backoff with jitter for reconnection attempts.

Implements the backoff strategy used when MCP connections fail.
"""

import random
from typing import Optional


class ExponentialBackoff:
    """Implements exponential backoff with jitter.

    Sequence: 1s → 2s → 4s → 8s → 16s → 30s (max)
    Jitter: ±20% randomization to prevent thundering herd
    """

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        multiplier: float = 2.0,
        jitter: float = 0.2,
        max_attempts: Optional[int] = 5,
    ) -> None:
        """Initialize backoff strategy.

        Args:
            initial_delay: Starting delay in seconds
            max_delay: Maximum delay in seconds
            multiplier: Exponential growth factor
            jitter: Jitter factor (0.2 = ±20%)
            max_attempts: Max retry attempts (None = infinite)
        """
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
        self.max_attempts = max_attempts

        self._current_attempt = 0
        self._current_delay = initial_delay

    def next_delay(self) -> Optional[float]:
        """Calculate next delay value.

        Returns:
            Delay in seconds, or None if max attempts exceeded
        """
        if self.max_attempts and self._current_attempt >= self.max_attempts:
            return None

        # Calculate base delay with exponential growth
        delay = min(self._current_delay, self.max_delay)

        # Add jitter (±20%)
        jitter_amount = delay * self.jitter
        jittered_delay = delay + random.uniform(-jitter_amount, jitter_amount)

        # Ensure non-negative
        jittered_delay = max(0.1, jittered_delay)

        # Increment for next call
        self._current_attempt += 1
        self._current_delay *= self.multiplier

        return jittered_delay

    def reset(self) -> None:
        """Reset backoff to initial state."""
        self._current_attempt = 0
        self._current_delay = self.initial_delay

    @property
    def attempt_count(self) -> int:
        """Current attempt number."""
        return self._current_attempt

    @property
    def is_exhausted(self) -> bool:
        """Check if all retry attempts have been used."""
        if self.max_attempts is None:
            return False
        return self._current_attempt >= self.max_attempts
