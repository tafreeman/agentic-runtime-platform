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

Authenticates with the operator's Claude subscription sign-in: the SDK spawns
the Claude Code CLI, which resolves credentials itself. The CLI subprocess
inherits ``os.environ``, and ``agentic_v2.models.secrets`` puts
``ANTHROPIC_API_KEY`` there during backend auto-configuration -- so without an
explicit scrub the child silently authenticates with the API key instead,
billing the wrong account and failing outright when that key is unfunded. The
credential variables are therefore blanked in the child env (see
:func:`~agentic_v2.models.backends_claude.subscription_env`); pass ``env`` to
override that deliberately.

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
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

try:
    from claude_agent_sdk import (
        AgentDefinition,
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )
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
        model: str = "claude-opus-5",
        tools: list[str] | None = None,
        cwd: str | None = None,
        system_prompt: str | None = None,
        max_turns: int = 50,
        permission_mode: str = "default",
        subagents: dict[str, dict[str, Any]] | None = None,
        env: dict[str, str] | None = None,
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
            env: Extra environment for the CLI subprocess, applied over the
                 API-key scrub. Use it to deliberately restore API-key auth.
        """
        self._model = model
        self._tools = tools or BUILTIN_TOOLS
        self._cwd = cwd
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._permission_mode = permission_mode
        self._subagents = self._build_subagents(subagents or {})
        self._env = env or {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self, prompt: str) -> str:
        """Run the agent and return its final text.

        Dispatch is by ``isinstance`` against the SDK's message dataclasses:
        none of them carries a ``.type`` attribute, so an earlier
        ``message.type == "result"`` check raised ``AttributeError`` on the
        first message of every run.

        ``ResultMessage.result`` is preferred when the harness supplies it, and
        the concatenated assistant text is the fallback -- a run that ends
        without a ``ResultMessage`` (max turns, an interrupted stream) still
        returns whatever the model produced rather than an empty string.
        """
        prompt = await self._sanitize_prompt(prompt)
        options = self._build_options()

        text_parts: list[str] = []
        final: str | None = None

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                text_parts.extend(
                    block.text
                    for block in message.content
                    if isinstance(block, TextBlock)
                )
            elif isinstance(message, ResultMessage):
                if message.is_error:
                    detail = "; ".join(message.errors or []) or message.subtype
                    raise RuntimeError(f"Claude SDK agent run failed: {detail}")
                final = message.result

        return final if final is not None else "".join(text_parts)

    async def stream(self, prompt: str) -> AsyncIterator[Any]:
        """Async-iterate over the SDK's own message objects.

        Yields ``AssistantMessage`` / ``ResultMessage`` / ``SystemMessage`` /
        ``RateLimitEvent`` dataclasses verbatim, not ``(type, content)`` tuples
        as this docstring previously claimed. Consumers must dispatch with
        ``isinstance``; the messages carry no ``.type`` attribute.
        """
        prompt = await self._sanitize_prompt(prompt)
        options = self._build_options()

        async for message in query(prompt=prompt, options=options):
            yield message

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _sanitize_prompt(prompt: str) -> str:
        """Run inbound sanitization over the task prompt before the SDK loop.

        Unlike :class:`ClaudeAgent`, this wrapper delegates to the
        ``claude-agent-sdk``'s own sandboxed agentic loop, so untrusted tool
        *outputs* never pass back through this process — there is no
        tool-result-into-memory vector here. The one untrusted entry point is
        the inbound prompt, sanitized here as defense-in-depth before the SDK
        may act on it with built-in Bash/Write/Edit tools.

        Reuses the shared client's gated sanitizer (attached by ``get_client``
        per ``AGENTIC_SANITIZE_AGENT_LOOP``; a no-op under ``AGENTIC_NO_LLM``
        or when the flag is off). Fails closed — an unsafe prompt raises
        ``ValueError`` before the SDK runs.
        """
        from ...models import ModelTier, get_client

        sanitized = await get_client().sanitize_inbound_messages(
            [{"role": "user", "content": prompt}],
            source="claude_sdk_agent",
            tier=ModelTier.TIER_2,
        )
        return str(sanitized[0]["content"])

    def _build_options(self) -> ClaudeAgentOptions:
        from ...models.backends_claude import subscription_env

        kwargs: dict[str, Any] = {
            "model": self._model,
            "allowed_tools": self._tools,
            "permission_mode": self._permission_mode,
            "max_turns": self._max_turns,
            # Pins the CLI to the subscription sign-in; without it the child
            # inherits ANTHROPIC_API_KEY from os.environ and bills the API
            # account instead. See the module docstring.
            "env": subscription_env(self._env),
        }
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
