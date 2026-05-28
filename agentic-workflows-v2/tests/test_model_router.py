"""Tests for model routing and smart routing."""

import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from agentic_v2.models import (  # Stats; Router; Smart router; Client
    CircuitState,
    CooldownConfig,
    FallbackChain,
    LLMClientWrapper,
    ModelRouter,
    ModelStats,
    ModelTier,
    SmartModelRouter,
    TokenBudget,
    get_client,
    get_router,
    reset_client,
    reset_router,
    reset_smart_router,
)

# ============================================================================
# ModelStats Tests
# ============================================================================


class TestModelStats:
    """Tests for ModelStats."""

    def test_create_stats(self):
        """Test creating model stats."""
        stats = ModelStats(model_id="ollama:phi4")

        assert stats.model_id == "ollama:phi4"
        assert stats.success_count == 0
        assert stats.total_calls == 0
        assert stats.success_rate == 1.0  # Assume good until proven
        assert stats.is_healthy

    def test_record_success(self):
        """Test recording successful calls."""
        stats = ModelStats(model_id="test")

        stats.record_success(latency_ms=100)
        stats.record_success(latency_ms=200)

        assert stats.success_count == 2
        assert stats.total_calls == 2
        assert stats.success_rate == 1.0
        assert stats.avg_latency_ms > 0
        assert stats.last_success is not None

    def test_record_failure(self):
        """Test recording failed calls."""
        stats = ModelStats(model_id="test")

        stats.record_success(latency_ms=100)
        stats.record_failure("timeout")

        assert stats.failure_count == 1
        assert stats.success_rate == 0.5
        assert stats.last_failure is not None

    def test_ema_latency(self):
        """Test EMA latency calculation."""
        stats = ModelStats(model_id="test")

        # First call sets baseline
        stats.record_success(latency_ms=100)
        assert stats.avg_latency_ms == 100

        # Subsequent calls smooth the average
        stats.record_success(latency_ms=200)
        # EMA with alpha=0.2: 0.2*200 + 0.8*100 = 120
        assert stats.avg_latency_ms == pytest.approx(120, rel=0.1)

    def test_recent_success_rate(self):
        """Test sliding window success rate."""
        stats = ModelStats(model_id="test", _window_size=5)

        # 3 successes, 2 failures
        stats.record_success(latency_ms=100)
        stats.record_success(latency_ms=100)
        stats.record_success(latency_ms=100)
        stats.record_failure("error")
        stats.record_failure("error")

        assert stats.recent_success_rate == 0.6

    def test_percentiles(self):
        """Test latency percentile calculation."""
        stats = ModelStats(model_id="test")

        # Add samples with known distribution
        for i in range(1, 101):
            stats.record_success(latency_ms=float(i))

        percentiles = stats.percentiles
        assert percentiles.p50 == pytest.approx(50, rel=0.1)
        assert percentiles.p95 == pytest.approx(95, rel=0.1)

    def test_circuit_breaker_opens(self):
        """Test circuit breaker opens after failures."""
        stats = ModelStats(model_id="test", _failure_threshold=3)

        assert stats.circuit_state == CircuitState.CLOSED

        # Trigger failures
        stats.record_failure("error")
        stats.record_failure("error")
        stats.record_failure("error")

        assert stats.circuit_state == CircuitState.OPEN
        assert not stats.check_circuit()

    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after timeout."""
        stats = ModelStats(
            model_id="test", _failure_threshold=2, _recovery_timeout_seconds=1
        )

        # Open circuit
        stats.record_failure("error")
        stats.record_failure("error")
        assert stats.circuit_state == CircuitState.OPEN

        # Simulate time passing (both wall clock and monotonic)
        stats._last_failure_time = datetime.now(timezone.utc) - timedelta(seconds=2)
        stats._last_failure_mono = time.monotonic() - 2.0

        # Should allow test request
        assert stats.check_circuit()
        assert stats.circuit_state == CircuitState.HALF_OPEN

    def test_cooldown(self):
        """Test cooldown period."""
        stats = ModelStats(model_id="test")

        assert not stats.is_in_cooldown

        stats.set_cooldown(seconds=60)
        assert stats.is_in_cooldown
        assert stats.cooldown_remaining_seconds > 0

        stats.clear_cooldown()
        assert not stats.is_in_cooldown

    def test_rate_limit_tracking(self):
        """Test rate limit specific tracking."""
        stats = ModelStats(model_id="test")

        stats.record_rate_limit()

        assert stats.rate_limit_count == 1
        assert stats.failure_count == 1
        assert stats.is_in_cooldown  # Rate limits apply cooldown

    def test_serialization(self):
        """Test stats serialization."""
        stats = ModelStats(model_id="test")
        stats.record_success(latency_ms=100)
        stats.record_failure("error")

        data = stats.to_dict()
        assert data["model_id"] == "test"
        assert data["success_count"] == 1
        assert data["failure_count"] == 1

        # Round-trip
        restored = ModelStats.from_dict(data)
        assert restored.model_id == stats.model_id
        assert restored.success_count == stats.success_count


# ============================================================================
# FallbackChain Tests
# ============================================================================


class TestFallbackChain:
    """Tests for FallbackChain."""

    def test_create_chain(self):
        """Test creating a fallback chain."""
        chain = FallbackChain(("model1", "model2", "model3"), "test-chain")

        assert len(chain) == 3
        assert chain[0] == "model1"
        assert list(chain) == ["model1", "model2", "model3"]

    def test_chain_builder(self):
        """Test fluent chain builder."""
        chain = (
            FallbackChain.build("custom")
            .add("ollama:phi4")
            .add("gh:gpt-4o-mini")
            .add("gh:gpt-4o")
            .done()
        )

        assert chain.name == "custom"
        assert len(chain) == 3
        assert chain[0] == "ollama:phi4"

    def test_empty_chain_rejected(self):
        """Test that empty chain raises error."""
        with pytest.raises(ValueError):
            FallbackChain(tuple(), "empty")


# ============================================================================
# ModelRouter Tests
# ============================================================================


class TestModelRouter:
    """Tests for ModelRouter."""

    def setup_method(self):
        """Reset global router before each test."""
        reset_router()

    def test_default_chains(self):
        """Test default chains exist for each tier."""
        router = ModelRouter()

        for tier in [ModelTier.TIER_1, ModelTier.TIER_2, ModelTier.TIER_3]:
            chain = router.get_chain(tier)
            assert len(chain) > 0

    def test_custom_chain_registration(self):
        """Test registering custom chains."""
        router = ModelRouter()

        custom = FallbackChain(("custom:model1", "custom:model2"), "custom")
        router.register_chain(ModelTier.TIER_2, custom)

        chain = router.get_chain(ModelTier.TIER_2)
        assert chain.name == "custom"
        assert chain[0] == "custom:model1"

    def test_model_availability(self):
        """Test model availability tracking."""
        router = ModelRouter()

        router.mark_available("test:model")
        assert router.is_model_available("test:model")

        router.mark_unavailable("test:model")
        assert not router.is_model_available("test:model")

    def test_health_checker(self):
        """Test custom health checker."""
        router = ModelRouter()

        # Set up health checker that says only "good:model" is available
        router.set_health_checker(lambda m: m.startswith("good:"))

        assert router.is_model_available("good:model")
        assert not router.is_model_available("bad:model")

    def test_get_model_for_tier(self):
        """Test getting first available model for tier."""
        router = ModelRouter()

        # Mark all models unavailable except one
        router.register_chain(
            ModelTier.TIER_2, FallbackChain(("model1", "model2", "model3"), "test")
        )
        router.mark_unavailable("model1")
        router.mark_unavailable("model2")
        router.mark_available("model3")

        model = router.get_model_for_tier(ModelTier.TIER_2)
        assert model == "model3"

    def test_get_fallback_for_model(self):
        """Test getting next model in chain."""
        router = ModelRouter()

        router.register_chain(
            ModelTier.TIER_2, FallbackChain(("model1", "model2", "model3"), "test")
        )

        # All available by default
        next_model = router.get_fallback_for_model("model1", ModelTier.TIER_2)
        assert next_model == "model2"

        next_model = router.get_fallback_for_model("model2", ModelTier.TIER_2)
        assert next_model == "model3"

        # No more fallbacks
        next_model = router.get_fallback_for_model("model3", ModelTier.TIER_2)
        assert next_model is None

    def test_scoped_routing(self):
        """Test scoped routing context manager."""
        router = ModelRouter()

        # Get original chain
        original_chain = router.get_chain(ModelTier.TIER_2)

        # Use scoped routing
        with router.scoped(ModelTier.TIER_2, ["scoped:model1"]) as scoped:
            chain = router.get_chain(ModelTier.TIER_2)
            assert chain[0] == "scoped:model1"

        # Chain restored after scope
        restored_chain = router.get_chain(ModelTier.TIER_2)
        assert restored_chain[0] == original_chain[0]

    def test_global_router(self):
        """Test global router singleton."""
        router1 = get_router()
        router2 = get_router()

        assert router1 is router2


# ============================================================================
# SmartModelRouter Tests
# ============================================================================


class TestSmartModelRouter:
    """Tests for SmartModelRouter."""

    def setup_method(self):
        """Reset global router before each test."""
        reset_smart_router()

    def test_record_success(self):
        """Test recording success updates stats."""
        router = SmartModelRouter()

        router.record_success("test:model", latency_ms=100)

        stats = router.model_stats["test:model"]
        assert stats.success_count == 1
        assert stats.avg_latency_ms == 100

    def test_record_failure_with_cooldown(self):
        """Test recording failure applies cooldown."""
        router = SmartModelRouter()

        router.record_failure("test:model", error_type="timeout")

        stats = router.model_stats["test:model"]
        assert stats.failure_count == 1
        assert stats.is_in_cooldown

    def test_adaptive_cooldown(self):
        """Test cooldown scales with failures."""
        router = SmartModelRouter(
            cooldown_config=CooldownConfig(
                base_failure_cooldown_seconds=10, consecutive_failure_multiplier=2.0
            )
        )

        # First failure - base cooldown
        router.record_failure("test:model")
        stats = router.model_stats["test:model"]
        first_cooldown = stats.cooldown_remaining_seconds

        # Second failure - scaled cooldown
        router.record_failure("test:model")
        second_cooldown = stats.cooldown_remaining_seconds

        assert second_cooldown > first_cooldown

    def test_health_weighted_selection(self):
        """Test selection prefers healthy models."""
        router = SmartModelRouter()

        router.register_chain(
            ModelTier.TIER_2, FallbackChain(("model1", "model2"), "test")
        )

        # Model1 has failures, model2 is perfect
        router.record_failure("model1")
        router.record_failure("model1")
        router.record_success("model2", latency_ms=100)
        router.record_success("model2", latency_ms=100)

        # Clear cooldown so model1 is available but unhealthy
        router.model_stats["model1"].clear_cooldown()

        # Should prefer model2
        model = router.get_model_for_tier(ModelTier.TIER_2, prefer_healthy=True)
        assert model == "model2"

    def test_cost_aware_routing(self):
        """Test cost-aware model selection."""
        router = SmartModelRouter()
        router.model_costs = {"cheap:model": 0.1, "expensive:model": 10.0}

        router.register_chain(
            ModelTier.TIER_2, FallbackChain(("expensive:model", "cheap:model"), "test")
        )

        # With cost limit, should skip expensive model
        model = router.get_model_for_tier(ModelTier.TIER_2, max_cost=1.0)
        assert model == "cheap:model"

    def test_predict_availability(self):
        """Test availability prediction."""
        router = SmartModelRouter()

        # New model - should be healthy
        pred = router.predict_availability("new:model")
        assert pred["available"]
        assert pred["confidence"] > 0.5

        # Model with many rate limits
        router.model_stats["limited:model"] = ModelStats(model_id="limited:model")
        router.model_stats["limited:model"].rate_limit_count = 10

        pred = router.predict_availability("limited:model")
        assert pred["reason"] == "rate_limit_history"

    def test_stats_persistence(self):
        """Test stats persistence to file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            stats_path = Path(f.name)

        try:
            # Create router and record some stats
            router = SmartModelRouter(stats_file=stats_path)
            router.record_success("test:model", latency_ms=100)
            router.record_failure("test:model2")

            # File should be written
            assert stats_path.exists()

            # Create new router - should load stats
            router2 = SmartModelRouter(stats_file=stats_path)
            assert "test:model" in router2.model_stats
            assert router2.model_stats["test:model"].success_count == 1
        finally:
            stats_path.unlink(missing_ok=True)

    def test_fallback_chain_with_health(self):
        """Test getting chain with health scores."""
        router = SmartModelRouter()

        router.register_chain(
            ModelTier.TIER_2, FallbackChain(("model1", "model2", "model3"), "test")
        )

        # Set different health levels - all models must have stats
        for _ in range(3):
            router.record_success("model1", latency_ms=100)
            router.record_failure("model1")  # 50% success
        for _ in range(5):
            router.record_success("model2", latency_ms=100)
            router.record_failure("model2")  # 50% success
        for _ in range(10):
            router.record_success("model3", latency_ms=100)  # 100% success

        # Clear cooldowns and circuit breakers so all are available
        for model in ["model1", "model2", "model3"]:
            stats = router.model_stats[model]
            stats.clear_cooldown()
            # Reset circuit breaker to CLOSED
            stats.circuit_state = CircuitState.CLOSED
            stats._consecutive_failures = 0

        chain_with_health = router.get_fallback_chain_with_health(ModelTier.TIER_2)

        # model3 should be first (100% success rate)
        assert len(chain_with_health) >= 1
        # model3 has highest success rate (1.0)
        model3_entry = next((m for m in chain_with_health if m[0] == "model3"), None)
        assert model3_entry is not None
        assert model3_entry[1] == 1.0  # 100% success rate
        assert chain_with_health[0][1] == 1.0  # 100% success rate


