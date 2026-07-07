"""Persona registry — pre-canned agent personas selectable per step.

Personas are declared in ``config/defaults/personas.yaml``. Each entry maps a
stable ``id`` to a display name, role, and a system prompt (inline ``prompt``
or a ``prompt_file`` under ``agentic_v2/prompts/``). A workflow step opts in
with ``persona: <id>``; :func:`resolve_persona_prompt` returns the prompt text
the agent factory should use.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_PERSONAS_PATH = Path(__file__).parent.parent / "config" / "defaults" / "personas.yaml"
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@dataclass(frozen=True)
class Persona:
    """A single pre-canned persona definition."""

    id: str
    name: str
    role: str = ""
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    prompt: str | None = None
    prompt_file: str | None = None


def _parse_persona(raw: object) -> Persona | None:
    """Parse one raw YAML entry into a ``Persona``, or None when malformed."""
    if not isinstance(raw, dict):
        return None
    persona_id = raw.get("id")
    if not isinstance(persona_id, str) or not persona_id.strip():
        return None
    tags = raw.get("tags")
    return Persona(
        id=persona_id.strip(),
        name=str(raw.get("name", persona_id)),
        role=str(raw.get("role", "")),
        description=str(raw.get("description", "")),
        tags=tuple(str(t) for t in tags) if isinstance(tags, list) else (),
        prompt=raw.get("prompt") if isinstance(raw.get("prompt"), str) else None,
        prompt_file=(
            raw.get("prompt_file") if isinstance(raw.get("prompt_file"), str) else None
        ),
    )


@functools.lru_cache(maxsize=1)
def _load_personas(path: str) -> tuple[Persona, ...]:
    """Load and cache the persona registry from a YAML file path."""
    personas_path = Path(path)
    if not personas_path.exists():
        logger.warning("Persona registry not found at %s", personas_path)
        return ()
    try:
        data = yaml.safe_load(personas_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.error("Persona registry at %s is invalid YAML: %s", personas_path, exc)
        return ()
    if not isinstance(data, dict):
        return ()
    raw_personas = data.get("personas")
    if not isinstance(raw_personas, list):
        # A present-but-blank `personas:` key parses as None.
        return ()
    parsed = (_parse_persona(raw) for raw in raw_personas)
    return tuple(p for p in parsed if p is not None)


def list_personas() -> list[Persona]:
    """Return every persona declared in the registry, in file order."""
    return list(_load_personas(str(_PERSONAS_PATH)))


def get_persona(persona_id: str) -> Persona | None:
    """Look up a persona by id, or None when unknown."""
    for persona in _load_personas(str(_PERSONAS_PATH)):
        if persona.id == persona_id:
            return persona
    return None


def resolve_persona_prompt(persona_id: str) -> str | None:
    """Return the system prompt text for a persona id, or None when unresolvable.

    Inline ``prompt`` text wins; otherwise ``prompt_file`` is read from the
    package prompts directory. Missing files resolve to None so the agent
    factory can fall back to its role-based resolution.
    """
    persona = get_persona(persona_id)
    if persona is None:
        logger.warning("Unknown persona id %r; falling back to role prompt", persona_id)
        return None
    if persona.prompt:
        return persona.prompt
    if persona.prompt_file:
        prompt_path = _PROMPTS_DIR / persona.prompt_file
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        logger.warning(
            "Persona %r prompt_file %s not found under %s",
            persona_id,
            persona.prompt_file,
            _PROMPTS_DIR,
        )
    return None
