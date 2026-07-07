"""Catalog routes: personas, tools, and observer channels.

These read-only endpoints feed the workflow editor's per-node pickers:

* ``GET /api/personas`` -- pre-canned personas from the persona registry.
* ``GET /api/tools`` -- tools a step may allowlist, with tier defaults.
* ``GET /api/observers`` -- observer channels a step may enable.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..models_settings import (
    ListObserversResponse,
    ListPersonasResponse,
    ListToolsResponse,
    ObserverInfo,
    PersonaInfo,
    ToolInfo,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["catalog"])

_PROMPT_PREVIEW_CHARS = 240

_OBSERVER_DESCRIPTIONS: dict[str, str] = {
    "trace": (
        "Engine trace adapter (OpenTelemetry spans and canonical step events)."
    ),
    "websocket": (
        "Live execution streaming to the web UI (step_start/step_end events "
        "over WebSocket and SSE)."
    ),
    "scoring": "Per-step quality scoring listener feeding run evaluations.",
}


@router.get("/personas", response_model=ListPersonasResponse)
async def list_personas_route() -> ListPersonasResponse:
    """List selectable personas from the persona registry."""
    from ...langchain.personas import list_personas, resolve_persona_prompt

    personas: list[PersonaInfo] = []
    for persona in list_personas():
        prompt = resolve_persona_prompt(persona.id) or ""
        preview = prompt.strip()[:_PROMPT_PREVIEW_CHARS]
        personas.append(
            PersonaInfo(
                id=persona.id,
                name=persona.name,
                role=persona.role,
                description=persona.description,
                tags=list(persona.tags),
                prompt_preview=preview,
            )
        )
    return ListPersonasResponse(personas=personas)


@router.get("/tools", response_model=ListToolsResponse)
async def list_tools_route() -> ListToolsResponse:
    """List tools available for per-step allowlisting."""
    from ...langchain.tools import ALL_TOOLS, TIER_TOOLS

    tier_membership: dict[str, list[int]] = {}
    for tier, tools in sorted(TIER_TOOLS.items()):
        for tool in tools:
            tier_membership.setdefault(tool.name, []).append(tier)

    infos = [
        ToolInfo(
            name=tool.name,
            description=(tool.description or "").strip(),
            tiers=tier_membership.get(tool.name, []),
        )
        for tool in ALL_TOOLS
    ]
    return ListToolsResponse(tools=infos)


@router.get("/observers", response_model=ListObserversResponse)
async def list_observers_route() -> ListObserversResponse:
    """List observer channels a step can enable via ``observers``."""
    from ...langchain.config import KNOWN_OBSERVERS

    observers = [
        ObserverInfo(id=channel, description=_OBSERVER_DESCRIPTIONS.get(channel, ""))
        for channel in KNOWN_OBSERVERS
    ]
    return ListObserversResponse(observers=observers)
