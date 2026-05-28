"""Minimal workflow run example.

Run with: python examples/workflow_run.py
"""

import asyncio
import logging
from pathlib import Path

from agentic_v2 import DAGExecutor, ExecutionContext
from agentic_v2.workflows import WorkflowLoader


async def main():
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Use default package definitions
    try:
        loader = WorkflowLoader()
        available = loader.list_workflows()
        logger.info(f"Available workflows: {available}")

        if not available:
            logger.warning("No workflows found in package definitions.")
            return

        # Pick the first one, e.g., "code_review"
        wf_name = "code_review" if "code_review" in available else available[0]
        logger.info(f"Loading workflow: {wf_name}")

        workflow_def = loader.load(wf_name)
        dag = workflow_def.dag

        # Prepare context with some dummy input if needed
        ctx = ExecutionContext(workflow_id=f"run_{wf_name}")
        # For code_review, we need a 'code_file' input.
        if wf_name == "code_review":
            # Create a dummy python file to review
            dummy_file = Path("dummy_code.py")
            dummy_file.write_text("def hello():\n    print('world')\n")
            ctx.set_sync("code_file", str(dummy_file))
            logger.info(f"Created dummy file: {dummy_file}")

        logger.info(f"Executing workflow: {wf_name}")
        executor = DAGExecutor()
        res = await executor.execute(dag, ctx=ctx)

        # Cleanup dummy file
        if wf_name == "code_review" and Path("dummy_code.py").exists():
            Path("dummy_code.py").unlink()
            logger.info("Cleaned up dummy file")

        print("\nWorkflow Execution Result:")
        print(f"Status: {res.overall_status}")
        print(f"Result: {res}")

    except Exception as e:
        logger.error(f"Error running workflow: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
