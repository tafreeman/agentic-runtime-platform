"""Tests for the DAGExecutor workflow-level timeout watchdog.

Covers:
- A hung step is cancelled when ``timeout`` fires.
- The returned WorkflowResult reflects the failure (status + error message).
- No asyncio tasks are leaked after timeout.
- ``timeout=None`` (default) preserves the original happy-path behaviour.
- Timeout accepted via ``**kwargs`` dispatch path.
- Downstream steps are cascade-skipped on timeout.
"""

from __future__ import annotations

import asyncio
import warnings
from typing import Any

import pytest

from agentic_v2.contracts import StepStatus, WorkflowResult
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.dag import DAG
from agentic_v2.engine.dag_executor import DAGExecutor
from agentic_v2.engine.step import StepDefinition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dag(name: str = "test-dag") -> DAG:
    """Return an empty DAG ready for step registration."""
    return DAG(name=name)


def _instant_step(ctx: ExecutionContext) -> dict[str, Any]:
    """Synchronous instant step — wrapped in a coroutine below."""
    return {"done": True}


async def instant_step(ctx: ExecutionContext) -> dict[str, Any]:
    """A step that completes immediately without sleeping."""
    return {"done": True}


async def hung_step(ctx: ExecutionContext) -> dict[str, Any]:
    """A step that sleeps indefinitely — simulates a hung LLM call."""
    await asyncio.sleep(10)
    return {"done": True}  # pragma: no cover


async def fast_step(ctx: ExecutionContext) -> dict[str, Any]:
    """A step that completes very quickly (< 50 ms)."""
    await asyncio.sleep(0.01)
    return {"value": 42}


async def raising_step(ctx: ExecutionContext) -> dict[str, Any]:
    """A step that raises — drives the non-timeout failure path."""
    raise RuntimeError("step exploded")


# ---------------------------------------------------------------------------
# Core timeout tests
# ---------------------------------------------------------------------------


