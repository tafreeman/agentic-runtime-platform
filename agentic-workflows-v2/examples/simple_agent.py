"""Simple agent example for `agentic_v2`.

Run with: python examples/simple_agent.py
"""

import asyncio

from agentic_v2.agents.base import BaseAgent


class EchoAgent(BaseAgent):
    async def run(self, input):
        return {"echo": input}


async def main():
    agent = EchoAgent()
    out = await agent.run({"message": "hello"})
    print(out)


if __name__ == "__main__":
    asyncio.run(main())
