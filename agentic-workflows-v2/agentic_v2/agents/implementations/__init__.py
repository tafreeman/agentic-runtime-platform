"""Concrete agent implementations backed by external LLM SDKs.

This subpackage provides two production-ready agent implementations:

:class:`ClaudeAgent`:
    A :class:`~agentic_v2.agents.base.BaseAgent` subclass that calls the
    Anthropic Messages API, translating between the project's internal
    OpenAI-style message format and the Anthropic SDK.

:class:`ClaudeSDKAgent`:
    A standalone wrapper around the ``claude-agent-sdk`` package that
    provides built-in file, web, and terminal tools without requiring
    :class:`~agentic_v2.agents.base.BaseAgent` infrastructure.

:func:`load_agents`:
    Loader that reads ``.md`` agent definition files (YAML frontmatter +
    system prompt body) and returns a dict of
    :class:`~claude_agent_sdk.AgentDefinition` instances.
"""

from __future__ import annotations

# ClaudeAgent uses only the `anthropic` SDK and must always be importable.
from .claude_agent import ClaudeAgent, SimpleOutput, SimpleTask

# The remaining exports depend on the optional `claude-agent-sdk` ([claude]
# extra). Guard them so importing this package — and ClaudeAgent — does not
# hard-require the SDK; the names are simply absent (clear ImportError on use)
# when the extra is not installed.
try:
    from .agent_loader import agents as AGENTS
    from .agent_loader import load_agents
    from .claude_sdk_agent import BUILTIN_TOOLS, ClaudeSDKAgent

    _CLAUDE_SDK_EXPORTS = ["AGENTS", "BUILTIN_TOOLS", "ClaudeSDKAgent", "load_agents"]
except ImportError:  # pragma: no cover - exercised only without the [claude] extra
    _CLAUDE_SDK_EXPORTS = []

__all__ = [
    "ClaudeAgent",
    "SimpleOutput",
    "SimpleTask",
    *_CLAUDE_SDK_EXPORTS,
]
