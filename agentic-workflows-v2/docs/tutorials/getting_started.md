## Getting Started

This quick tutorial shows how to install and run a minimal workflow example.

1. Install in editable mode:

```bash
pip install -e .
```

2. (Optional) Explore what's available via the CLI:

```bash
agentic list agents
agentic list tools
```

3. Run a tiny in-process DAG (no LLM required):

```python
import asyncio

from agentic_v2 import DAG, DAGExecutor, ExecutionContext, step

async def main():
    @step("produce")
    async def produce(ctx: ExecutionContext) -> dict:
        return {"text": "hello"}

    @step("shout", depends_on=["produce"])
    async def shout(ctx: ExecutionContext) -> dict:
        text = await ctx.get("text")
        return {"text": str(text).upper()}

    produce_step = produce.with_output(text="text")
    shout_step = shout.with_input(text="text").with_output(text="shout_text")

    dag = DAG(name="hello_dag").add(produce_step).add(shout_step)
    ctx = ExecutionContext(workflow_id="hello_dag")

    result = await DAGExecutor().execute(dag, ctx=ctx)
    print(result.overall_status)
    print(result.final_output["shout_text"])  # -> HELLO

asyncio.run(main())
```

See `../examples/` for runnable examples.
