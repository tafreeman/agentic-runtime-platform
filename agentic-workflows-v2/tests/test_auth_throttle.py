"""Unit tests for AuthThrottle — per-IP sliding-window brute-force protection.

Tests use an injectable clock so time can be controlled without real sleeps.
"""

from __future__ import annotations


import pytest

from agentic_v2.server.auth import AuthThrottle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClock:
    """Monotonic clock whose value can be advanced programmatically."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the clock forward by *seconds*."""
        self._now += seconds


def _make_throttle(
    window: float = 10.0,
    threshold: int = 3,
    lockout: float = 30.0,
    clock: FakeClock | None = None,
) -> tuple[AuthThrottle, FakeClock]:
    """Create an AuthThrottle with a fake clock and given thresholds."""
    clk = clock or FakeClock()
    throttle = AuthThrottle(window=window, threshold=threshold, lockout=lockout, clock=clk)
    return throttle, clk


# ---------------------------------------------------------------------------
# is_locked — baseline behaviour
# ---------------------------------------------------------------------------


class TestIsLockedBaseline:
    """is_locked returns (False, 0.0) for a fresh IP."""

    def test_fresh_ip_not_locked(self) -> None:
        throttle, _ = _make_throttle()
        locked, retry = throttle.is_locked("1.2.3.4")
        assert locked is False
        assert retry == 0.0

    def test_unknown_ip_not_locked(self) -> None:
        throttle, _ = _make_throttle()
        locked, _ = throttle.is_locked("0.0.0.0")
        assert locked is False


# ---------------------------------------------------------------------------
# record_failure — sliding window
# ---------------------------------------------------------------------------


class TestRecordFailure:
    """record_failure increments the counter and triggers lockout."""

    def test_below_threshold_not_locked(self) -> None:
        """Fewer failures than threshold do not lock the IP."""
        throttle, _ = _make_throttle(threshold=3)
        ip = "10.0.0.1"
        throttle.record_failure(ip)
        throttle.record_failure(ip)
        locked, _ = throttle.is_locked(ip)
        assert locked is False

    def test_exactly_threshold_triggers_lockout(self) -> None:
        """Hitting exactly the threshold locks the IP."""
        throttle, _ = _make_throttle(threshold=3, lockout=30.0)
        ip = "10.0.0.2"
        for _ in range(3):
            throttle.record_failure(ip)
        locked, retry = throttle.is_locked(ip)
        assert locked is True
        assert retry > 0.0

    def test_fourth_failure_also_sees_lockout(self) -> None:
        """A 4th check after 3 failures still sees the lockout."""
        throttle, _ = _make_throttle(threshold=3)
        ip = "10.0.0.3"
        for _ in range(4):
            throttle.record_failure(ip)
        locked, _ = throttle.is_locked(ip)
        assert locked is True

    def test_failures_outside_window_do_not_count(self) -> None:
        """Failures older than the window are not counted toward the threshold."""
        throttle, clk = _make_throttle(window=10.0, threshold=3)
        ip = "10.0.0.4"
        # Record 2 failures, then advance past the window, then 1 more
        throttle.record_failure(ip)
        throttle.record_failure(ip)
        clk.advance(11.0)  # past the 10s window
        throttle.record_failure(ip)
        # Only 1 failure is in the window — should not be locked
        locked, _ = throttle.is_locked(ip)
        assert locked is False

    def test_retry_after_is_full_lockout_duration(self) -> None:
        """Retry-after on fresh lockout equals the lockout duration."""
        throttle, clk = _make_throttle(threshold=3, lockout=60.0)
        ip = "10.0.0.5"
        for _ in range(3):
            throttle.record_failure(ip)
        locked, retry = throttle.is_locked(ip)
        assert locked is True
        # Allow 1s tolerance for clock arithmetic
        assert 59.0 <= retry <= 60.0


# ---------------------------------------------------------------------------
# Lockout expiry
# ---------------------------------------------------------------------------


