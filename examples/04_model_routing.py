"""04 — Configure and use SmartModelRouter with tier-based model selection.

Demonstrates:
    - Creating a :class:`ModelRouter` with default fallback chains.
    - Registering custom :class:`FallbackChain` for a tier.
    - Using the :class:`SmartModelRouter` with health tracking:
        - Recording successes and failures.
        - Observing circuit breaker state changes.
        - Getting health-weighted model selection.
        - Using :meth:`call_with_fallback` for automatic failover.
    - Scoped routing for temporary overrides.
    - Inspecting stats summaries.

No API keys are required.  All routing is simulated with in-memory state.

Usage:
    python examples/04_model_routing.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from agentic_v2.models import (
    DEFAULT_CHAINS,
    FallbackChain,
    ModelRouter,
    ModelTier,
    SmartModelRouter,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def demo_basic_routing() -> None:
    """Show basic ModelRouter with default chains."""
    print("=" * 60)
    print("1. Basic ModelRouter — Default Chains")
    print("=" * 60)

    router = ModelRouter()

    # Inspect the default chains for each tier
    for tier in [
        ModelTier.TIER_1,
        ModelTier.TIER_2,
        ModelTier.TIER_3,
        ModelTier.TIER_4,
    ]:
        chain = router.get_chain(tier)
        models = list(chain)
        print(f"\n  {tier.name} ({chain.name}):")
        for model in models:
            print(f"    - {model}")

    # Get the first available model for TIER_2
    # Without a health checker, all models are assumed available
    model = router.get_model_for_tier(ModelTier.TIER_2)
    print(f"\n  Selected for TIER_2: {model}")


def demo_custom_chains() -> None:
    """Show registering custom fallback chains."""
    print("\n" + "=" * 60)
    print("2. Custom Fallback Chains")
    print("=" * 60)

    router = ModelRouter()

    # Build a custom chain using the fluent DSL
    custom_chain = (
        FallbackChain.build("my-tier2")
        .add("ollama:phi4")  # Local model first (free)
        .add("ollama:llama3.2:latest")  # Another local option
        .add("gh:openai/gpt-4o-mini")  # GitHub Models fallback
        .done()
    )

    router.register_chain(ModelTier.TIER_2, custom_chain)
    print(f"  Registered custom chain for TIER_2: {list(custom_chain)}")

    # Now TIER_2 uses the custom chain
    model = router.get_model_for_tier(ModelTier.TIER_2)
    print(f"  Selected model: {model}")

    # Mark the first model as unavailable to trigger fallback
    router.mark_unavailable("ollama:phi4")
    model = router.get_model_for_tier(ModelTier.TIER_2)
    print(f"  After phi4 unavailable: {model}")


def demo_scoped_routing() -> None:
    """Show temporary scoped routing overrides."""
    print("\n" + "=" * 60)
    print("3. Scoped Routing (Temporary Overrides)")
    print("=" * 60)

    router = ModelRouter()

    # Normal selection
    normal_model = router.get_model_for_tier(ModelTier.TIER_2)
    print(f"  Normal TIER_2 model: {normal_model}")

    # Scoped override — restrict to only local models for this operation
    with router.scoped(ModelTier.TIER_2, ["ollama:phi4", "ollama:mistral"]) as scoped:
        scoped_model = scoped.get_model()
        all_available = scoped.get_all_available()
        print(f"  Scoped TIER_2 model: {scoped_model}")
        print(f"  All available in scope: {all_available}")

    # After exiting scope, original chain is restored
    restored_model = router.get_model_for_tier(ModelTier.TIER_2)
    print(f"  Restored TIER_2 model: {restored_model}")


def demo_smart_routing() -> None:
    """Show SmartModelRouter with health tracking and circuit breakers."""
    print("\n" + "=" * 60)
    print("4. SmartModelRouter — Health Tracking & Circuit Breakers")
    print("=" * 60)

    # Create a smart router (no persistence file — in-memory only)
    router = SmartModelRouter()

    # Simulate successful calls to build health scores
    print("\n  Simulating model performance...")
    router.record_success("gemini:gemini-2.0-flash", latency_ms=120.0)
    router.record_success("gemini:gemini-2.0-flash", latency_ms=150.0)
    router.record_success("gemini:gemini-2.0-flash", latency_ms=130.0)
    print("    gemini:gemini-2.0-flash — 3 successes (~130ms avg)")

    router.record_success("gh:openai/gpt-4o-mini", latency_ms=450.0)
    router.record_success("gh:openai/gpt-4o-mini", latency_ms=500.0)
    print("    gh:openai/gpt-4o-mini — 2 successes (~475ms avg)")

    # Simulate failures for one model
    router.record_failure("openai:gpt-4o-mini", error_type="timeout")
    router.record_failure("openai:gpt-4o-mini", error_type="timeout")
    print("    openai:gpt-4o-mini — 2 failures (timeout)")

    # Health-weighted selection prefers the healthy, fast model
    selected = router.get_model_for_tier(ModelTier.TIER_2, prefer_healthy=True)
    print(f"\n  Health-weighted selection for TIER_2: {selected}")

    # Check model availability prediction
    for model_name in ["gemini:gemini-2.0-flash", "openai:gpt-4o-mini"]:
        prediction = router.predict_availability(model_name)
        print(f"\n  Availability prediction for {model_name}:")
        print(f"    Available: {prediction['available']}")
        print(f"    Confidence: {prediction['confidence']:.1%}")
        print(f"    Reason: {prediction['reason']}")

    # Inspect health-scored fallback chain
    chain_with_health = router.get_fallback_chain_with_health(ModelTier.TIER_2)
    print("\n  TIER_2 chain with health scores:")
    for model_name, health_score in chain_with_health:
        print(f"    {model_name}: health={health_score:.2f}")


def demo_stats_summary() -> None:
    """Show the stats summary API."""
    print("\n" + "=" * 60)
    print("5. Stats Summary")
    print("=" * 60)

    router = SmartModelRouter()

    # Build some stats
    router.record_success("gemini:gemini-2.0-flash", latency_ms=100.0)
    router.record_success("gh:openai/gpt-4o-mini", latency_ms=400.0)
    router.record_failure("openai:gpt-4o-mini", error_type="rate_limit")

    summary = router.get_stats_summary()
    print(f"  Total models tracked: {summary['total_models']}")
    print(f"  Healthy models: {summary['healthy_models']}")
    for model_name, stats in summary["models"].items():
        print(f"\n  {model_name}:")
        print(f"    Success rate: {stats.get('recent_success_rate', 0):.1%}")
        print(f"    Circuit state: {stats.get('circuit_state', 'N/A')}")


async def demo_call_with_fallback() -> None:
    """Show automatic failover with call_with_fallback."""
    print("\n" + "=" * 60)
    print("6. Automatic Failover with call_with_fallback")
    print("=" * 60)

    router = SmartModelRouter()

    # Define a mock caller that fails for certain models
    call_count = 0

    async def mock_caller(model: str, prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        # Simulate: first model in TIER_2 chain fails, second succeeds
        if "gemini" in model:
            raise RuntimeError("Simulated Gemini API timeout")
        return f"Response from {model}: processed '{prompt[:30]}...'"

    try:
        model_used, response = await router.call_with_fallback(
            caller=mock_caller,
            prompt="Explain the observer pattern in Python",
            tier=ModelTier.TIER_2,
            max_retries=3,
        )
        print(f"  Model used: {model_used}")
        print(f"  Response: {response}")
        print(f"  Total calls attempted: {call_count}")
    except RuntimeError as exc:
        print(f"  All models failed: {exc}")


def main() -> None:
    """Run all routing demonstrations."""
    demo_basic_routing()
    demo_custom_chains()
    demo_scoped_routing()
    demo_smart_routing()
    demo_stats_summary()
    asyncio.run(demo_call_with_fallback())

    print("\n" + "=" * 60)
    print("All routing demos complete.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
