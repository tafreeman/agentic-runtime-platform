# Create an agent

Use `BaseAgent` when a step needs the agent lifecycle, memory, model calls, or
tools. A deterministic step is simpler when none of those features are needed.

This minimal agent echoes its input without contacting a provider:

```python
from __future__ import annotations

import asyncio
from typing import Any

from pydantic import Field

from agentic_v2 import AgentConfig, TaskInput, TaskOutput
from agentic_v2.agents.base import BaseAgent


class EchoInput(TaskInput):
    text: str = Field(min_length=1)


class EchoOutput(TaskOutput):
    echo: str = ""


class EchoAgent(BaseAgent[EchoInput, EchoOutput]):
    def __init__(self, config: AgentConfig | None = None) -> None:
        super().__init__(
            config=config
            or AgentConfig(
                name="echo",
                description="Returns the supplied text",
                max_iterations=1,
                max_memory_messages=20,
                max_memory_tokens=1000,
            )
        )

    def _format_task_message(self, task: EchoInput) -> str:
        return task.text

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        last_user = next(
            (
                message.get("content", "")
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )
        return {"content": last_user}

    async def _is_task_complete(
        self,
        task: EchoInput,
        response: str,
    ) -> bool:
        return True

    async def _parse_output(
        self,
        task: EchoInput,
        response: str,
    ) -> EchoOutput:
        return EchoOutput(success=True, echo=response, confidence=1.0)


async def main() -> None:
    agent = EchoAgent()
    try:
        output = await agent.run(EchoInput(text="hello"))
        print(output.echo)
    finally:
        await agent.cleanup()


asyncio.run(main())
```

A production subclass must still implement the same four methods:

- `_format_task_message()`;
- `_call_model()`;
- `_is_task_complete()`;
- `_parse_output()`.

Keep the output structured. If a model response is missing required data,
return a failed output or raise a clear parsing error instead of reporting
success.

## Test the boundary

```python
import asyncio


def test_echo_agent() -> None:
    async def run() -> None:
        agent = EchoAgent()
        try:
            output = await agent.run(EchoInput(text="hi"))
            assert output.success is True
            assert output.echo == "hi"
        finally:
            await agent.cleanup()

    asyncio.run(run())
```

For model-backed agents, inject a fake client and tool registry. Add tests for
malformed output, provider failure, tool failure, cancellation, and the
iteration limit.

See the repository [agent guide](../../../docs/deep-dive-agents.md) for the
full lifecycle and orchestration behavior.
