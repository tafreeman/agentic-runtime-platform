"""Agent factory — creates LangGraph ReAct agents from config.

Each "agent" in YAML (e.g. ``tier2_reviewer``) maps to a configured
``create_react_agent`` instance.  The factory resolves:

- Which ChatModel to use (based on tier)
- Which tools to bind (based on tier + step-level overrides)
- Which system prompt to load (from ``prompts/*.md``)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from langgraph.prebuilt import create_react_agent

from .models import get_model_for_tier
from .tools import get_tools_by_name, get_tools_for_tier

logger = logging.getLogger(__name__)

# Directory containing agent persona prompts (Markdown files)
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Agent name pattern: tier{N}_{role}
_AGENT_PATTERN = re.compile(r"tier(\d+)_(.+)")


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _load_system_prompt(
    agent_name: str,
    prompt_file_override: str | None = None,
) -> str:
    """Load a Markdown persona prompt for an agent.

    Resolution order:
    1. Explicit ``prompt_file_override`` from YAML step.
    2. ``prompts/{role}.md`` where role is extracted from agent name.
    3. A sensible default prompt.
    """
    # Try override first
    if prompt_file_override:
        p = _PROMPTS_DIR / prompt_file_override
        if p.exists():
            return p.read_text(encoding="utf-8")

    # Extract role from agent name (e.g. tier2_reviewer → reviewer)
    match = _AGENT_PATTERN.match(agent_name)
    if match:
        role = match.group(2)
        p = _PROMPTS_DIR / f"{role}.md"
        if p.exists():
            return p.read_text(encoding="utf-8")

    # Fallback
    return (
        f"You are an AI assistant acting as '{agent_name}'.  "
        "Complete the task given to you accurately and concisely."
    )


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def parse_agent_tier(agent_name: str) -> int:
    """Extract the numeric tier from an agent name like ``tier2_reviewer``."""
    match = _AGENT_PATTERN.match(agent_name)
    return int(match.group(1)) if match else 2  # default to tier 2


def create_agent(
    agent_name: str,
    *,
    tool_names: list[str] | None = None,
    prompt_file: str | None = None,
    model_override: str | None = None,
) -> Any:
    """Create a LangGraph ReAct agent for the given agent name.

    Parameters
    ----------
    agent_name:
        Agent identifier from YAML (e.g. ``tier2_reviewer``).
    tool_names:
        Optional list of tool names to restrict to.
        If ``None``, all tools for the agent's tier are used.
    prompt_file:
        Override the system prompt file.
    model_override:
        Override the model name for this agent.

    Returns
    -------
    A compiled LangGraph ``CompiledGraph`` (react agent).
    """
    tier = parse_agent_tier(agent_name)

    # Tier 0 = deterministic, no LLM needed
    if tier == 0:
        return None  # Handled separately by the graph compiler

    # Resolve tools
    if tool_names is not None:
        tools = get_tools_by_name(tool_names)
    else:
        tools = get_tools_for_tier(tier)

    # Resolve model
    model = get_model_for_tier(tier, model_override)

    # Resolve system prompt
    system_prompt = _load_system_prompt(agent_name, prompt_file)

    # Build the ReAct agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        prompt=system_prompt,
    )

    return agent
