from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from filelock import FileLock

from .model_registry import is_quarantined
from .model_stats import CircuitState, ModelStats
from .rate_limit_tracker import RateLimitTracker, _extract_provider
from .redis_state import _COUNTER_FIELDS, RedisCircuitBreakerStore
from .router import ModelRouter, ModelTier

logger = logging.getLogger(__name__)


# HTTP status codes that authoritatively classify a provider error.  A real
# status is preferred over message-substring matching: only these mark a model
# permanently unavailable, so a transient "model not found" message can no
# longer evict a healthy model (see SmartModelRouter._classify_and_record_error).
_PERMANENT_HTTP_STATUS = frozenset({401, 403, 404})
_RATE_LIMIT_HTTP_STATUS = 429
_TIMEOUT_HTTP_STATUS = 408


class CircuitResolvedError(Exception):
    """Signal: a preceding probe resolved the HALF_OPEN circuit.

    Raised inside ``execute_with_bulkhead`` when a caller acquires the probe
    lock but finds the circuit no longer HALF_OPEN (a prior probe closed or
    re-opened it).  The caller should treat this model as unavailable and
    re-route to the next candidate.  Never surfaces to end-callers.

    This exception is intentionally shared between ``smart_router`` and
    ``fallback_selector``; the public name (no leading underscore) signals
    that cross-module import is by design.
    """

    def __init__(self, model: str, new_state: CircuitState) -> None:
        super().__init__(
            f"Circuit for {model!r} resolved to {new_state.value} before probe ran"
        )
        self.model = model
        self.new_state = new_state


def _counter_snapshot(stats: ModelStats) -> dict[str, int]:
    """Capture the monotonic counter values used as a CAS persist baseline."""
    stats_dict = stats.to_dict()
    return {field_name: stats_dict.get(field_name, 0) for field_name in _COUNTER_FIELDS}


# Metrics instrumentation — all calls are no-ops when metrics are not enabled
try:
    from ..integrations.metrics import (
        record_circuit_breaker_trip as _record_cb_trip,
    )
    from ..integrations.metrics import (
        record_llm_request as _record_llm_request,
    )

    _METRICS_AVAILABLE = True