class TestDAGExecutorTimeout:
    """Workflow-level timeout watchdog for DAGExecutor."""

    async def test_timeout_cancels_hung_step(self) -> None:
        """A step sleeping for 10 s is cancelled when timeout=0.1 s fires."""
        dag = _make_dag("hung-workflow")
        dag.add(StepDefinition(name="hung", func=hung_step))

        executor = DAGExecutor()
        result = await executor.execute(dag, timeout=0.1)

        assert isinstance(result, WorkflowResult)
        assert result.overall_status == StepStatus.FAILED

    async def test_timeout_result_has_error_message(self) -> None:
        """The failed StepResult for the timed-out step carries a clear error."""
        dag = _make_dag("hung-workflow-err")
        dag.add(StepDefinition(name="hung", func=hung_step))

        executor = DAGExecutor()
        result = await executor.execute(dag, timeout=0.1)

        # The hung step must appear in results as FAILED
        assert len(result.steps) >= 1
        failed = [s for s in result.steps if s.status == StepStatus.FAILED]
        assert failed, "Expected at least one FAILED step after timeout"
        # Error message must mention timeout
        assert failed[0].error is not None
        assert "timeout" in failed[0].error.lower() or "exceeded" in failed[0].error.lower()

    async def test_timeout_result_metadata(self) -> None:
        """WorkflowResult.metadata contains timeout bookkeeping fields."""
        dag = _make_dag("hung-metadata")
        dag.add(StepDefinition(name="hung", func=hung_step))

        executor = DAGExecutor()
        result = await executor.execute(dag, timeout=0.1)

        assert result.metadata.get("timeout_exceeded") is True
        assert result.metadata.get("timeout_seconds") == pytest.approx(0.1)

    async def test_timeout_no_leaked_tasks(self) -> None:
        """No asyncio tasks are pending after a timeout (no leak warnings)."""
        dag = _make_dag("no-leak")
        dag.add(StepDefinition(name="hung", func=hung_step))

        executor = DAGExecutor()
        # Capture ResourceWarnings that asyncio emits for destroyed pending tasks
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = await executor.execute(dag, timeout=0.1)
            # Give the event loop one tick to finalize any pending task cleanup
            await asyncio.sleep(0)

        task_warnings = [
            w
            for w in caught
            if issubclass(w.category, (ResourceWarning, RuntimeWarning))
            and "pending" in str(w.message).lower()
        ]
        assert task_warnings == [], (
            f"Leaked asyncio tasks detected: {[str(w.message) for w in task_warnings]}"
        )
        # Also verify all current tasks (excluding our own) are not pending
        current_tasks = asyncio.all_tasks()
        # The only task should be the test itself (or none if we're in sync ctx)
        pending_names = [t.get_name() for t in current_tasks if not t.done()]
        dag_task_names = [t for t in pending_names if t in dag.steps]
        assert dag_task_names == [], f"DAG step tasks still pending: {dag_task_names}"

        assert result.overall_status == StepStatus.FAILED

    async def test_timeout_cascade_skips_downstream(self) -> None:
        """Steps that depend on the timed-out step are cascade-skipped."""
        dag = _make_dag("cascade-timeout")
        dag.add(StepDefinition(name="hung", func=hung_step))
        downstream = StepDefinition(name="downstream", func=instant_step)
        downstream.depends_on = ["hung"]
        dag.add(downstream)

        executor = DAGExecutor()
        result = await executor.execute(dag, timeout=0.1)

        assert result.overall_status == StepStatus.FAILED
        step_map = {s.step_name: s for s in result.steps}
        # downstream must be skipped (not left out of results entirely)
        assert "downstream" in step_map
        assert step_map["downstream"].status == StepStatus.SKIPPED

    async def test_timeout_kwargs_dispatch(self) -> None:
        """timeout accepted via **kwargs so server-layer dispatch works unchanged."""
        dag = _make_dag("kwargs-timeout")
        dag.add(StepDefinition(name="hung", func=hung_step))

        executor = DAGExecutor()
        # Pass timeout through the **kwargs path (server layer pattern)
        result = await executor.execute(dag, **{"timeout": 0.1})

        assert result.overall_status == StepStatus.FAILED
        assert result.metadata.get("timeout_exceeded") is True

    @pytest.mark.slow
    async def test_timeout_fires_within_reasonable_wall_time(self) -> None:
        """The workflow completes close to the timeout boundary, not 10 s later."""
        import time

        dag = _make_dag("wall-time")
        dag.add(StepDefinition(name="hung", func=hung_step))

        executor = DAGExecutor()
        start = time.monotonic()
        result = await executor.execute(dag, timeout=0.2)
        elapsed = time.monotonic() - start

        assert result.overall_status == StepStatus.FAILED
        # Should finish well under 1 second (hung_step sleeps 10 s)
        assert elapsed < 1.0, f"Timeout took {elapsed:.2f}s, expected < 1.0s"


# ---------------------------------------------------------------------------
# Happy-path regression tests (timeout=None should not change behaviour)
# ---------------------------------------------------------------------------


class TestDAGExecutorTimeoutNone:
    """Ensure timeout=None preserves all existing happy-path behaviour."""

    async def test_no_timeout_single_step_success(self) -> None:
        """Single-step DAG succeeds normally when no timeout is set."""
        dag = _make_dag("happy-single")
        dag.add(StepDefinition(name="compute", func=instant_step))

        executor = DAGExecutor()
        result = await executor.execute(dag)

        assert isinstance(result, WorkflowResult)
        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 1
        assert result.steps[0].step_name == "compute"
        assert result.steps[0].status == StepStatus.SUCCESS

    async def test_no_timeout_sequential_steps_success(self) -> None:
        """Two-step sequential DAG succeeds normally when no timeout is set."""
        dag = _make_dag("happy-sequential")
        dag.add(StepDefinition(name="a", func=instant_step))
        step_b = StepDefinition(name="b", func=instant_step)
        step_b.depends_on = ["a"]
        dag.add(step_b)

        executor = DAGExecutor()
        result = await executor.execute(dag)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 2
        step_names = {s.step_name for s in result.steps}
        assert step_names == {"a", "b"}

    async def test_no_timeout_explicit_none(self) -> None:
        """Passing timeout=None explicitly is identical to the default."""
        dag = _make_dag("explicit-none")
        dag.add(StepDefinition(name="compute", func=fast_step))

        executor = DAGExecutor()
        result = await executor.execute(dag, timeout=None)

        assert result.overall_status == StepStatus.SUCCESS

    async def test_no_timeout_kwargs_none(self) -> None:
        """timeout=None via kwargs path also preserves happy-path behaviour."""
        dag = _make_dag("kwargs-none")
        dag.add(StepDefinition(name="compute", func=fast_step))

        executor = DAGExecutor()
        result = await executor.execute(dag, **{"timeout": None})

        assert result.overall_status == StepStatus.SUCCESS


