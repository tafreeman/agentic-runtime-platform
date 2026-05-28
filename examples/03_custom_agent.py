"""03 — Create a minimal custom agent extending BaseAgent.

Demonstrates:
    - Subclassing :class:`BaseAgent` with typed I/O (``TaskInput`` / ``TaskOutput``).
    - Implementing the four required abstract methods:
        ``_call_model``, ``_format_task_message``,
        ``_is_task_complete``, ``_parse_output``.
    - Configuring the agent with :class:`AgentConfig`.
    - Registering an event handler for observability.
    - Running the agent on a :class:`TaskInput`.

This example uses a **mock LLM call** (no API keys required).
The ``_call_model`` method returns a deterministic response to show
the full agent lifecycle without needing a real LLM provider.

Usage:
    python examples/03_custom_agent.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Optional

from agentic_v2.agents import AgentConfig, AgentEvent, AgentState, BaseAgent
from agentic_v2.contracts import TaskInput, TaskOutput
from agentic_v2.models import ModelTier

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom agent: SummarizerAgent
# ---------------------------------------------------------------------------
# Demonstrates the minimal contract a concrete agent must satisfy.


class SummarizerAgent(BaseAgent[TaskInput, TaskOutput]):
    """A simple agent that summarizes text input.

    This is a teaching example — the ``_call_model`` method returns a
    hard-coded summary to illustrate the agent lifecycle without
    requiring an API key.
    """

    def __init__(self, config: Optional[AgentConfig] = None, **kwargs: Any):
        if config is None:
            config = AgentConfig(
                name="summarizer",
                description="Summarizes input text into key bullet points",
                system_prompt=(
                    "You are a precise text summarizer. "
                    "Extract the 3 most important points as bullet items."
                ),
                default_tier=ModelTier.TIER_2,
                max_iterations=3,
            )
        super().__init__(config=config, **kwargs)

    # -- Required abstract method: call the LLM ----------------------------

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Simulate an LLM call with a deterministic response.

        In a real agent, this would call the LLM via ``self.llm_client``
        or the ``self.router`` to select the best model.  Here we return
        a canned summary to demonstrate the lifecycle.
        """
        # Extract the user message (last non-system message)
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break

        # Produce a mock summary
        word_count = len(user_content.split())
        summary = (
            f"Summary of input ({word_count} words):\n"
            f"- Key point 1: The text discusses important concepts.\n"
            f"- Key point 2: Multiple topics are covered.\n"
            f"- Key point 3: The content is {word_count} words long."
        )

        return {"content": summary}

    # -- Required abstract method: format input as a user message ----------

    def _format_task_message(self, task: TaskInput) -> str:
        """Convert the TaskInput into a user-facing prompt string."""
        # TaskInput has task_id, context, and constraints fields.
        # We use the context dict to pass the text to summarize.
        text_to_summarize = task.context.get("text", "No text provided.")
        context_info = ""
        extra_keys = {k: v for k, v in task.context.items() if k != "text"}
        if extra_keys:
            context_info = "\n\nAdditional context:\n"
            for key, value in extra_keys.items():
                context_info += f"  {key}: {value}\n"

        return f"Please summarize the following:\n\n{text_to_summarize}{context_info}"

    # -- Required abstract method: decide if the task is done --------------

    async def _is_task_complete(self, task: TaskInput, response: str) -> bool:
        """A summary is complete when the response contains bullet points."""
        return "- " in response

    # -- Required abstract method: parse the LLM response into output ------

    async def _parse_output(self, task: TaskInput, response: str) -> TaskOutput:
        """Wrap the raw summary text into a TaskOutput."""
        return TaskOutput(
            success=True,
            confidence=0.9,
            model_used="mock-summarizer",
            summary=response,
            iterations=self._iteration_count,
        )


# ---------------------------------------------------------------------------
# Event handler for observability
# ---------------------------------------------------------------------------


def on_agent_event(agent: BaseAgent, event: AgentEvent, data: dict[str, Any]) -> None:
    """Log agent lifecycle events for observability."""
    if event == AgentEvent.STATE_CHANGE:
        print(f"  [EVENT] State: {data['old_state']} -> {data['new_state']}")
    elif event == AgentEvent.THINKING:
        print(f"  [EVENT] Thinking (iteration {data['iteration']})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """Create, configure, and run the custom SummarizerAgent."""

    # 1. Instantiate the agent ------------------------------------------------
    agent = SummarizerAgent()
    print(f"Created agent: {agent.config.name}")
    print(f"  Description: {agent.config.description}")
    print(f"  Default tier: {agent.config.default_tier.name}")
    print(f"  Max iterations: {agent.config.max_iterations}")

    # 2. Register an event handler for lifecycle visibility -------------------
    agent.on_event(on_agent_event)

    # 3. Build a task input ---------------------------------------------------
    # TaskInput uses the `context` dict to pass data to the agent.
    # The "text" key is what our _format_task_message expects.
    task = TaskInput(
        context={
            "text": (
                "Python is a high-level programming language known for its "
                "readability and versatility.  It supports multiple paradigms "
                "including object-oriented, functional, and procedural programming.  "
                "Python has a vast ecosystem of libraries for web development, "
                "data science, machine learning, automation, and more."
            ),
            "audience": "beginners",
            "max_bullets": "3",
        },
    )

    # 4. Run the agent --------------------------------------------------------
    print("\nRunning agent...")
    result = await agent.run(task)

    # 5. Inspect the result ---------------------------------------------------
    print("\n=== Agent Result ===")
    print(f"State      : {agent.state.value}")
    print(f"Iterations : {agent.iteration_count}")
    print(f"Success    : {result.success}")
    print(f"Model used : {result.model_used}")
    print(f"Confidence : {result.confidence}")
    # TaskOutput with extra="allow" stores our custom 'summary' field
    summary = getattr(result, "summary", "N/A")
    print(f"Summary    :\n{summary}")

    # 6. Clean up -------------------------------------------------------------
    await agent.cleanup()
    print("\nAgent cleaned up successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
