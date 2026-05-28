"""Agent discovery endpoint for the Agentic server.

Provides ``GET /api/agents`` which reads agent definitions from
``config/defaults/agents.yaml`` and returns them as a typed list.
Agent configuration is loaded on every request (no caching) to
support live config edits during development.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter

from ..models import AgentInfo, ListAgentsResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agents"])

_AGENTS_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "config"
    / "defaults"
    / "agents.yaml"
)


def _discover_agents() -> list[AgentInfo]:
    """Load agent definitions from the YAML config file.

    Reads ``config/defaults/agents.yaml`` and constructs an
    :class:`AgentInfo` for each entry in the ``agents`` section.

    Returns:
        List of :class:`AgentInfo` instances, or empty list if the
        config file is missing or malformed.
    """
    if not _AGENTS_CONFIG_PATH.exists():
        logger.warning("agents.yaml not found at %s", _AGENTS_CONFIG_PATH)
        return []

    try:
        with open(_AGENTS_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        logger.exception("Failed to load agents.yaml: %s", exc)
        return []

    agents_section = data.get("agents", {})
    if not isinstance(agents_section, dict):
        return []

    result: list[AgentInfo] = []
    for agent_id, agent_data in agents_section.items():
        if not isinstance(agent_data, dict):
            continue
        result.append(
            AgentInfo(
                name=agent_data.get("name", agent_id),
                description=agent_data.get("description", ""),
                tier=agent_data.get("tier", "2"),
            )
        )
    return result


@router.get("/agents", response_model=ListAgentsResponse)
async def list_agents():
    """List available agents (discovered from config)."""
    agents = _discover_agents()
    return ListAgentsResponse(agents=agents)
