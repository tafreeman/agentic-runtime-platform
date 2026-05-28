## Creating an Agent

This guide shows a minimal agent implementation and how to register it with the framework.

1. Create a new agent class in `agentic_v2/agents/`.

`BaseAgent` is async-first and expects you to implement the model call and some simple parsing hooks.
Here’s a tiny **offline-friendly** agent that just echoes its input (no LLM required):

```python
from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from agentic_v2 import AgentConfig, TaskInput, TaskOutput
from agentic_v2.agents.base import BaseAgent


class EchoInput(TaskInput):
    text: str = Field(description="Text to echo")


class EchoOutput(TaskOutput):
    echo: str = ""


class EchoAgent(BaseAgent[EchoInput, EchoOutput]):
    def __init__(self, config: Optional[AgentConfig] = None):
        super().__init__(
            config
            or AgentConfig(
                name="echo",
                description="Echoes text back",
                # Memory is bounded by both messages + an approximate token budget.
                max_memory_messages=20,
                max_memory_tokens=1000,
            )
        )

    def _format_task_message(self, task: EchoInput) -> str:
        return task.text

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        # No LLM call needed; just echo the last user message.
        last_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        return {"content": last_user}

    async def _is_task_complete(self, task: EchoInput, response: str) -> bool:
        return True

    async def _parse_output(self, task: EchoInput, response: str) -> EchoOutput:
        return EchoOutput(success=True, echo=response, confidence=1.0)
```

2. Use it:

```python
import asyncio


async def main() -> None:
    agent = EchoAgent()
    out = await agent.run(EchoInput(text="hello"))
    print(out.echo)


asyncio.run(main())
```

3. Unit test example (pytest):

```python
import asyncio

def test_echo_agent():
    agent = EchoAgent()
    out = asyncio.run(agent.run(EchoInput(text="hi")))
    assert out.success is True
    assert out.echo == "hi"
```