except ImportError:  # pragma: no cover — optional dependency
    _METRICS_AVAILABLE = False

    def _record_cb_trip(provider: str, state: str) -> None:  # type: ignore[misc]
        pass

    def _record_llm_request(  # type: ignore[misc]
        provider: str,
        duration_seconds: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        pass


# Default per-provider concurrency limits (ADR-002A)
_DEFAULT_BULKHEAD_LIMITS: dict[str, int] = {
    "ollama": 10,
    "openai": 50,
    "anthropic": 50,
    "gemini": 50,
    "gh": 30,
    "azure": 50,
}


@dataclass(frozen=True)
class ModelSelection:
    """Result of a model selection decision.

    Captures whether the returned model came from the requested tier
    (normal) or a different tier (degraded fallback). Callers can
    inspect ``is_degraded`` to log, meter, or adjust behavior.
    """

    model_name: str
    requested_tier: str
    actual_tier: str
    is_degraded: bool = False


@dataclass
class CooldownConfig:
    """Configuration for adaptive cooldowns."""

    # Base cooldown durations
    base_failure_cooldown_seconds: int = 30
    base_rate_limit_cooldown_seconds: int = 120
    base_timeout_cooldown_seconds: int = 60

    # Scaling factors
    consecutive_failure_multiplier: float = 1.5
    max_cooldown_seconds: int = 600  # 10 minutes

    # Recovery
    success_count_to_clear: int = 3


@dataclass
class SmartModelRouter(ModelRouter):
    """Production-hardened router with learning and adaptive behavior."""

    # Stats for each model
    model_stats: dict[str, ModelStats] = field(default_factory=dict)

    # Configuration
    cooldown_config: CooldownConfig = field(default_factory=CooldownConfig)

    # Persistence
    stats_file: Path | None = None
    _auto_save: bool = True

    # Cost weights (tokens per $0.001)
    model_costs: dict[str, float] = field(
        default_factory=lambda: {
            "ollama:phi4": 0.0,
            "ollama:llama3.2:latest": 0.0,
            "gh:gpt-4o-mini": 0.15,
            "gh:gpt-4o": 2.5,
        }
    )

    # ADR-002E: Rate-limit tracker with provider-aware header parsing
    rate_limit_tracker: RateLimitTracker = field(default_factory=RateLimitTracker)

    # ADR-002A: Per-provider bulkhead semaphores (cascade prevention)
    _provider_semaphores: dict[str, asyncio.Semaphore] = field(
        default_factory=dict, repr=False
    )

    # ADR-002D: Per-provider probe locks (half-open serialization)
    _probe_locks: dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)

    # Redis-backed shared state (None = local-only mode)
    _redis_store: RedisCircuitBreakerStore | None = field(default=None, repr=False)

    # Per-model counter baselines for CAS read-modify-write persistence.
    # Tracks the monotonic-counter values this worker last successfully wrote
    # to Redis, so each save persists only the delta produced since then —
    # preventing concurrent workers from clobbering each other's circuit
    # breaker counters (last-writer-wins). Keyed by model name.
    _redis_counter_baselines: dict[str, dict[str, int]] = field(
        default_factory=dict, repr=False
    )

    # Background save tasks — prevent GC of fire-and-forget Redis writes
    _background_tasks: set[asyncio.Task[None]] = field(
        default_factory=set, repr=False
    )

    # Serializes _save_stats_to_redis: record_success/record_failure spawn a
    # fire-and-forget save task each, and two concurrent saves for the same
    # model would read the same baseline, compute the same delta, and CAS it
    # twice (over-counting). The lock makes the second save wait, so it sees
    # the updated baseline and persists only the genuinely new delta.
    _redis_save_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, repr=False
    )

    # Last model selection result (for degraded-mode inspection)
    _last_selection: ModelSelection | None = field(default=None, repr=False)

    # Degraded routing observability
    degraded_selection_count: int = 0
    on_degraded_selection: Callable[[ModelSelection], None] | None = field(
        default=None, repr=False
    )

    @property
    def last_selection(self) -> ModelSelection | None:
        """The most recent model selection result.

        Inspect ``last_selection.is_degraded`` after calling
        ``get_model_for_tier()`` to determine if cross-tier fallback
        was used.
        """
        return self._last_selection

    def __post_init__(self) -> None:
        if self.stats_file:
            self._load_stats()

    @property
    def _should_persist(self) -> bool:
        """Whether persistence is configured (Redis or file)."""
        redis_ok = (
            self._redis_store is not None and self._redis_store.is_connected
        )
        return bool(self.stats_file) or redis_ok

    def _get_stats(self, model: str) -> ModelStats:
        """Get or create stats for a model."""
        if model not in self.model_stats:
            self.model_stats[model] = ModelStats(model_id=model)
        return self.model_stats[model]

    def _get_semaphore(self, model: str) -> asyncio.Semaphore:
        """Get or create a bulkhead semaphore for a provider."""
        provider = _extract_provider(model)
        if provider not in self._provider_semaphores:
            limit = _DEFAULT_BULKHEAD_LIMITS.get(provider, 20)
            self._provider_semaphores[provider] = asyncio.Semaphore(limit)
        return self._provider_semaphores[provider]

    def _get_probe_lock(self, model: str) -> asyncio.Lock:
        """Get or create a probe lock for half-open serialization."""
        provider = _extract_provider(model)
        if provider not in self._probe_locks:
            self._probe_locks[provider] = asyncio.Lock()
        return self._probe_locks[provider]

    def _set_last_selection(self, selection: ModelSelection) -> None:
        """Store selection metadata and emit degraded-mode observability."""
        self._last_selection = selection
        if not selection.is_degraded:
            return

        self.degraded_selection_count += 1
        logger.warning(
            "Degraded model selection: requested_tier=%s actual_tier=%s model=%s",
            selection.requested_tier,
            selection.actual_tier,
            selection.model_name,
        )
        if self.on_degraded_selection is not None:
            try:
                self.on_degraded_selection(selection)
            except Exception:
                logger.exception("Degraded model selection callback failed")

    def record_success(self, model: str, latency_ms: float) -> None:
        """Record a successful call and emit latency metric."""
        stats = self._get_stats(model)
        stats.record_success(latency_ms)
        self.mark_available(model)

        # Emit LLM latency metric (convert ms → seconds)
        _record_llm_request(
            provider=_extract_provider(model),
            duration_seconds=latency_ms / 1000.0,
        )

        if self._auto_save and self._should_persist:
            self._save_stats()

    def record_failure(
        self, model: str, error_type: str = "unknown", is_permanent: bool = False
    ) -> None:
        """Record a failed call and emit circuit breaker metric."""
        stats = self._get_stats(model)
        stats.record_failure(error_type)

        # Apply adaptive cooldown
        cooldown = self._calculate_cooldown(stats, error_type)
        stats.set_cooldown(cooldown)

        # Emit circuit breaker trip metric
        _record_cb_trip(
            provider=_extract_provider(model),
            state=stats.circuit_state.value,
        )

        # Mark permanently unavailable if permanent error
        if is_permanent:
            self.mark_unavailable(model)

        if self._auto_save and self._should_persist:
            self._save_stats()

    def record_rate_limit(
        self,
        model: str,
        response_headers: dict[str, str] | None = None,
    ) -> None:
        """Record a rate limit hit with provider-aware cooldown and metric."""
        stats = self._get_stats(model)
        cooldown = self.rate_limit_tracker.get_cooldown_seconds(
            model, headers=response_headers
        )
        stats.record_rate_limit(retry_after_seconds=cooldown)

        # Emit circuit breaker trip metric for rate-limit event
        _record_cb_trip(
            provider=_extract_provider(model),
            state="rate_limited",
        )

        if self._auto_save and self._should_persist:
            self._save_stats()

    def record_timeout(self, model: str) -> None:
        """Record a timeout and emit circuit breaker metric."""
        stats = self._get_stats(model)
        stats.record_timeout()

        cooldown = self._calculate_cooldown(stats, "timeout")
        stats.set_cooldown(cooldown)

        # Emit circuit breaker trip metric for timeout event
        _record_cb_trip(
            provider=_extract_provider(model),
            state="timeout",
        )

        if self._auto_save and self._should_persist:
            self._save_stats()

    def _calculate_cooldown(self, stats: ModelStats, error_type: str) -> int:
        """Calculate adaptive cooldown duration."""
        cfg = self.cooldown_config
        if error_type == "rate_limit":
            base = cfg.base_rate_limit_cooldown_seconds
        elif error_type == "timeout":
            base = cfg.base_timeout_cooldown_seconds
        else:
            base = cfg.base_failure_cooldown_seconds
        failures = stats._consecutive_failures
        multiplier = cfg.consecutive_failure_multiplier ** min(failures, 5)

        cooldown = int(base * multiplier)
        return min(cooldown, cfg.max_cooldown_seconds)

    def _cross_tier_search(
        self,
        original_tier: ModelTier,
        max_cost: float | None = None,
    ) -> tuple[list[tuple[str, ModelStats]], ModelTier | None]:
        """Search adjacent tiers for available models.

        Returns:
            A tuple of (candidates, actual_tier). actual_tier is the tier
            that provided the candidates, or None if no candidates found.
        """
        all_tiers = sorted(ModelTier, key=lambda t: t.value)
        eligible = [
            t for t in all_tiers if t != original_tier and t != ModelTier.TIER_0
        ]

        # Sort by distance from original tier, preferring lower (degrade) first
        def tier_priority(t: ModelTier) -> tuple[int, int]:
            distance = abs(t.value - original_tier.value)
            direction = 0 if t.value < original_tier.value else 1
            return (distance, direction)

        eligible.sort(key=tier_priority)

        for tier in eligible:
            candidates = self._find_candidates_in_tier(tier, max_cost)
            if candidates:
                return candidates, tier

        return [], None

    def _find_candidates_in_tier(
        self,
        tier: ModelTier,
        max_cost: float | None = None,
    ) -> list[tuple[str, ModelStats]]:
        """Find all healthy candidate models in a single tier."""
        chain = self.get_chain(tier)
        candidates: list[tuple[str, ModelStats]] = []

        for model in chain:
            if is_quarantined(model):
                continue  # retired at provider (ADR-040 drift detection)
            if not self.is_model_available(model):
                continue
            stats = self._get_stats(model)
            if not stats.check_circuit():
                continue
            if stats.is_in_cooldown:
                continue
            if max_cost is not None:
                cost = self.model_costs.get(model, 0.0)
                if cost > max_cost:
                    continue
            candidates.append((model, stats))

        return candidates

    def get_model_for_tier(
        self,
        tier: ModelTier,
        prefer_healthy: bool = True,
        max_cost: float | None = None,
        allow_cross_tier: bool = True,
    ) -> str | None:
        """Get best available model for a tier with cross-tier degradation.

        After calling this method, inspect ``last_selection`` to determine
        whether cross-tier fallback was used (``is_degraded=True``).
        """
        candidates = self._find_candidates_in_tier(tier, max_cost)
        actual_tier = tier
        is_degraded = False

        if not candidates and allow_cross_tier:
            candidates, cross_tier = self._cross_tier_search(tier, max_cost)
            if cross_tier is not None:
                actual_tier = cross_tier
                is_degraded = True

        if not candidates:
            self._last_selection = None
            # E7-3: Raise when ALL tiers are exhausted (allow_cross_tier=True means
            # the caller already searched every tier). Single-tier misses (allow_cross_tier=False)
            # return None for backward compatibility — the caller decides how to degrade.
            if allow_cross_tier and not os.environ.get("AGENTIC_NO_LLM"):
                # Lazy import to avoid circular dependency
                # (models → smart_router → core.errors → core → engine → models)
                from ..core.errors import NoProviderConfiguredError

                raise NoProviderConfiguredError()
            return None

        if not prefer_healthy or len(candidates) == 1:
            selected = candidates[0][0]
            self._set_last_selection(
                ModelSelection(
                    model_name=selected,
                    requested_tier=tier.name,
                    actual_tier=actual_tier.name,
                    is_degraded=is_degraded,
                )
            )
            return selected

        # Score candidates by health
        def score(model_stats: tuple[str, ModelStats]) -> float:
            _, stats = model_stats
            # Weight: success_rate (60%) + low latency (20%) + recency (20%)
            success_score = stats.recent_success_rate * 0.6

            # Latency score (lower is better, normalize to 0-1)
            latency = stats.avg_latency_ms
            latency_score = max(0, 1 - (latency / 10000)) * 0.2 if latency > 0 else 0.2

            # Recency score (recent successes preferred)
            recency_score = 0.2
            if stats.last_success:
                age = (datetime.now(UTC) - stats.last_success).total_seconds()
                recency_score = max(0, 1 - (age / 3600)) * 0.2  # Decay over 1 hour

            return success_score + latency_score + recency_score

        candidates.sort(key=score, reverse=True)
        selected = candidates[0][0]
        self._set_last_selection(
            ModelSelection(
                model_name=selected,
                requested_tier=tier.name,
                actual_tier=actual_tier.name,
                is_degraded=is_degraded,
            )
        )
        return selected

    def get_fallback_chain_with_health(
        self, tier: ModelTier
    ) -> list[tuple[str, float]]:
        """Get fallback chain with health scores."""
        chain = self.get_chain(tier)
        scored = []

        for model in chain:
            stats = self._get_stats(model)
            if stats.check_circuit() and not stats.is_in_cooldown:
                scored.append((model, stats.recent_success_rate))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def predict_availability(self, model: str) -> dict[str, Any]:
        """Predict model availability (dict with confidence and reason)."""
        stats = self._get_stats(model)

        # Check obvious blockers
        if is_quarantined(model):
            return {
                "available": False,
                "confidence": 1.0,
                "reason": "quarantined",
            }
        if not self.is_model_available(model):
            return {
                "available": False,
                "confidence": 1.0,
                "reason": "marked_unavailable",
            }

        if stats.circuit_state == CircuitState.OPEN:
            return {
                "available": False,
                "confidence": 0.9,
                "reason": "circuit_open",
                "recovery_in_seconds": stats._recovery_timeout_seconds,
            }

        if stats.is_in_cooldown:
            return {
                "available": False,
                "confidence": 0.95,
                "reason": "in_cooldown",
                "cooldown_remaining": stats.cooldown_remaining_seconds,
            }

        # Predict based on recent performance
        if stats.recent_success_rate < 0.3:
            return {
                "available": True,
                "confidence": 0.4,
                "reason": "poor_recent_performance",
                "success_rate": stats.recent_success_rate,
            }

        if stats.rate_limit_count > 5:
            return {
                "available": True,
                "confidence": 0.6,
                "reason": "rate_limit_history",
                "rate_limit_count": stats.rate_limit_count,
            }

        return {
            "available": True,
            "confidence": min(0.9, stats.recent_success_rate + 0.1),
            "reason": "healthy",
            "success_rate": stats.recent_success_rate,
        }

    def get_stats_summary(self) -> dict[str, Any]:
        """Get summary of all model stats."""
        return {
            "total_models": len(self.model_stats),
            "healthy_models": sum(1 for s in self.model_stats.values() if s.is_healthy),
            "degraded_selection_count": self.degraded_selection_count,
            "models": {
                model: stats.to_dict() for model, stats in self.model_stats.items()
            },
        }

    @classmethod
    async def create_with_redis(
        cls,
        redis_url: str,
        prefix: str = "agentic:cb:",
        ttl_seconds: int = 3600,
        **kwargs: Any,
    ) -> SmartModelRouter:
        """Factory: create a router with a Redis-backed state store.

        On connection failure the router still works — it falls back to
        local file persistence silently.

        Args:
            redis_url: Redis connection URL.
            prefix: Key prefix for circuit breaker state.
            ttl_seconds: TTL for Redis keys.
            **kwargs: Forwarded to ``SmartModelRouter()``.

        Returns:
            A ``SmartModelRouter`` with Redis store attached (or ``None``
            store if connection failed).
        """
        store = await RedisCircuitBreakerStore.connect(
            redis_url=redis_url,
            prefix=prefix,
            ttl_seconds=ttl_seconds,
        )
        router = cls(_redis_store=store, **kwargs)
        # Attempt initial load from Redis
        if store.is_connected:
            await router._load_stats_from_redis()
        return router

    def _save_stats(self) -> None:
        """Save stats to Redis (if available) or file.

        Redis writes are fire-and-forget via ``asyncio.create_task`` so
        that synchronous callers (``record_success``, ``record_failure``)
        are not blocked.  File fallback remains synchronous with
        cross-process ``FileLock``.
        """
        # Try Redis first (non-blocking)
        if self._redis_store is not None and self._redis_store.is_connected:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._save_stats_to_redis())
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                return
            except RuntimeError:
                # No running event loop — fall through to file
                pass

        # File fallback
        self._save_stats_to_file()

    async def drain_background_tasks(self) -> None:
        """Await all outstanding fire-and-forget Redis save tasks.

        Call this during graceful shutdown (e.g. lifespan teardown) to
        ensure no circuit-breaker state writes are silently abandoned.
        After this coroutine returns, ``_background_tasks`` is empty.

        Example::

            # FastAPI / Starlette lifespan
            @asynccontextmanager
            async def lifespan(app):
                yield
                await router.drain_background_tasks()
        """
        pending = set(self._background_tasks)
        if not pending:
            return
        logger.debug("Draining %d background Redis save task(s)", len(pending))
        results = await asyncio.gather(*pending, return_exceptions=True)
        for exc in results:
            if isinstance(exc, Exception):
                logger.warning("Background Redis save task raised: %s", exc)
        # Tasks remove themselves via done_callback; ensure the set is clear
        # even if a task was already done before gather started.
        self._background_tasks.difference_update(pending)

    async def aclose(self) -> None:
        """Flush pending background tasks and release resources.

        Convenience alias for shutdown sequences that follow the
        standard ``async with`` / ``aclose()`` convention.
        """
        await self.drain_background_tasks()

    def _save_stats_to_file(self) -> None:
        """Save stats to file atomically with cross-process file locking."""
        if not self.stats_file:
            return

        data = {
            "version": "1.0",
            "saved_at": datetime.now(UTC).isoformat(),
            "stats": {
                model: stats.to_dict() for model, stats in self.model_stats.items()
            },
        }

        lock = FileLock(str(self.stats_file) + ".lock")
        with lock:
            # Atomic write: write to temp file, then rename
            temp_file = self.stats_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(data, indent=2))
            temp_file.replace(self.stats_file)

    async def _save_stats_to_redis(self) -> None:
        """Persist model stats to Redis via per-model CAS read-modify-write.

        Each model is saved with :meth:`RedisCircuitBreakerStore.save_stats_cas`,
        which re-reads the current value and merges this worker's counter
        deltas on top of it. This prevents concurrent workers from clobbering
        each other's circuit-breaker counters (the old ``save_all_stats``
        pipeline was blind last-writer-wins). Falls back to local file
        persistence if any model fails to persist.
        """
        if self._redis_store is None:
            return

        # Serialize saves from this router: without the lock, two in-flight
        # save tasks would both compute deltas from the same baseline and
        # apply them twice (see _redis_save_lock).
        async with self._redis_save_lock:
            all_persisted = True
            for model, stats in self.model_stats.items():
                baseline = self._redis_counter_baselines.get(model)
                new_baseline = await self._redis_store.save_stats_cas(
                    model, stats, baseline
                )
                if new_baseline is None:
                    all_persisted = False
                else:
                    self._redis_counter_baselines[model] = new_baseline

        if not all_persisted:
            logger.debug("Redis CAS save incomplete; local file fallback will be used")
            self._save_stats_to_file()

    def _load_stats(self) -> None:
        """Load stats from file with cross-process file locking."""
        if not self.stats_file or not self.stats_file.exists():
            return

        lock = FileLock(str(self.stats_file) + ".lock")
        try:
            with lock:
                data = json.loads(self.stats_file.read_text())
            for model, stats_dict in data.get("stats", {}).items():
                self.model_stats[model] = ModelStats.from_dict(stats_dict)
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to load stats from file; starting fresh")

    async def _load_stats_from_redis(self) -> None:
        """Load all model stats from Redis into memory."""
        if self._redis_store is None:
            return
        try:
            loaded = await self._redis_store.load_all_stats()
            if loaded:
                self.model_stats.update(loaded)
                # Seed CAS baselines from the loaded counts so the next save
                # persists only deltas produced after this load (not the full
                # already-persisted counts, which would double-count).
                for model, stats in loaded.items():
                    self._redis_counter_baselines[model] = _counter_snapshot(stats)
                logger.info(
                    "Loaded %d model stats from Redis", len(loaded)
                )
        except Exception:
            logger.warning(
                "Failed to load stats from Redis; using local state",
                exc_info=True,
            )

    def _is_model_ready_for_attempt(self, model: str) -> bool:
        """Check if a model can accept a request right now."""
        stats = self._get_stats(model)
        if stats.circuit_state == CircuitState.HALF_OPEN:
            if self._get_probe_lock(model).locked():
                return False
        semaphore = self._get_semaphore(model)
        if semaphore.locked():
            return False

        return True

    @asynccontextmanager
    async def execute_with_bulkhead(self, model: str) -> AsyncIterator[None]:
        """Guard a provider call with bulkhead and probe-lock controls.

        All external provider calls **must** be wrapped with this context
        manager (or :meth:`_execute_call`) so that the HALF_OPEN circuit-
        breaker probe lock serialises concurrent callers correctly.  Callers
        that bypass this guard will race on the probe and may submit multiple
        simultaneous probes, defeating the half-open serialisation invariant.

        Half-open single-probe invariant:
          Only one coroutine should reach the provider as a probe.  The
          correctness guarantee comes from re-reading ``circuit_state`` *under
          the probe lock* (step 3 below) — not from the lockless ``locked()``
          check, which is only a fast-path optimisation to avoid acquiring the
          lock when a probe is already obviously in-flight.

          1. **Fast-path bail-out (optimisation only):** if ``probe_lock.locked()``
             is True, another coroutine already owns the probe slot.  We raise
             ``CircuitResolvedError`` immediately (no waiting) so
             ``call_with_fallback`` can skip this model without queuing.

          2. **Lock acquisition:** we call ``await probe_lock.acquire()``.  On an
             uncontested asyncio Lock this returns without suspending the
             coroutine; it is NOT guaranteed to be yield-free in all Python
             versions, so the lockless check in step 1 must not be relied on
             for correctness.

          3. **Authoritative state re-read (correctness gate):** once we hold
             the lock, we re-read ``circuit_state``.  A probe that completed
             between our ``locked()`` check and our ``acquire()`` will have
             transitioned the circuit to CLOSED or OPEN; a late-arriving loser
             therefore sees the updated state and raises ``CircuitResolvedError``
             rather than firing a redundant probe.  This is the invariant that
             guarantees at-most-one concurrent probe.

          4. ``probe_in_progress`` is set under the lock so that concurrent
             callers that check ``circuit_state`` via ``check_circuit()`` before
             the lock is free also see the probe is occupied and back off.
        """
        stats = self._get_stats(model)
        semaphore = self._get_semaphore(model)
        async with semaphore:
            if stats.circuit_state == CircuitState.HALF_OPEN:
                probe_lock = self._get_probe_lock(model)
                # Non-blocking gate: if a probe is already in-flight, bail out
                # immediately rather than queuing behind the lock.
                if probe_lock.locked():
                    raise CircuitResolvedError(model, stats.circuit_state)
                # Acquire synchronously (no yield on an uncontested Lock in asyncio).
                await probe_lock.acquire()
                # Re-read state under the lock: the winning probe may have resolved
                # the circuit between our locked() check and acquire().
                if stats.circuit_state != CircuitState.HALF_OPEN:
                    probe_lock.release()
                    raise CircuitResolvedError(model, stats.circuit_state)
                stats.probe_in_progress = True
                try:
                    yield
                finally:
                    stats.probe_in_progress = False
                    probe_lock.release()
            else:
                yield

    async def _execute_call(
        self, caller: Callable[[str, str], Awaitable[Any]], model: str, prompt: str
    ) -> Any:
        """Execute a model call with bulkhead and probe-lock guards.

        Re-raises ``CircuitResolvedError`` so that ``call_with_fallback``
        can skip this model and route to the next candidate.
        """
        async with self.execute_with_bulkhead(model):
            return await caller(model, prompt)

    @staticmethod
    def _coerce_headers(headers: Any) -> dict[str, str] | None:
        """Coerce provider SDK header mappings into a plain string dict."""
        if isinstance(headers, Mapping):
            return {str(key): str(value) for key, value in headers.items()}
        return None

    def _headers_from_error(self, error: Exception) -> dict[str, str] | None:
        """Extract response headers from common provider exception shapes."""
        headers = self._coerce_headers(getattr(error, "headers", None))
        if headers is not None:
            return headers

        response = getattr(error, "response", None)
        if response is not None:
            return self._coerce_headers(getattr(response, "headers", None))
        return None

    def _status_code_from_error(self, error: Exception) -> int | None:
        """Extract an HTTP status code from common provider exception shapes.

        Mirrors :meth:`_headers_from_error`: prefer a top-level ``status_code``
        attribute (OpenAI-style), then fall back to ``error.response.status_code``
        (httpx-style).  Returns ``None`` when no integer status is present.
        """
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            return status

        response = getattr(error, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
            if isinstance(status, int):
                return status
        return None

    def _classify_and_record_error(self, model: str, error: Exception) -> None:
        """Classify a provider error and record it with the right cooldown.

        HTTP status is authoritative: ``401/403/404`` mark the model permanently
        unavailable, ``429`` is a rate limit, ``408`` is a timeout.  Message
        substrings are only a fallback for providers that do not surface a status
        code -- and a bare "not found"/"no access" message is treated as
        *transient*, so a briefly-unavailable model is no longer permanently
        evicted on a substring match (only a real 4xx status evicts it).
        """
        error_str = str(error).lower()
        headers_dict = self._headers_from_error(error)
        if headers_dict is not None:
            self.rate_limit_tracker.update_from_headers(model, headers_dict)

        # Local import: ``core`` eagerly imports ``engine`` which imports
        # ``models``, so a module-level import here would be circular.
        from ..core.errors import ErrorCode, classify_error

        status = self._status_code_from_error(error)
        code, _ = classify_error(error_str)
        if status in _PERMANENT_HTTP_STATUS:
            self.record_failure(model, "permanent", is_permanent=True)
        elif status == _RATE_LIMIT_HTTP_STATUS or code is ErrorCode.RATE_LIMITED:
            self.record_rate_limit(model, headers_dict)
        elif status == _TIMEOUT_HTTP_STATUS or "timeout" in error_str:
            self.record_timeout(model)
        else:
            self.record_failure(model, type(error).__name__)

    async def call_with_fallback(
        self,
        caller: Callable[[str, str], Any],
        prompt: str,
        tier: ModelTier,
        max_retries: int = 3,
    ) -> tuple[str, Any]:
        """Call a model with automatic fallback and production hardening."""
        tried: list[str] = []
        last_error: Exception | None = None

        for _ in range(max_retries):
            model = self.get_model_for_tier(tier)
            if model is None or model in tried:
                break

            tried.append(model)

            if not self._is_model_ready_for_attempt(model):
                continue

            start_mono = time.monotonic()
            try:
                response = await self._execute_call(caller, model, prompt)
                latency = (time.monotonic() - start_mono) * 1000
                self.record_success(model, latency)
                return model, response
            except asyncio.CancelledError:
                raise
            except CircuitResolvedError:
                # A prior probe already resolved the HALF_OPEN circuit before
                # this caller could run its probe.  Skip this model without
                # recording a failure and try the next candidate.
                logger.debug(
                    "Skipping model %r: circuit resolved by a prior probe", model
                )
                continue
            except Exception as e:
                self._classify_and_record_error(model, e)
                last_error = e

        raise RuntimeError(
            f"All models failed. Tried: {tried}. Last error: {last_error}"
        )

    def __repr__(self) -> str:
        healthy = sum(1 for s in self.model_stats.values() if s.is_healthy)
        redis_status = (
            "connected"
            if self._redis_store is not None and self._redis_store.is_connected
            else "none"
        )
        return (
            f"SmartModelRouter(models={len(self.model_stats)}, "
            f"healthy={healthy}, "
            f"stats_file={self.stats_file}, "
            f"redis={redis_status})"
        )


# Global smart router instance
_smart_router: SmartModelRouter | None = None


def get_smart_router(stats_file: Path | None = None) -> SmartModelRouter:
    """Get the global smart router."""
    global _smart_router
    if _smart_router is None:
        _smart_router = SmartModelRouter(stats_file=stats_file)
    return _smart_router


def set_smart_router(router: SmartModelRouter) -> None:
    """Install *router* as the process-wide smart-router singleton.

    All consumers that resolve the router lazily via :func:`get_smart_router`
    (``models.client``, ``agents.base``, ``engine.executor``, the server
    health route, etc.) will use *router* on their next call. This is the
    seam the FastAPI lifespan uses to swap in a Redis-backed router built by
    :meth:`SmartModelRouter.create_with_redis` at startup, replacing the
    default in-process router instantiated on first access.

    Args:
        router: The router instance to install as the global singleton.
    """
    global _smart_router
    _smart_router = router


def reset_smart_router() -> None:
    """Reset the global smart router (for testing)."""
    global _smart_router
    _smart_router = None
