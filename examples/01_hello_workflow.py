"""01 — Run a simple workflow from Python.

Demonstrates:
    - Defining step functions that operate on :class:`ExecutionContext`.
    - Building a two-step :class:`Pipeline` with :class:`PipelineBuilder`.
    - Running the pipeline synchronously via ``asyncio.run``.
    - Inspecting :class:`WorkflowResult` with per-step outcomes.

No API keys are required.  All logic is deterministic.

Usage:
    python examples/01_hello_workflow.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from agentic_v2.contracts import WorkflowResult

# ---- Imports from the agentic-workflows-v2 package -----------------------
from agentic_v2.engine import (
    ExecutionContext,
    Pipeline,
    PipelineBuilder,
    PipelineExecutor,
    StepDefinition,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step functions
# ---------------------------------------------------------------------------
# Each step receives an ExecutionContext and returns a dict of outputs.
# Steps are pure async functions — no LLM calls here, so no API keys needed.


async def greet(ctx: ExecutionContext) -> dict[str, Any]:
    """Produce a greeting message from the context's 'name' variable."""
    name = ctx.get_sync("name") or "World"
    greeting = f"Hello, {name}!"
    logger.info("Step 'greet' produced: %s", greeting)
    return {"greeting": greeting}


async def shout(ctx: ExecutionContext) -> dict[str, Any]:
    """Transform the greeting into uppercase."""
    greeting = ctx.get_sync("greeting") or ""
    shouted = greeting.upper()
    logger.info("Step 'shout' produced: %s", shouted)
    return {"shouted": shouted}


# ---------------------------------------------------------------------------
# Build and run the pipeline
# ---------------------------------------------------------------------------


async def main() -> None:
    """Build a two-step pipeline, execute it, and print results."""

    # 1. Define steps ----------------------------------------------------------
    #
    # Steps return dicts.  Use output_mapping to route return values
    # into the shared ExecutionContext so downstream steps can read them.
    step_greet = StepDefinition(
        name="greet",
        description="Generate a greeting",
        func=greet,
        output_mapping={"greeting": "greeting"},  # step return key -> context key
    )

    step_shout = StepDefinition(
        name="shout",
        description="Uppercase the greeting",
        func=shout,
        output_mapping={"shouted": "shouted"},
    )

    # 2. Build the pipeline ----------------------------------------------------
    # PipelineBuilder uses .step() for fluent construction.
    pipeline: Pipeline = (
        PipelineBuilder("hello_workflow").step(step_greet).step(step_shout).build()
    )

    # 3. Create a shared execution context with initial data -------------------
    ctx = ExecutionContext()
    ctx.set_sync("name", "Agentic Workflows")

    # 4. Execute ---------------------------------------------------------------
    # PipelineExecutor returns a WorkflowResult with per-step outcomes.
    executor = PipelineExecutor()
    result: WorkflowResult = await executor.execute(pipeline, ctx)

    # 5. Inspect results -------------------------------------------------------
    #
    # Step functions store outputs in two places:
    #   - Return dict  -> StepResult.output_data (accessible via result.steps)
    #   - ctx.set_sync -> Shared ExecutionContext (accessible via ctx.get_sync)
    #
    # Both are shown here for completeness.
    print("\n=== Pipeline Results ===")
    print(f"Status : {result.overall_status.value}")
    print(f"Steps  : {len(result.steps)} completed")
    for step_res in result.steps:
        print(f"  {step_res.step_name}: {step_res.status.value}")
        if step_res.output_data:
            print(f"    outputs: {step_res.output_data}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
