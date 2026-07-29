# First native DAG

From the repository root, install the runtime:

```powershell
python -m pip install -e .\agentic-workflows-v2
```

Check the CLI:

```powershell
agentic version
agentic list workflows
```

The following program runs entirely in process and does not call a model:

```python
import asyncio

from agentic_v2 import DAG, DAGExecutor, ExecutionContext, step


async def main() -> None:
    @step("produce")
    async def produce(ctx: ExecutionContext) -> dict:
        return {"text": "hello"}

    @step("shout", depends_on=["produce"])
    async def shout(ctx: ExecutionContext) -> dict:
        text = await ctx.get("text")
        return {"text": str(text).upper()}

    produce_step = produce.with_output(text="text")
    shout_step = (
        shout.with_input(text="text").with_output(text="shout_text")
    )

    dag = DAG(name="hello_dag").add(produce_step).add(shout_step)
    context = ExecutionContext(workflow_id="hello_dag")

    result = await DAGExecutor().execute(dag, ctx=context)
    print(result.overall_status)
    print(result.final_output["shout_text"])


asyncio.run(main())
```

Expected final value:

```text
HELLO
```

`depends_on` controls scheduling. `with_input()` reads a context key and
`with_output()` maps a returned key back into the shared execution context.

Next:

- [Build a workflow](building_workflow.md)
- [Create an agent](creating_agent.md)
- Browse the runnable [examples](../../examples/README.md)
