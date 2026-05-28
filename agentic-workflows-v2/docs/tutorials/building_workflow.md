## Building a Workflow

This tutorial demonstrates a simple workflow definition and execution using the engine primitives.

1. Define step functions with the `@step` decorator:

```python
from __future__ import annotations

import asyncio

from agentic_v2 import DAG, DAGExecutor, ExecutionContext, step


@step("load")
async def load(ctx: ExecutionContext) -> dict:
  # No inputs; produce an output
  return {"text": "hello world"}


@step("transform", depends_on=["load"])
async def transform(ctx: ExecutionContext) -> dict:
  text = await ctx.get("text")
  return {"upper": str(text).upper()}
```

2. Wire inputs/outputs through the shared context and execute as a DAG:

```python
async def main() -> None:
  load_step = load.with_output(text="text")
  transform_step = (
    transform.with_input(text="text").with_output(upper="result")
  )

  dag = DAG(name="demo").add(load_step).add(transform_step)
  ctx = ExecutionContext(workflow_id="demo")

  wf_result = await DAGExecutor().execute(dag, ctx=ctx)
  print(wf_result.overall_status)
  print(wf_result.final_output["result"])  # -> HELLO WORLD


asyncio.run(main())
```

3. Next steps:

- Use `depends_on=[...]` to express parallelism and dependencies.
- Add `timeout` / retry policies on steps via `StepDefinition.with_timeout(...)` and `StepDefinition.with_retry(...)`.
- For higher-level patterns (pipelines, conditional branches), see the `PipelineBuilder` APIs in `agentic_v2.engine`.
