"""Rate-limit tracking with provider-aware header parsing (ADR-002E).

Implements dual token-bucket tracking (RPM + TPM) per provider and parses
provider-specific rate-limit headers to set precise cooldown durations
instead of the flat 120s default.

Key design decisions:
- Provider-specific header parsing (OpenAI, Anthropic, Azure, Gemini)
- Fallback to exponential backoff with jitter when headers are unreliable
- Dual buckets (requests + tokens) per provider
- Thread-safe via monotonic clock (ADR-002C)
"""

import math
import random
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


@dataclass
class TokenBucket:
    """Token bucket for rate limiting.

    Tracks available capacity using the token bucket algorithm. Tokens
    are consumed on each request and refilled at a steady rate. Uses
    monotonic clock for timing (ADR-002C).
    """

    capacity: int
    refill_rate: float  # tokens per second
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens.

        Returns True if successful.
        """
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def remaining(self) -> float:
        """Return current available tokens."""
        self._refill()
        return self._tokens

    def time_until_available(self, tokens: int = 1) -> float:
        """Seconds until `tokens` become available.

        0 if already available.
        """
        self._refill()
        if self._tokens >= tokens:
            return 0.0
        deficit = tokens - self._tokens
        return deficit / self.refill_rate if self.refill_rate > 0 else float("inf")

    def reset(self, remaining: int, reset_seconds: float) -> None:
        """Reset bucket state from provider headers.

        Args:
            remaining: Remaining capacity reported by provider
            reset_seconds: Seconds until full capacity resets
        """
        self._tokens = float(min(remaining, self.capacity))
        if reset_seconds > 0 and remaining < self.capacity:
            self.refill_rate = (self.capacity - remaining) / reset_seconds
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        """Refill bucket based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now


@dataclass
class ProviderRateLimits:
    """Rate-limit state for a single provider."""

    provider: str
    rpm_bucket: TokenBucket  # Requests per minute
    tpm_bucket: TokenBucket | None = None  # Tokens per minute (if tracked)
    last_retry_after: float | None = None  # Last Retry-After value seen
    total_requests: int = 0  # Total requests for throttle computation
    recent_errors: int = 0  # Recent errors for throttle computation


# Default rate limits per provider (conservative estimates)
_DEFAULT_LIMITS: dict[str, dict[str, int]] = {
    "openai": {"rpm": 60, "tpm": 90_000},
    "anthropic": {"rpm": 60, "tpm": 80_000},
    "gemini": {"rpm": 60, "tpm": 100_000},
    "gh": {"rpm": 15, "tpm": 150_000},  # GitHub Models
    "azure": {"rpm": 60, "tpm": 120_000},
    "ollama": {"rpm": 1000, "tpm": 1_000_000},  # Local, effectively unlimited
}