class TestLockoutExpiry:
    """Lockout expires correctly after the lockout duration."""

    def test_lockout_expires_after_duration(self) -> None:
        throttle, clk = _make_throttle(threshold=3, lockout=5.0)
        ip = "10.0.1.1"
        for _ in range(3):
            throttle.record_failure(ip)

        # Immediately after lockout
        locked, _ = throttle.is_locked(ip)
        assert locked is True

        # After lockout duration
        clk.advance(5.1)
        locked, retry = throttle.is_locked(ip)
        assert locked is False
        assert retry == 0.0

    def test_after_lockout_expires_new_failures_start_fresh(self) -> None:
        """After expiry, a new failure cycle works correctly."""
        throttle, clk = _make_throttle(threshold=3, lockout=5.0)
        ip = "10.0.1.2"
        for _ in range(3):
            throttle.record_failure(ip)

        clk.advance(6.0)  # expire the lockout

        # New failure cycle — 2 failures should not re-lock
        throttle.record_failure(ip)
        throttle.record_failure(ip)
        locked, _ = throttle.is_locked(ip)
        assert locked is False


# ---------------------------------------------------------------------------
# record_success — clears state
# ---------------------------------------------------------------------------


class TestRecordSuccess:
    """Successful auth clears the failure history."""

    def test_success_clears_failures_below_threshold(self) -> None:
        throttle, _ = _make_throttle(threshold=3)
        ip = "10.0.2.1"
        throttle.record_failure(ip)
        throttle.record_failure(ip)
        throttle.record_success(ip)

        # After success, failures are gone
        locked, _ = throttle.is_locked(ip)
        assert locked is False
        # Should take full threshold new failures to lock again
        throttle.record_failure(ip)
        throttle.record_failure(ip)
        locked, _ = throttle.is_locked(ip)
        assert locked is False

    def test_success_on_unknown_ip_is_noop(self) -> None:
        throttle, _ = _make_throttle()
        throttle.record_success("192.168.0.99")  # must not raise
        locked, _ = throttle.is_locked("192.168.0.99")
        assert locked is False


# ---------------------------------------------------------------------------
# Multiple IPs are tracked independently
# ---------------------------------------------------------------------------


class TestMultipleIPs:
    """Throttle tracks each IP independently."""

    def test_ip_a_lockout_does_not_affect_ip_b(self) -> None:
        throttle, _ = _make_throttle(threshold=3)
        ip_a = "10.0.3.1"
        ip_b = "10.0.3.2"
        for _ in range(3):
            throttle.record_failure(ip_a)

        locked_a, _ = throttle.is_locked(ip_a)
        locked_b, _ = throttle.is_locked(ip_b)
        assert locked_a is True
        assert locked_b is False

    def test_success_for_ip_a_does_not_affect_ip_b(self) -> None:
        throttle, _ = _make_throttle(threshold=3)
        ip_a = "10.0.3.3"
        ip_b = "10.0.3.4"
        for _ in range(2):
            throttle.record_failure(ip_a)
            throttle.record_failure(ip_b)

        throttle.record_success(ip_a)

        # ip_b still has 2 failures
        throttle.record_failure(ip_b)
        locked_b, _ = throttle.is_locked(ip_b)
        assert locked_b is True

        # ip_a was cleared
        throttle.record_failure(ip_a)
        throttle.record_failure(ip_a)
        locked_a, _ = throttle.is_locked(ip_a)
        assert locked_a is False


# ---------------------------------------------------------------------------
# Env-var defaults are applied when no kwargs given
# ---------------------------------------------------------------------------


class TestEnvVarDefaults:
    """AuthThrottle reads env vars when kwargs are not supplied."""

    def test_default_threshold_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTIC_AUTH_LOCKOUT_THRESHOLD", "2")
        throttle = AuthThrottle(window=60.0, lockout=60.0)
        ip = "10.0.4.1"
        throttle.record_failure(ip)
        throttle.record_failure(ip)
        locked, _ = throttle.is_locked(ip)
        assert locked is True

    def test_default_lockout_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS", "10")
        clk = FakeClock()
        throttle = AuthThrottle(window=60.0, threshold=2, clock=clk)
        ip = "10.0.4.2"
        throttle.record_failure(ip)
        throttle.record_failure(ip)
        locked, retry = throttle.is_locked(ip)
        assert locked is True
        assert retry <= 10.0
