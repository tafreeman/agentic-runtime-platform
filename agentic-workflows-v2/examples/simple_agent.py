"""Simple agent example for `agentic_v2`.

Run with: python examples/simple_agent.py
"""

import asyncio
from typing import Any

from agentic_v2.agents.base import BaseAgent
from agentic_v2.contracts import TaskInput, TaskOutput


class EchoInput(TaskInput):
    """Input accepted by the echo agent."""

    message: str


class EchoOutput(TaskOutput):
    """Text returned by the echo agent."""

    message: str


class EchoAgent(BaseAgent[EchoInput, EchoOutput]):
    """Minimal concrete agent that requires no model or API key."""

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        del tools
        return {"content": messages[-1]["content"]}

    def _format_task_message(self, task: EchoInput) -> str:
        return task.message

    async def _is_task_complete(self, task: EchoInput, response: str) -> bool:
        del task, response
        return True

    async def _parse_output(self, task: EchoInput, response: str) -> EchoOutput:
        del task
        return EchoOutput(success=True, message=response)


async def main():
    agent = EchoAgent()
    output = await agent.run(EchoInput(message="hello"))
    print(output.message)


if __name__ == "__main__":
    asyncio.run(main())