@dataclass
class RateLimitTracker:
    """Track rate limits per provider using dual token buckets (ADR-002E).

    Parses provider-specific rate-limit headers to maintain accurate
    capacity tracking. Falls back to conservative defaults when headers
    are absent or unreliable.
    """

    _providers: dict[str, ProviderRateLimits] = field(default_factory=dict)

    def get_provider(self, model: str) -> ProviderRateLimits:
        """Get or create rate-limit state for a model's provider."""
        provider = _extract_provider(model)
        if provider not in self._providers:
            limits = _DEFAULT_LIMITS.get(provider, {"rpm": 30, "tpm": 50_000})
            self._providers[provider] = ProviderRateLimits(
                provider=provider,
                rpm_bucket=TokenBucket(
                    capacity=limits["rpm"],
                    refill_rate=limits["rpm"] / 60.0,
                ),
                tpm_bucket=TokenBucket(
                    capacity=limits["tpm"],
                    refill_rate=limits["tpm"] / 60.0,
                ),
            )
        return self._providers[provider]

    def can_request(self, model: str, estimated_tokens: int = 1000) -> bool:
        """Check if a request is allowed under current rate limits."""
        state = self.get_provider(model)
        if not state.rpm_bucket.consume():
            return False
        if state.tpm_bucket and not state.tpm_bucket.consume(estimated_tokens):
            return False
        return True

    def parse_retry_after(self, headers: dict[str, str]) -> int | None:
        """Parse Retry-After header (RFC 7231 Section 7.1.3).

        Supports both delta-seconds and HTTP-date formats.

        Args:
            headers: Response headers (case-insensitive keys)

        Returns:
            Retry-after seconds, or None if header absent/unparseable
        """
        # Normalize header keys to lowercase
        lower_headers = {str(k).lower(): str(v) for k, v in headers.items()}
        retry_after = lower_headers.get("retry-after")
        if retry_after:
            try:
                seconds = int(retry_after)
                cooldown = _cooldown_seconds(seconds)
                if cooldown is not None:
                    return cooldown
            except ValueError:
                pass

            # Try HTTP-date format (RFC 7231 Section 7.1.3)
            try:
                dt = parsedate_to_datetime(retry_after)
                delta = (dt - datetime.now(UTC)).total_seconds()
                cooldown = _cooldown_seconds(delta)
                if cooldown is not None:
                    return cooldown
            except (ValueError, TypeError):
                pass

        retry_after_ms = _first_header(
            lower_headers,
            ("retry-after-ms", "x-ms-retry-after-ms"),
        )
        if retry_after_ms is not None:
            cooldown = _cooldown_seconds(_parse_milliseconds(retry_after_ms))
            if cooldown is not None:
                return cooldown

        return None

    def update_from_headers(self, model: str, headers: dict[str, str]) -> int | None:
        """Parse provider-specific rate-limit headers and update buckets.

        Returns the recommended cooldown seconds if rate-limited, else None.

        Supported header formats:
        - OpenAI: x-ratelimit-remaining-requests, x-ratelimit-reset-requests,
                  x-ratelimit-remaining-tokens, x-ratelimit-reset-tokens
        - Anthropic: retry-after, x-ratelimit-limit-requests,
                     x-ratelimit-remaining-requests
        - GitHub Models: x-ratelimit-remaining, x-ratelimit-reset
        - Azure OpenAI: retry-after-ms, x-ms-ratelimit-remaining-requests,
                        x-ms-ratelimit-reset-requests
        - Gemini: x-ratelimit-remaining, x-ratelimit-reset
        """
        lower_headers = {str(k).lower(): str(v) for k, v in headers.items()}
        provider = _extract_provider(model)
        state = self.get_provider(model)

        # Parse Retry-After first (universal)
        retry_after = self.parse_retry_after(headers)
        if retry_after is not None:
            state.last_retry_after = float(retry_after)
            return retry_after

        # Provider-specific header parsing
        if provider in ("openai", "azure"):
            return self._parse_openai_headers(state, lower_headers)
        if provider == "gh":
            return self._parse_github_headers(state, lower_headers)
        if provider == "gemini":
            return self._parse_gemini_headers(state, lower_headers)
        if provider == "anthropic":
            return self._parse_anthropic_headers(state, lower_headers)

        return None

    def get_cooldown_seconds(
        self,
        model: str,
        headers: dict[str, str] | None = None,
        default_cooldown: int = 120,
    ) -> int:
        """Get the appropriate cooldown for a rate-limited model.

        Priority: provider Retry-After > parsed headers > default + jitter.

        Args:
            model: Model identifier
            headers: Response headers (if available)
            default_cooldown: Fallback cooldown seconds

        Returns:
            Recommended cooldown in seconds
        """
        if headers:
            from_headers = self.update_from_headers(model, headers)
            if from_headers is not None:
                return from_headers

        # Fallback: exponential backoff with jitter
        state = self.get_provider(model)
        if state.last_retry_after is not None:
            # Use last known retry-after as base estimate
            base = int(state.last_retry_after)
        else:
            base = default_cooldown

        # Add 10-25% jitter to prevent thundering herd
        jitter = random.uniform(0.1, 0.25)
        return int(base * (1 + jitter))

    def record_request(self, model: str) -> None:
        """Record a request for throttle factor computation.

        Args:
            model: Model identifier (provider extracted automatically)
        """
        state = self.get_provider(model)
        state.total_requests += 1

    def record_error(self, model: str) -> None:
        """Record an error for throttle factor computation.

        Args:
            model: Model identifier (provider extracted automatically)
        """
        state = self.get_provider(model)
        state.recent_errors += 1

    def compute_throttle_factor(self, model: str) -> float:
        """Return 0.0-1.0 throttle factor based on recent error rate.

        A throttle factor of 0.0 means no throttling; 1.0 means maximum
        throttling. The factor scales linearly at 2x the error rate,
        capped at 1.0.

        Args:
            model: Model identifier (provider extracted automatically)

        Returns:
            Throttle factor between 0.0 and 1.0
        """
        provider = _extract_provider(model)
        state = self._providers.get(provider)
        if not state or state.total_requests < 10:
            return 0.0  # Not enough data
        error_rate = state.recent_errors / state.total_requests
        return min(1.0, error_rate * 2)

    def _parse_openai_headers(
        self, state: ProviderRateLimits, headers: dict[str, str]
    ) -> int | None:
        """Parse OpenAI-style rate-limit headers."""
        remaining_requests = _first_safe_int(
            headers,
            (
                "x-ratelimit-remaining-requests",
                "x-ms-ratelimit-remaining-requests",
            ),
        )
        reset_requests = _first_reset_seconds(
            headers,
            (
                "x-ratelimit-reset-requests",
                "x-ms-ratelimit-reset-requests",
            ),
        )
        remaining_tokens = _first_safe_int(
            headers,
            (
                "x-ratelimit-remaining-tokens",
                "x-ms-ratelimit-remaining-tokens",
            ),
        )
        reset_tokens = _first_reset_seconds(
            headers,
            (
                "x-ratelimit-reset-tokens",
                "x-ms-ratelimit-reset-tokens",
            ),
        )

        # Update RPM bucket
        if remaining_requests is not None and reset_requests is not None:
            state.rpm_bucket.reset(remaining_requests, reset_requests)

        # Update TPM bucket
        if (
            state.tpm_bucket
            and remaining_tokens is not None
            and reset_tokens is not None
        ):
            state.tpm_bucket.reset(remaining_tokens, reset_tokens)

        cooldowns: list[int] = []
        if remaining_requests is not None and remaining_requests <= 0:
            cooldown = _cooldown_seconds(reset_requests)
            if cooldown is not None:
                cooldowns.append(cooldown)
        if remaining_tokens is not None and remaining_tokens <= 0:
            cooldown = _cooldown_seconds(reset_tokens)
            if cooldown is not None:
                cooldowns.append(cooldown)

        return max(cooldowns) if cooldowns else None

    def _parse_github_headers(
        self, state: ProviderRateLimits, headers: dict[str, str]
    ) -> int | None:
        """Parse GitHub Models rate-limit headers."""
        openai_style_cooldown = self._parse_openai_headers(state, headers)
        if openai_style_cooldown is not None:
            return openai_style_cooldown

        remaining = _first_safe_int(
            headers,
            ("x-ratelimit-remaining", "ratelimit-remaining"),
        )
        reset = _first_reset_seconds(
            headers,
            ("x-ratelimit-reset", "ratelimit-reset"),
        )

        if remaining is not None and reset is not None:
            state.rpm_bucket.reset(remaining, reset)

        if remaining is not None and remaining <= 0:
            return _cooldown_seconds(reset)

        return None

    def _parse_gemini_headers(
        self, state: ProviderRateLimits, headers: dict[str, str]
    ) -> int | None:
        """Parse Gemini/Google rate-limit reset headers."""
        remaining = _first_safe_int(
            headers,
            (
                "x-ratelimit-remaining-requests",
                "x-ratelimit-remaining",
                "x-goog-ratelimit-remaining-requests",
                "x-goog-ratelimit-remaining",
            ),
        )
        reset = _first_reset_seconds(
            headers,
            (
                "x-ratelimit-reset-requests",
                "x-ratelimit-reset",
                "x-goog-ratelimit-reset-requests",
                "x-goog-ratelimit-reset",
            ),
        )
        remaining_tokens = _first_safe_int(
            headers,
            (
                "x-ratelimit-remaining-tokens",
                "x-goog-ratelimit-remaining-tokens",
            ),
        )
        reset_tokens = _first_reset_seconds(
            headers,
            (
                "x-ratelimit-reset-tokens",
                "x-goog-ratelimit-reset-tokens",
            ),
        )

        if remaining is not None and reset is not None:
            state.rpm_bucket.reset(remaining, reset)
        if (
            state.tpm_bucket
            and remaining_tokens is not None
            and reset_tokens is not None
        ):
            state.tpm_bucket.reset(remaining_tokens, reset_tokens)

        cooldowns: list[int] = []
        if remaining is not None and remaining <= 0:
            cooldown = _cooldown_seconds(reset)
            if cooldown is not None:
                cooldowns.append(cooldown)
        if remaining_tokens is not None and remaining_tokens <= 0:
            cooldown = _cooldown_seconds(reset_tokens)
            if cooldown is not None:
                cooldowns.append(cooldown)

        return max(cooldowns) if cooldowns else None

    def _parse_anthropic_headers(
        self, state: ProviderRateLimits, headers: dict[str, str]
    ) -> int | None:
        """Parse Anthropic-style rate-limit headers."""
        remaining = _first_safe_int(
            headers,
            (
                "anthropic-ratelimit-requests-remaining",
                "x-ratelimit-remaining-requests",
            ),
        )
        reset = _first_reset_seconds(
            headers,
            (
                "anthropic-ratelimit-requests-reset",
                "x-ratelimit-reset-requests",
            ),
        )

        if remaining is not None:
            state.rpm_bucket.reset(remaining, reset or 60.0)

        if remaining is not None and remaining <= 0:
            return _cooldown_seconds(reset) or 60

        return None


