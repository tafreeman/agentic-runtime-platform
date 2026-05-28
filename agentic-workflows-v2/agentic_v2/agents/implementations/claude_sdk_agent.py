"""Standalone agent wrapper around the ``claude-agent-sdk`` package.

Provides :class:`ClaudeSDKAgent`, a lightweight async wrapper that delegates
to the SDK's own agentic loop with built-in file, web, and terminal tools
(Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch).

Unlike :class:`~agentic_v2.agents.implementations.claude_agent.ClaudeAgent`,
this class is **not** a :class:`~agentic_v2.agents.base.BaseAgent` subclass.
It bypasses the project's tool registry and conversation memory in favor of
the SDK's native capabilities, making it suitable for self-contained tasks
that benefit from direct filesystem and shell access.

Named sub-agents can be registered via the ``subagents`` parameter, enabling
the orchestrator to delegate subtasks through the SDK's ``Task`` tool.

Requires the ``claude-agent-sdk`` package (install via
``pip install 'agentic-workflows-v2[claude]'``).

Example::

    from agentic_v2.agents.implementations import ClaudeSDKAgent

    agent = ClaudeSDKAgent(
        tools=["Read", "Glob", "Grep", "Bash"],
        cwd="/path/to/project",
    )
    result = await agent.run("Find all TODO comments in the codebase")
    logger.info("Claude SDK agent result: %s", result)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, query
except ImportError as e:
    raise ImportError(
        "claude-agent-sdk is required: pip install 'agentic-workflows-v2[claude]'"
    ) from e


# Available built-in tools provided by the Agent SDK
BUILTIN_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
]


class ClaudeSDKAgent:
    """Async wrapper around the ``claude-agent-sdk`` agentic loop.

    Provides access to Claude's built-in file, web, and terminal tools
    without requiring :class:`~agentic_v2.agents.base.BaseAgent`
    infrastructure or a :class:`~agentic_v2.tools.ToolRegistry`.

    Pass ``subagents`` to register named specialist agents that the
    orchestrator can delegate to via the SDK's ``Task`` tool.

    Attributes:
        BUILTIN_TOOLS: Module-level list of all tool names available in
            the ``claude-agent-sdk``.
    """

    def __init__(
        self,
        model: str = "claude-opus-4-6",
        tools: list[str] | None = None,
        cwd: str | None = None,
        system_prompt: str | None = None,
        max_turns: int = 50,
        permission_mode: str = "default",
        subagents: dict[str, dict[str, Any]] | None = None,
    ):
        """
        Args:
            model: Claude model ID.
            tools: Subset of BUILTIN_TOOLS to allow (default: all).
            cwd: Working directory for file operations.
            system_prompt: Optional custom system prompt.
            max_turns: Maximum agent turns before stopping.
            permission_mode: "default" | "acceptEdits" | "bypassPermissions".
            subagents: Named sub-agents the orchestrator can spawn via Task.
                       Each value is a dict with keys: description, prompt, tools.
        """
        self._model = model
        self._tools = tools or BUILTIN_TOOLS
        self._cwd = cwd
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._permission_mode = permission_mode
        self._subagents = self._build_subagents(subagents or {})

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self, prompt: str) -> str:
        """Run the agent and return the final result string."""
        options = self._build_options()
        result = ""

        async for message in query(prompt=prompt, options=options):
            if message.type == "result":
                result = message.result or ""

        return result

    async def stream(self, prompt: str):
        """Async-iterate over (type, content) tuples from the agent."""
        options = self._build_options()

        async for message in query(prompt=prompt, options=options):
            yield message

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_options(self) -> ClaudeAgentOptions:
        kwargs: dict[str, Any] = dict(
            model=self._model,
            allowed_tools=self._tools,
            permission_mode=self._permission_mode,
            max_turns=self._max_turns,
        )
        if self._cwd:
            kwargs["cwd"] = self._cwd
        if self._system_prompt:
            kwargs["system_prompt"] = self._system_prompt
        if self._subagents:
            kwargs["agents"] = self._subagents
        return ClaudeAgentOptions(**kwargs)

    @staticmethod
    def _build_subagents(
        raw: dict[str, dict[str, Any]],
    ) -> dict[str, AgentDefinition]:
        return {
            name: AgentDefinition(
                description=spec["description"],
                prompt=spec.get("prompt", ""),
                tools=spec.get("tools", ["Read", "Glob", "Grep"]),
            )
            for name, spec in raw.items()
        }
