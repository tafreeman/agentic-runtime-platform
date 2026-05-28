"""YAML workflow loading and execution example.

Demonstrates how to:
1. Load a YAML workflow definition from disk
2. Validate its structure
3. Execute it with the native DAG executor
4. Inspect step results

Run with: python examples/yaml_workflow.py

No API keys required — uses the built-in deterministic (tier-0) workflow.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from textwrap import dedent

from agentic_v2 import DAGExecutor, ExecutionContext
from agentic_v2.workflows import WorkflowLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Create a temporary YAML workflow definition
# ---------------------------------------------------------------------------

SAMPLE_YAML = dedent("""\
    name: example_deterministic
    description: Simple two-step deterministic workflow (no LLM calls)
    version: "1.0"

    inputs:
      input_text:
        type: string
        description: Text to process
        required: true

    outputs:
      processed_text:
        from: ${steps.parse.outputs.result}

    steps:
      - name: parse
        agent: tier0_parser
        description: Parse input text and extract structure
        inputs:
          code_file: ${workflow_inputs.input_text}
        outputs:
          result: parsed_ast
""")


async def main() -> None:
    """Load, validate, and execute a YAML workflow."""

    # Write the YAML to a temp directory so WorkflowLoader can find it
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / "example_deterministic.yaml"
        yaml_path.write_text(SAMPLE_YAML, encoding="utf-8")

        # ── Load ──────────────────────────────────────────────────
        loader = WorkflowLoader(definitions_dir=Path(tmpdir))
        available = loader.list_workflows()
        logger.info("Available workflows: %s", available)

        workflow_def = loader.load("example_deterministic")
        dag = workflow_def.dag
        logger.info(
            "Loaded '%s': %d steps",
            workflow_def.name,
            len(dag.steps),
        )

        # ── Execute ───────────────────────────────────────────────
        ctx = ExecutionContext(workflow_id="yaml-demo-001")
        # Provide a small Python snippet as input text
        ctx.set_sync(
            "input_text",
            "def greet(name):\n    return f'Hello, {name}!'\n",
        )

        executor = DAGExecutor()
        result = await executor.execute(dag, ctx=ctx)

        # ── Inspect results ───────────────────────────────────────
        logger.info("Overall status: %s", result.overall_status)
        for step in result.steps:
            logger.info(
                "  Step '%s': status=%s, output_data=%s",
                step.step_name,
                step.status,
                list(step.output_data.keys()) if step.output_data else "none",
            )

        duration_ms = result.total_duration_ms
        if duration_ms is not None:
            logger.info("Workflow finished in %.1f ms", duration_ms)


if __name__ == "__main__":
    asyncio.run(main())