def _extract_provider(model: str) -> str:
    """Extract provider name from model identifier.

    Supports formats: 'provider:model', 'provider/model', plain 'model'.
    """
    if ":" in model:
        return model.split(":")[0].lower()
    if "/" in model:
        return model.split("/")[0].lower()
    return "unknown"


def _safe_int(value: str | None) -> int | None:
    """Parse an integer from a header value, returning None on failure."""
    if value is None:
        return None
    try:
        result = int(value)
        # Azure is known to return -1 and 0 incorrectly
        return result if result >= 0 else None
    except (ValueError, TypeError):
        return None


def _first_header(headers: dict[str, str], names: tuple[str, ...]) -> str | None:
    """Return the first present header value from a list of lowercase names."""
    for name in names:
        value = headers.get(name)
        if value is not None and value.strip():
            return value
    return None


def _first_safe_int(headers: dict[str, str], names: tuple[str, ...]) -> int | None:
    """Parse the first present integer header from a list of names."""
    for name in names:
        parsed = _safe_int(headers.get(name))
        if parsed is not None:
            return parsed
    return None


def _first_reset_seconds(
    headers: dict[str, str], names: tuple[str, ...]
) -> float | None:
    """Parse the first present reset header into seconds from now."""
    for name in names:
        parsed = _parse_reset_seconds(headers.get(name))
        if parsed is not None:
            return parsed
    return None


