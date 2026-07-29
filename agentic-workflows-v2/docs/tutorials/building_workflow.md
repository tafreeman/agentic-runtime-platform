# Build a Python workflow

This example creates two deterministic steps and connects them through an
`ExecutionContext`.

```python
from __future__ import annotations

import asyncio

from agentic_v2 import DAG, DAGExecutor, ExecutionContext, StepStatus, step


@step("load")
async def load(ctx: ExecutionContext) -> dict:
    return {"text": "hello world"}


@step("transform", depends_on=["load"])
async def transform(ctx: ExecutionContext) -> dict:
    text = await ctx.get("text")
    return {"upper": str(text).upper()}


async def main() -> None:
    load_step = load.with_output(text="text")
    transform_step = (
        transform.with_input(text="text").with_output(upper="result")
    )

    dag = DAG(name="demo").add(load_step).add(transform_step)
    context = ExecutionContext(workflow_id="demo")
    result = await DAGExecutor().execute(dag, ctx=context)

    if result.overall_status != StepStatus.SUCCESS:
        raise RuntimeError(result.failed_steps)

    print(result.final_output["result"])


asyncio.run(main())
```

The important contracts are:

- `depends_on=["load"]` prevents `transform` from running early.
- `with_output(text="text")` publishes the returned `text` value.
- `with_input(text="text")` declares which context value the next step reads.
- `with_output(upper="result")` gives the final value a workflow-level name.

Independent DAG nodes may run concurrently. If you need strict ordering,
explicit parallel groups, or conditional branches, use `PipelineBuilder`.
Configure timeouts and retries on `StepDefinition`; do not implement retry
loops inside each step.

For declarative YAML workflows, use the repository
[workflow authoring guide](../../../docs/WORKFLOW_AUTHORING.md).
