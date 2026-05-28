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

from .agent_loader import agents as AGENTS
from .agent_loader import load_agents
from .claude_agent import ClaudeAgent, SimpleOutput, SimpleTask
from .claude_sdk_agent import BUILTIN_TOOLS, ClaudeSDKAgent

__all__ = [
    "AGENTS",
    "BUILTIN_TOOLS",
    "ClaudeAgent",
    "ClaudeSDKAgent",
    "SimpleOutput",
    "SimpleTask",
    "load_agents",
]