def _parse_milliseconds(value: str | None) -> float | None:
    """Parse a millisecond retry header to seconds."""
    if value is None:
        return None
    try:
        seconds = float(value) / 1000.0
    except (ValueError, TypeError):
        return None
    return seconds if seconds > 0 else None


def _parse_reset_seconds(value: str | None) -> float | None:
    """Parse reset headers as duration, Unix deadline, or HTTP/RFC3339 date."""
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    try:
        numeric = float(stripped)
        if numeric > 1_000_000_000_000:
            seconds = (numeric / 1000.0) - time.time()
        elif numeric > 1_000_000_000:
            seconds = numeric - time.time()
        else:
            seconds = numeric
        return seconds if seconds > 0 else None
    except ValueError:
        pass

    duration = _parse_duration(stripped)
    if duration is not None:
        return duration

    try:
        dt = parsedate_to_datetime(stripped)
        seconds = (dt - datetime.now(UTC)).total_seconds()
        return seconds if seconds > 0 else None
    except (ValueError, TypeError):
        pass

    try:
        dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        seconds = (dt - datetime.now(UTC)).total_seconds()
        return seconds if seconds > 0 else None
    except ValueError:
        return None


def _cooldown_seconds(seconds: float | int | None) -> int | None:
    """Return a bounded positive cooldown in whole seconds."""
    if seconds is None or seconds <= 0 or seconds > 3600:
        return None
    return max(1, math.ceil(seconds))


def _parse_duration(value: str | None) -> float | None:
    """Parse a duration string like '6s', '1m30s', '500ms' to seconds."""
    if value is None:
        return None

    try:
        # Try plain seconds first
        return float(value)
    except ValueError:
        pass

    # Parse OpenAI-style duration strings: "6s", "1m0s", "200ms"
    total = 0.0
    remaining = value.strip()

    # Minutes
    minutes, remaining, minutes_failed = _consume_duration_minutes(remaining)
    if minutes_failed:
        return None
    total += minutes

    # Seconds
    seconds, remaining = _consume_duration_seconds(remaining)
    total += seconds

    # Milliseconds
    total += _consume_duration_milliseconds(remaining)

    return total if total > 0 else None


def _consume_duration_minutes(remaining: str) -> tuple[float, str, bool]:
    """Extract the minutes component from a duration string.

    Returns ``(seconds_from_minutes, rest, failed)`` where ``failed`` is True
    only when a minutes marker is present but its value is unparseable.
    """
    # Match a minutes marker ('m' NOT followed by 's') so a millisecond token
    # like "500ms" elsewhere in the string does not block minute parsing
    # (e.g. "1m500ms" -> 1 minute + 500 ms).
    match = re.search(r"(\d+(?:\.\d+)?)m(?!s)", remaining)
    if match:
        try:
            minutes = float(match.group(1))
        except ValueError:
            return 0.0, remaining, True
        rest = remaining[: match.start()] + remaining[match.end() :]
        return minutes * 60, rest, False
    return 0.0, remaining, False


def _consume_duration_seconds(remaining: str) -> tuple[float, str]:
    """Extract the seconds component from a duration string."""
    if "s" in remaining and "ms" not in remaining:
        parts = remaining.split("s", 1)
        rest = parts[1] if len(parts) > 1 else ""
        try:
            return float(parts[0]), rest
        except ValueError:
            return 0.0, rest
    return 0.0, remaining


def _consume_duration_milliseconds(remaining: str) -> float:
    """Extract the milliseconds component from a duration string."""
    if "ms" in remaining:
        parts = remaining.split("ms", 1)
        try:
            return float(parts[0]) / 1000
        except ValueError:
            return 0.0
    return 0.0
