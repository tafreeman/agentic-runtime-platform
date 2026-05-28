"""Model statistics tracking with advanced metrics.

Aggressive design improvements:
- Exponential Moving Average (EMA) for latency smoothing
- Percentile tracking (p50, p95, p99) via sorted reservoir
- Sliding window for recent performance
- Circuit breaker state machine
- Time-decayed success rates
"""

import bisect
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class LatencyPercentiles:
    """Percentile statistics for latency."""

    p50: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        return {
            "p50": self.p50,
            "p75": self.p75,
            "p90": self.p90,
            "p95": self.p95,
            "p99": self.p99,
        }


@dataclass
class ModelStats:
    """Comprehensive statistics for a single model.

    Design improvements over original plan:
    - EMA for latency (smoother than simple average)
    - Percentile tracking via reservoir sampling
    - Circuit breaker pattern for automatic failure handling
    - Time-decayed metrics (recent performance weighted higher)
    - Serialization support for persistence
    """

    model_id: str

    # Counters
    success_count: int = 0
    failure_count: int = 0
    rate_limit_count: int = 0
    timeout_count: int = 0

    # Latency tracking (EMA)
    _ema_latency_ms: float = 0.0
    _ema_alpha: float = 0.2  # Smoothing factor

    # Percentile tracking (sorted reservoir)
    _latency_samples: list[float] = field(default_factory=list)
    _max_samples: int = 1000

    # Sliding window for recent performance
    _recent_results: list[tuple[datetime, bool]] = field(default_factory=list)
    _window_size: int = 50

    # Circuit breaker
    circuit_state: CircuitState = CircuitState.CLOSED
    _failure_threshold: int = 5
    _recovery_timeout_seconds: int = 60
    _last_failure_time: datetime | None = None
    _last_failure_mono: float | None = None  # ADR-002C: monotonic clock
    _consecutive_failures: int = 0
    _half_open_success_required: int = 2
    _half_open_successes: int = 0

    # Timestamps (wall clock — for logging/serialization only)
    last_success: datetime | None = None
    last_failure: datetime | None = None
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Cooldown tracking — monotonic clock for runtime, wall clock for persistence
    cooldown_until: datetime | None = None  # Wall clock (serialization only)
    _cooldown_until_mono: float | None = None  # ADR-002C: monotonic clock

    @property
    def total_calls(self) -> int:
        """Total number of API calls."""
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        """Overall success rate (0-1)."""
        if self.total_calls == 0:
            return 1.0  # Assume good until proven otherwise
        return self.success_count / self.total_calls

    @property
    def recent_success_rate(self) -> float:
        """Success rate over recent window (0-1)."""
        if not self._recent_results:
            return 1.0
        successes = sum(1 for _, success in self._recent_results if success)
        return successes / len(self._recent_results)

    @property
    def avg_latency_ms(self) -> float:
        """Exponential moving average latency."""
        return self._ema_latency_ms

    @property
    def percentiles(self) -> LatencyPercentiles:
        """Calculate latency percentiles from samples."""
        if not self._latency_samples:
            return LatencyPercentiles()

        sorted_samples = sorted(self._latency_samples)
        n = len(sorted_samples)

        def get_percentile(p: float) -> float:
            idx = int(p * n)
            return sorted_samples[min(idx, n - 1)]

        return LatencyPercentiles(
            p50=get_percentile(0.50),
            p75=get_percentile(0.75),
            p90=get_percentile(0.90),
            p95=get_percentile(0.95),
            p99=get_percentile(0.99),
        )

    @property
    def is_healthy(self) -> bool:
        """Check if model is considered healthy."""
        if self.circuit_state == CircuitState.OPEN:
            return False
        if self.is_in_cooldown:
            return False
        # Consider unhealthy if recent success rate < 50%
        if len(self._recent_results) >= 5 and self.recent_success_rate < 0.5:
            return False
        return True

    @property
    def is_in_cooldown(self) -> bool:
        """Check if model is in cooldown period.

        Uses monotonic clock (ADR-002C) to avoid NTP clock-jump
        corruption.
        """
        if self._cooldown_until_mono is None:
            return False
        return time.monotonic() < self._cooldown_until_mono

    @property
    def cooldown_remaining_seconds(self) -> float:
        """Seconds remaining in cooldown, or 0 if not in cooldown."""
        if self._cooldown_until_mono is None:
            return 0.0
        remaining = self._cooldown_until_mono - time.monotonic()
        return max(0.0, remaining)

    def record_success(self, latency_ms: float) -> None:
        """Record a successful call.

        Args:
            latency_ms: Call latency in milliseconds
        """
        now_utc = datetime.now(timezone.utc)
        self.success_count += 1
        self.last_success = now_utc

        # Update EMA latency
        if self._ema_latency_ms == 0:
            self._ema_latency_ms = latency_ms
        else:
            self._ema_latency_ms = (
                self._ema_alpha * latency_ms
                + (1 - self._ema_alpha) * self._ema_latency_ms
            )

        # Update latency samples (reservoir)
        if len(self._latency_samples) < self._max_samples:
            bisect.insort(self._latency_samples, latency_ms)
        else:
            # Replace random sample to maintain reservoir
            import random

            idx = random.randint(0, len(self._latency_samples) - 1)
            self._latency_samples[idx] = latency_ms
            self._latency_samples.sort()

        # Update recent window
        self._recent_results.append((now_utc, True))
        if len(self._recent_results) > self._window_size:
            self._recent_results.pop(0)

        # Circuit breaker handling
        self._consecutive_failures = 0
        if self.circuit_state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self._half_open_success_required:
                self.circuit_state = CircuitState.CLOSED
                self._half_open_successes = 0

    def record_failure(self, error_type: str = "unknown") -> None:
        """Record a failed call.

        Args:
            error_type: Type of error encountered
        """
        now_utc = datetime.now(timezone.utc)
        self.failure_count += 1
        self.last_failure = now_utc
        self._last_failure_time = now_utc
        self._last_failure_mono = time.monotonic()  # ADR-002C

        # Update recent window
        self._recent_results.append((now_utc, False))
        if len(self._recent_results) > self._window_size:
            self._recent_results.pop(0)

        # Circuit breaker handling
        self._consecutive_failures += 1
        if self.circuit_state == CircuitState.HALF_OPEN:
            # Failed during recovery test - reopen circuit
            self.circuit_state = CircuitState.OPEN
            self._half_open_successes = 0
        elif self._consecutive_failures >= self._failure_threshold:
            self.circuit_state = CircuitState.OPEN

    def record_rate_limit(self, retry_after_seconds: int | None = None) -> None:
        """Record a rate limit hit.

        Args:
            retry_after_seconds: Provider-specified retry delay from Retry-After
                header. If None, falls back to default 120s cooldown.
        """
        self.rate_limit_count += 1
        self.record_failure("rate_limit")
        # ADR-002C/E: Use provider Retry-After when available, monotonic clock
        cooldown_secs = retry_after_seconds if retry_after_seconds is not None else 120
        self.set_cooldown(cooldown_secs)

    def record_timeout(self) -> None:
        """Record a timeout."""
        self.timeout_count += 1
        self.record_failure("timeout")

    def set_cooldown(self, seconds: int) -> None:
        """Set cooldown period.

        Uses monotonic clock for runtime tracking (ADR-002C) and wall clock
        for serialization/logging only.

        Args:
            seconds: Duration of cooldown in seconds
        """
        self._cooldown_until_mono = time.monotonic() + seconds
        self.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    def clear_cooldown(self) -> None:
        """Clear any active cooldown."""
        self._cooldown_until_mono = None
        self.cooldown_until = None

    def check_circuit(self) -> bool:
        """Check if circuit allows requests.

        Uses monotonic clock for recovery timeout (ADR-002C).

        Returns:
            True if requests should be allowed
        """
        if self.circuit_state == CircuitState.CLOSED:
            return True

        if self.circuit_state == CircuitState.OPEN:
            # Check if recovery timeout has passed using monotonic clock
            if self._last_failure_mono is not None:
                elapsed = time.monotonic() - self._last_failure_mono
                if elapsed >= self._recovery_timeout_seconds:
                    self.circuit_state = CircuitState.HALF_OPEN
                    return True
            elif self._last_failure_time is not None:
                # Fallback for stats loaded from persistence (no mono reference)
                elapsed = (
                    datetime.now(timezone.utc) - self._last_failure_time
                ).total_seconds()
                if elapsed >= self._recovery_timeout_seconds:
                    self.circuit_state = CircuitState.HALF_OPEN
                    return True
            return False

        # HALF_OPEN: allow limited requests
        return True

    def to_dict(self) -> dict:
        """Serialize to dictionary for persistence."""
        return {
            "model_id": self.model_id,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "rate_limit_count": self.rate_limit_count,
            "timeout_count": self.timeout_count,
            "ema_latency_ms": self._ema_latency_ms,
            "circuit_state": self.circuit_state.value,
            "last_success": (
                self.last_success.isoformat() if self.last_success else None
            ),
            "last_failure": (
                self.last_failure.isoformat() if self.last_failure else None
            ),
            "first_seen": self.first_seen.isoformat(),
            "cooldown_until": (
                self.cooldown_until.isoformat() if self.cooldown_until else None
            ),
            "success_rate": self.success_rate,
            "recent_success_rate": self.recent_success_rate,
            "percentiles": self.percentiles.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModelStats":
        """Deserialize from dictionary.

        Recomputes monotonic clock deadlines from persisted wall-clock
        timestamps (ADR-002C). Monotonic values are process-local and
        cannot be persisted directly.
        """
        stats = cls(model_id=data["model_id"])
        stats.success_count = data.get("success_count", 0)
        stats.failure_count = data.get("failure_count", 0)
        stats.rate_limit_count = data.get("rate_limit_count", 0)
        stats.timeout_count = data.get("timeout_count", 0)
        stats._ema_latency_ms = data.get("ema_latency_ms", 0.0)
        stats.circuit_state = CircuitState(data.get("circuit_state", "closed"))

        if data.get("last_success"):
            stats.last_success = datetime.fromisoformat(data["last_success"])
        if data.get("last_failure"):
            stats.last_failure = datetime.fromisoformat(data["last_failure"])
            stats._last_failure_time = stats.last_failure
            # _last_failure_mono left as None — check_circuit falls back to
            # wall clock for stats loaded from persistence
        if data.get("first_seen"):
            stats.first_seen = datetime.fromisoformat(data["first_seen"])
        if data.get("cooldown_until"):
            stats.cooldown_until = datetime.fromisoformat(data["cooldown_until"])
            # Recompute monotonic deadline from remaining wall-clock seconds
            remaining = (
                stats.cooldown_until - datetime.now(timezone.utc)
            ).total_seconds()
            if remaining > 0:
                stats._cooldown_until_mono = time.monotonic() + remaining
            # else: cooldown already expired, leave mono as None

        return stats

    def __repr__(self) -> str:
        """Rich representation."""
        return (
            f"ModelStats({self.model_id}: "
            f"success_rate={self.success_rate:.1%}, "
            f"calls={self.total_calls}, "
            f"latency={self.avg_latency_ms:.0f}ms, "
            f"circuit={self.circuit_state.value})"
        )