# ============================================================================
# TokenBudget Tests
# ============================================================================


class TestTokenBudget:
    """Tests for TokenBudget."""

    def test_basic_budget(self):
        """Test basic budget operations."""
        budget = TokenBudget(max_tokens=1000)

        assert budget.remaining == 1000
        assert budget.percentage_used == 0.0

        assert budget.consume(300)
        assert budget.remaining == 700
        assert budget.percentage_used == 30.0

    def test_budget_exceeded(self):
        """Test budget consumption rejection."""
        budget = TokenBudget(max_tokens=100)

        assert budget.consume(50)
        assert not budget.consume(100)  # Would exceed
        assert budget.remaining == 50  # Unchanged

    def test_can_afford(self):
        """Test affordability check."""
        budget = TokenBudget(max_tokens=100, used_tokens=80)

        assert budget.can_afford(20)
        assert not budget.can_afford(21)


# ============================================================================
# LLMClientWrapper Tests
# ============================================================================


class TestLLMClientWrapper:
    """Tests for LLMClientWrapper."""

    def setup_method(self):
        """Reset global client before each test."""
        reset_client()
        reset_smart_router()

    def test_create_client(self):
        """Test creating client."""
        client = LLMClientWrapper()

        assert client.backend is None
        assert client.enable_cache
        assert client.budget is None

    def test_budget_setting(self):
        """Test setting token budget."""
        client = LLMClientWrapper()

        client.set_budget(max_tokens=10000)

        assert client.budget is not None
        assert client.budget.max_tokens == 10000

    def test_cache_key_generation(self):
        """Test cache key uniqueness."""
        client = LLMClientWrapper()

        key1 = client._cache_key("prompt1", ModelTier.TIER_2)
        key2 = client._cache_key("prompt2", ModelTier.TIER_2)
        key3 = client._cache_key("prompt1", ModelTier.TIER_3)

        assert key1 != key2  # Different prompts
        assert key1 != key3  # Different tiers

    def test_cache_operations(self):
        """Test cache get/set."""
        client = LLMClientWrapper()

        key = "test-key"
        client._set_cached(key, "response", "model", 100)

        cached = client._get_cached(key)
        assert cached is not None
        assert cached.response == "response"
        assert cached.model == "model"

    def test_cache_clearing(self):
        """Test cache clearing."""
        client = LLMClientWrapper()

        client._set_cached("key1", "r1", "m1", 10)
        client._set_cached("key2", "r2", "m2", 20)

        count = client.clear_cache()
        assert count == 2
        assert len(client.cache) == 0

    def test_global_client(self):
        """Test global client singleton."""
        client1 = get_client()
        client2 = get_client()

        assert client1 is client2

    def test_stats_reporting(self):
        """Test stats reporting."""
        client = LLMClientWrapper()
        client.set_budget(1000)
        client._set_cached("k", "r", "m", 50)

        stats = client.get_stats()

        assert stats["cache_entries"] == 1
        assert stats["budget"]["max"] == 1000
        assert "router_stats" in stats
