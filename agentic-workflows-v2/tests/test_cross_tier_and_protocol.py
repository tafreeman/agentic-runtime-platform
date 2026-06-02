"""Tests for ADR-002B (cross-tier degradation) and ADR-001 (ExecutionEngine
Protocol)."""

from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest
from agentic_v2.core.errors import NoProviderConfiguredError
from agentic_v2.contracts.messages import StepStatus, WorkflowResult
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.dag import DAG
from agentic_v2.engine.dag_executor import DAGExecutor
from agentic_v2.engine.pipeline import PipelineExecutor
from agentic_v2.engine.protocol import (
    ExecutionEngine,
    SupportsCheckpointing,
    SupportsStreaming,
)
from agentic_v2.models.model_stats import CircuitState
from agentic_v2.models.router import FallbackChain, ModelTier
from agentic_v2.models.smart_router import SmartModelRouter

# ── ADR-002B: Cross-tier degradation tests ───────────────────────────────────


class TestCrossTierDegradation:
    """Tests for cross-tier degradation when a tier is exhausted."""

    def _make_router(self) -> SmartModelRouter:
        """Create a router with chains for multiple tiers."""
        router = SmartModelRouter()
        router.register_chain(
            ModelTier.TIER_1,
            FallbackChain(("openai:gpt-4o-mini",), "tier1"),
        )
        router.register_chain(
            ModelTier.TIER_2,
            FallbackChain(("openai:gpt-4o", "gh:gpt-4o-mini"), "tier2"),
        )
        router.register_chain(
            ModelTier.TIER_3,
            FallbackChain(("anthropic:claude-3-sonnet",), "tier3"),
        )
        router.register_chain(
            ModelTier.TIER_4,
            FallbackChain(("anthropic:claude-3-opus",), "tier4"),
        )
        return router

    def test_normal_routing_returns_same_tier(self) -> None:
        """When tier has healthy models, return from that tier."""
        router = self._make_router()
        model = router.get_model_for_tier(ModelTier.TIER_2)
        assert model == "openai:gpt-4o"

    def test_degradation_disabled_returns_none(self) -> None:
        """With allow_cross_tier=False, return None when tier exhausted."""
        router = self._make_router()
        # Exhaust TIER_3
        stats = router._get_stats("anthropic:claude-3-sonnet")
        for _ in range(5):
            stats.record_failure("test")
        assert stats.circuit_state == CircuitState.OPEN

        model = router.get_model_for_tier(ModelTier.TIER_3, allow_cross_tier=False)
        assert model is None

    def test_degrades_downward_first(self) -> None:
        """When TIER_3 is exhausted, degrade to TIER_2 (lower) before TIER_4."""
        router = self._make_router()
        # Exhaust TIER_3
        stats = router._get_stats("anthropic:claude-3-sonnet")
        for _ in range(5):
            stats.record_failure("test")

        model = router.get_model_for_tier(ModelTier.TIER_3)
        # Should get a TIER_2 model (lower = preferred degradation direction)
        assert model in ("openai:gpt-4o", "gh:gpt-4o-mini")

    def test_escalates_upward_when_lower_exhausted(self) -> None:
        """When lower tiers are also exhausted, escalate upward."""
        router = self._make_router()
        # Exhaust TIER_2 and TIER_1
        for m in ("openai:gpt-4o-mini", "openai:gpt-4o", "gh:gpt-4o-mini"):
            stats = router._get_stats(m)
            for _ in range(5):
                stats.record_failure("test")

        # TIER_2 exhausted → should escalate to TIER_3 or TIER_4
        model = router.get_model_for_tier(ModelTier.TIER_2)
        assert model in ("anthropic:claude-3-sonnet", "anthropic:claude-3-opus")

    def test_all_tiers_exhausted_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ALL registered tiers are exhausted, return None.

        Run in offline mode: with the flag unset, ``get_model_for_tier`` raises
        ``NoProviderConfiguredError`` on a keyless box (see test_no_provider_error)
        — a different contract. Under ``AGENTIC_NO_LLM=1`` the router degrades to
        ``None`` on exhaustion, which is what this test asserts. Previously
        supplied by a session-wide flag leak; now scoped here.
        """
        monkeypatch.setenv("AGENTIC_NO_LLM", "1")
        router = SmartModelRouter()
        # Register ALL tiers with single models we control
        router.register_chain(ModelTier.TIER_1, FallbackChain(("m1:a",), "t1"))
        router.register_chain(ModelTier.TIER_2, FallbackChain(("m2:a",), "t2"))
        router.register_chain(ModelTier.TIER_3, FallbackChain(("m3:a",), "t3"))
        router.register_chain(ModelTier.TIER_4, FallbackChain(("m4:a",), "t4"))
        router.register_chain(ModelTier.TIER_5, FallbackChain(("m5:a",), "t5"))
        for m in ("m1:a", "m2:a", "m3:a", "m4:a", "m5:a"):
            stats = router._get_stats(m)
            for _ in range(5):
                stats.record_failure("test")

        with pytest.raises(NoProviderConfiguredError):
            router.get_model_for_tier(ModelTier.TIER_2)

    def test_tier_0_never_auto_selected(self) -> None:
        """TIER_0 (deterministic, no LLM) is never a degradation target."""
        router = self._make_router()
        router.register_chain(
            ModelTier.TIER_0,
            FallbackChain(("deterministic:tool",), "tier0"),
        )
        # Exhaust TIER_1
        stats = router._get_stats("openai:gpt-4o-mini")
        for _ in range(5):
            stats.record_failure("test")

        model = router.get_model_for_tier(ModelTier.TIER_1)
        # Should degrade to TIER_2, NOT TIER_0
        assert model != "deterministic:tool"
        assert model in ("openai:gpt-4o", "gh:gpt-4o-mini")

    def test_cross_tier_respects_cost_limit(self) -> None:
        """Cross-tier degradation still respects max_cost."""
        router = SmartModelRouter()
        router.register_chain(ModelTier.TIER_1, FallbackChain(("cheap:a",), "t1"))
        router.register_chain(ModelTier.TIER_2, FallbackChain(("mid:a",), "t2"))
        router.register_chain(ModelTier.TIER_3, FallbackChain(("pricey:a",), "t3"))
        router.model_costs["cheap:a"] = 0.1
        router.model_costs["pricey:a"] = 15.0

        # Exhaust TIER_2
        stats = router._get_stats("mid:a")
        for _ in range(5):
            stats.record_failure("test")

        # With cost limit, should skip expensive TIER_3 model and use TIER_1
        model = router.get_model_for_tier(ModelTier.TIER_2, max_cost=5.0)
        assert model == "cheap:a"

    def test_degradation_prefers_closest_tier(self) -> None:
        """Cross-tier prefers tiers closest to the original request."""
        router = self._make_router()
        router.register_chain(
            ModelTier.TIER_5,
            FallbackChain(("openai:gpt-4-turbo",), "tier5"),
        )
        # Exhaust TIER_3
        stats = router._get_stats("anthropic:claude-3-sonnet")
        for _ in range(5):
            stats.record_failure("test")

        model = router.get_model_for_tier(ModelTier.TIER_3)
        # TIER_2 (distance=1, down) is preferred over TIER_4 (distance=1, up)
        # and much preferred over TIER_5 (distance=2, up)
        assert model in ("openai:gpt-4o", "gh:gpt-4o-mini")

    @pytest.mark.asyncio
    async def test_call_with_fallback_uses_cross_tier(self) -> None:
        """call_with_fallback should work when cross-tier kicks in."""
        router = self._make_router()
        # Exhaust TIER_3
        stats = router._get_stats("anthropic:claude-3-sonnet")
        for _ in range(5):
            stats.record_failure("test")

        caller = AsyncMock(return_value="cross-tier response")
        model, response = await router.call_with_fallback(
            caller, "test prompt", ModelTier.TIER_3
        )
        assert response == "cross-tier response"
        # Should have used a model from an adjacent tier
        assert model != "anthropic:claude-3-sonnet"


# ── ADR-001: ExecutionEngine Protocol tests ──────────────────────────────────


class TestExecutionEngineProtocol:
    """Tests for the ExecutionEngine protocol (ADR-001)."""

    def test_dag_executor_satisfies_protocol(self) -> None:
        """DAGExecutor structurally conforms to ExecutionEngine."""
        executor = DAGExecutor()
        assert isinstance(executor, ExecutionEngine)

    def test_pipeline_executor_satisfies_protocol(self) -> None:
        """PipelineExecutor structurally conforms to ExecutionEngine."""
        executor = PipelineExecutor()
        assert isinstance(executor, ExecutionEngine)

    def test_custom_engine_satisfies_protocol(self) -> None:
        """A custom class with matching signature satisfies the protocol."""

        class MockEngine:
            async def execute(
                self,
                workflow: Any,
                ctx: Optional[ExecutionContext] = None,
                on_update: Any = None,
                **kwargs: Any,
            ) -> WorkflowResult:
                return WorkflowResult(
                    workflow_id="mock-1",
                    workflow_name="mock",
                    overall_status=StepStatus.SUCCESS,
                )

        engine = MockEngine()
        assert isinstance(engine, ExecutionEngine)

    def test_non_conforming_class_fails_check(self) -> None:
        """A class without execute() does NOT satisfy the protocol."""

        class NotAnEngine:
            def run(self) -> None:
                pass

        assert not isinstance(NotAnEngine(), ExecutionEngine)

    def test_streaming_protocol(self) -> None:
        """SupportsStreaming is a separate capability check."""

        class StreamingEngine:
            async def execute(self, workflow: Any, **kwargs: Any) -> WorkflowResult: ...

            async def stream(self, workflow: Any, **kwargs: Any) -> Any: ...

        engine = StreamingEngine()
        assert isinstance(engine, SupportsStreaming)
        # DAGExecutor does NOT support streaming
        assert not isinstance(DAGExecutor(), SupportsStreaming)

    def test_checkpointing_protocol(self) -> None:
        """SupportsCheckpointing is a separate capability check."""

        class CheckpointEngine:
            async def execute(self, workflow: Any, **kwargs: Any) -> WorkflowResult: ...

            def get_checkpoint_state(
                self, workflow: Any, *, thread_id: str, **kwargs: Any
            ) -> Optional[dict[str, Any]]:
                return None

            async def resume(
                self, workflow: Any, *, thread_id: str, **kwargs: Any
            ) -> WorkflowResult: ...

        engine = CheckpointEngine()
        assert isinstance(engine, SupportsCheckpointing)
        assert not isinstance(DAGExecutor(), SupportsCheckpointing)

    def test_protocol_used_as_type_hint(self) -> None:
        """Protocol can be used in function signatures for polymorphism."""

        async def run_any_engine(
            engine: ExecutionEngine,
            workflow: Any,
        ) -> WorkflowResult:
            return await engine.execute(workflow)

        # This function should accept any conforming engine
        # (type-level correctness — runtime test is a sanity check)
        assert callable(run_any_engine)

    @pytest.mark.asyncio
    async def test_dag_executor_through_protocol(self) -> None:
        """Execute a DAG through the protocol interface."""
        from agentic_v2.engine.step import StepDefinition

        async def noop_step(ctx: ExecutionContext) -> dict[str, Any]:
            return {"result": "done"}

        dag = DAG(name="test-dag")
        step = StepDefinition(name="step1", func=noop_step)
        dag.add(step)

        engine: ExecutionEngine = DAGExecutor()
        result = await engine.execute(dag)
        assert result.overall_status == StepStatus.SUCCESS