# ---------------------------------------------------------------------------
# Mixed fast + hung steps
# ---------------------------------------------------------------------------


class TestDAGExecutorTimeoutMixed:
    """Timeout handling when some steps complete before timeout fires."""

    async def test_fast_step_succeeds_hung_step_fails(self) -> None:
        """Independent fast and hung steps: fast succeeds, hung is cancelled."""
        dag = _make_dag("mixed")

        # Two independent root steps
        dag.add(StepDefinition(name="fast", func=fast_step))
        dag.add(StepDefinition(name="hung", func=hung_step))

        executor = DAGExecutor()
        # Give enough time for 'fast' to complete but not 'hung'
        result = await executor.execute(dag, timeout=0.15)

        assert result.overall_status == StepStatus.FAILED
        step_map = {s.step_name: s for s in result.steps}

        # fast should have completed successfully
        if "fast" in step_map:
            assert step_map["fast"].status == StepStatus.SUCCESS

        # hung should be failed or skipped
        assert "hung" in step_map
        assert step_map["hung"].status in (StepStatus.FAILED, StepStatus.SKIPPED)


# ---------------------------------------------------------------------------
# engine.execute span error-status tests (OTEL observability)
# ---------------------------------------------------------------------------


@pytest.fixture
def engine_span_exporter(monkeypatch):
    """Inject an in-memory-exporter-backed tracer for engine.execute spans.

    Mirrors the fixture in test_otel_trace_chain.py: installs a TracerProvider
    with an InMemorySpanExporter and patches the otel module singleton so
    DAGExecutor's ``_get_tracer()`` returns this test tracer (and therefore
    actually creates the ``engine.execute`` span).
    """
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    import agentic_v2.integrations.otel as otel_module

    monkeypatch.setenv("AGENTIC_TRACING", "1")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("agentic-engine-span-test")
    monkeypatch.setattr(otel_module, "_tracer_instance", test_tracer)

    yield exporter

    exporter.clear()


def _engine_span(exporter):
    for span in exporter.get_finished_spans():
        if span.name == "engine.execute":
            return span
    return None


class TestEngineExecuteSpanErrorStatus:
    """The engine.execute span must reflect workflow failure as ERROR."""

    async def test_failing_step_marks_engine_span_error(
        self, engine_span_exporter
    ) -> None:
        """A workflow whose step raises yields an ERROR engine.execute span."""
        from opentelemetry.trace import StatusCode

        dag = _make_dag("engine-fail")
        dag.add(StepDefinition(name="boom", func=raising_step))

        executor = DAGExecutor()
        result = await executor.execute(dag)

        assert result.overall_status == StepStatus.FAILED
        span = _engine_span(engine_span_exporter)
        assert span is not None, "engine.execute span was not exported"
        assert span.status.status_code is StatusCode.ERROR
        assert "exception" in [e.name for e in span.events]

    async def test_timeout_marks_engine_span_error(
        self, engine_span_exporter
    ) -> None:
        """A timed-out workflow yields an ERROR engine.execute span."""
        from opentelemetry.trace import StatusCode

        dag = _make_dag("engine-timeout")
        dag.add(StepDefinition(name="hung", func=hung_step))

        executor = DAGExecutor()
        result = await executor.execute(dag, timeout=0.1)

        assert result.overall_status == StepStatus.FAILED
        span = _engine_span(engine_span_exporter)
        assert span is not None
        assert span.status.status_code is StatusCode.ERROR
        # The timeout path records both the timeout event and the error.
        event_names = [e.name for e in span.events]
        assert "workflow.timeout" in event_names
        assert "exception" in event_names

    async def test_successful_workflow_engine_span_not_error(
        self, engine_span_exporter
    ) -> None:
        """A successful workflow leaves the engine.execute span un-errored."""
        from opentelemetry.trace import StatusCode

        dag = _make_dag("engine-ok")
        dag.add(StepDefinition(name="compute", func=instant_step))

        executor = DAGExecutor()
        result = await executor.execute(dag)

        assert result.overall_status == StepStatus.SUCCESS
        span = _engine_span(engine_span_exporter)
        assert span is not None
        assert span.status.status_code is not StatusCode.ERROR
