"""06 — Switch between the native DAG engine and the Pipeline engine.

Demonstrates:
    - Using the :class:`AdapterRegistry` to discover registered engines.
    - Building a :class:`DAG` with dependency edges and executing it via
      the :class:`DAGExecutor` (Kahn's algorithm scheduler).
    - Building an equivalent :class:`Pipeline` and executing it via
      :class:`PipelineExecutor` (sequential/parallel groups).
    - Comparing execution semantics: DAG (maximum parallelism from
      dependency graph) vs Pipeline (explicit stage ordering).

No API keys are required.  All step functions are deterministic.

Usage:
    python examples/06_adapter_switching.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Any

from agentic_v2.adapters import get_registry as get_adapter_registry
from agentic_v2.engine import (
    DAG,
    DAGExecutor,
    ExecutionContext,
    Pipeline,
    PipelineBuilder,
    PipelineExecutor,
    StepDefinition,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared step functions
# ---------------------------------------------------------------------------
# Each step simulates a brief async operation.  The same functions are used
# by both the DAG and Pipeline engines to show the difference in scheduling.


async def fetch_data(ctx: ExecutionContext) -> dict[str, Any]:
    """Simulate fetching data from an external source."""
    await asyncio.sleep(0.1)  # Simulate I/O
    records = ["alpha", "beta", "gamma", "delta"]
    logger.info("  [fetch_data] Fetched %d records", len(records))
    return {"records": records}


async def validate_data(ctx: ExecutionContext) -> dict[str, Any]:
    """Validate the fetched data (depends on fetch_data)."""
    await asyncio.sleep(0.05)
    raw = ctx.get_sync("raw_data")
    record_count = len(raw) if isinstance(raw, list) else 0
    logger.info("  [validate_data] Validated %d records", record_count)
    return {"valid_count": record_count}


async def enrich_data(ctx: ExecutionContext) -> dict[str, Any]:
    """Enrich data with metadata (depends on fetch_data, parallel with validate)."""
    await asyncio.sleep(0.08)
    raw = ctx.get_sync("raw_data")
    records = raw if isinstance(raw, list) else []
    enriched = [f"{r}_enriched" for r in records]
    logger.info("  [enrich_data] Enriched %d records", len(enriched))
    return {"enriched_records": enriched}


async def generate_report(ctx: ExecutionContext) -> dict[str, Any]:
    """Generate a final report (depends on validate AND enrich)."""
    await asyncio.sleep(0.05)
    valid_count = ctx.get_sync("valid_count") or 0
    enriched = ctx.get_sync("enriched_records") or []
    report = {
        "summary": f"Processed {valid_count} valid records",
        "enriched_count": len(enriched),
        "status": "complete",
    }
    logger.info("  [generate_report] Report: %s", report["summary"])
    return report


# ---------------------------------------------------------------------------
# 1. Adapter Registry — discover available engines
# ---------------------------------------------------------------------------


def demo_adapter_registry() -> None:
    """Show how to discover registered engine adapters."""
    print("=" * 60)
    print("1. Adapter Registry — Available Engines")
    print("=" * 60)

    registry = get_adapter_registry()
    adapters = registry.list_adapters()
    print(f"  Registered adapters: {adapters}")

    for adapter_name in adapters:
        engine = registry.get_adapter(adapter_name)
        print(f"  '{adapter_name}' -> {type(engine).__name__}")


# ---------------------------------------------------------------------------
# 2. DAG Execution — maximum parallelism from dependency graph
# ---------------------------------------------------------------------------


async def demo_dag_execution() -> None:
    """Execute a workflow as a DAG with dependency-driven parallelism."""
    print("\n" + "=" * 60)
    print("2. DAG Execution (Kahn's Algorithm)")
    print("=" * 60)

    # Define steps with explicit dependencies and output_mapping.
    # output_mapping routes the return-dict keys into the shared context
    # so downstream steps can read them via ctx.get_sync().
    step_fetch = StepDefinition(
        name="fetch_data",
        description="Fetch raw data",
        func=fetch_data,
        output_mapping={"records": "raw_data"},
    )
    step_validate = StepDefinition(
        name="validate_data",
        description="Validate data",
        func=validate_data,
        depends_on=["fetch_data"],
        output_mapping={"valid_count": "valid_count"},
    )
    step_enrich = StepDefinition(
        name="enrich_data",
        description="Enrich data",
        func=enrich_data,
        depends_on=["fetch_data"],
        output_mapping={"enriched_records": "enriched_records"},
    )
    step_report = StepDefinition(
        name="generate_report",
        description="Generate report",
        func=generate_report,
        depends_on=["validate_data", "enrich_data"],
        output_mapping={"summary": "report_summary"},
    )

    # Build the DAG
    dag = DAG(name="data_pipeline")
    dag.add(step_fetch)
    dag.add(step_validate)
    dag.add(step_enrich)
    dag.add(step_report)

    # Validate structure (checks for cycles, missing deps)
    dag.validate()

    # Show structure
    ready_initially = dag.get_ready_steps(completed=set())
    print(f"  DAG: {dag.name}")
    print(f"  Steps: {[s.name for s in dag.steps.values()]}")
    print(f"  Initially ready (no deps): {ready_initially}")
    print("  Dependency graph:")
    for step_name, step_def in dag.steps.items():
        deps = step_def.depends_on or []
        print(f"    {step_name} <- {deps if deps else '(no deps)'}")

    # Execute with DAGExecutor
    ctx = ExecutionContext()
    executor = DAGExecutor()

    print("\n  Executing DAG...")
    start = time.monotonic()
    result = await executor.execute(dag, ctx)
    elapsed = (time.monotonic() - start) * 1000

    print("\n  DAG Results:")
    print(f"    Overall status: {result.overall_status.value}")
    print(f"    Elapsed: {elapsed:.0f}ms")
    print(f"    Steps completed: {len(result.steps)}")
    for step_result in result.steps:
        print(f"      {step_result.step_name}: {step_result.status.value}")

    # Note: validate_data and enrich_data run IN PARALLEL because
    # they share the same dependency (fetch_data) but don't depend
    # on each other.  The DAG executor uses Kahn's algorithm to
    # maximize concurrency.
    print("\n  Key insight: validate_data and enrich_data ran in parallel")
    print("  because they only depend on fetch_data, not on each other.")


# ---------------------------------------------------------------------------
# 3. Pipeline Execution — explicit stage ordering
# ---------------------------------------------------------------------------


async def demo_pipeline_execution() -> None:
    """Execute the same workflow as a sequential Pipeline."""
    print("\n" + "=" * 60)
    print("3. Pipeline Execution (Sequential Stages)")
    print("=" * 60)

    # Build a pipeline — steps run in the order they are added.
    # Same output_mapping as the DAG version for context data flow.
    step_fetch = StepDefinition(
        name="fetch_data",
        description="Fetch raw data",
        func=fetch_data,
        output_mapping={"records": "raw_data"},
    )
    step_validate = StepDefinition(
        name="validate_data",
        description="Validate data",
        func=validate_data,
        output_mapping={"valid_count": "valid_count"},
    )
    step_enrich = StepDefinition(
        name="enrich_data",
        description="Enrich data",
        func=enrich_data,
        output_mapping={"enriched_records": "enriched_records"},
    )
    step_report = StepDefinition(
        name="generate_report",
        description="Generate report",
        func=generate_report,
        output_mapping={"summary": "report_summary"},
    )

    pipeline: Pipeline = (
        PipelineBuilder("data_pipeline_sequential")
        .step(step_fetch)
        .step(step_validate)
        .step(step_enrich)
        .step(step_report)
        .build()
    )

    ctx = ExecutionContext()
    executor = PipelineExecutor()

    print(f"  Pipeline: {pipeline.name}")
    print("  Steps run strictly in order (no parallelism)")

    print("\n  Executing Pipeline...")
    start = time.monotonic()
    result = await executor.execute(pipeline, ctx)
    elapsed = (time.monotonic() - start) * 1000

    print("\n  Pipeline Results:")
    print(f"    Status: {result.overall_status.value}")
    print(f"    Elapsed: {elapsed:.0f}ms")
    print(f"    Steps completed: {len(result.steps)}")
    print(f"    Report: {ctx.get_sync('report_summary')}")

    print("\n  Key insight: In the Pipeline, validate and enrich run")
    print("  sequentially even though they could run in parallel.")
    print("  Use DAG when you need dependency-driven parallelism.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run all adapter switching demonstrations."""
    demo_adapter_registry()
    await demo_dag_execution()
    await demo_pipeline_execution()

    print("\n" + "=" * 60)
    print("Engine comparison complete.")
    print("  - DAG: Maximum parallelism from dependency graph (Kahn's algorithm)")
    print("  - Pipeline: Explicit sequential ordering (simpler for linear flows)")
    print("  - Adapter Registry: Switch engines at runtime via get_adapter()")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
