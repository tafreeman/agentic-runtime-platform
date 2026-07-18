"""Prompt templates for agentic_v2 agents.

This module provides system prompts for various agent roles. Prompts are
stored as markdown files and loaded dynamically.

:func:`load_prompt` is now backed by the versioning registry in
:mod:`agentic_v2.prompts.registry` (see
``docs/adr/ADR-056-prompt-versioning-registry.md``): it resolves through
the shared :func:`default_registry` first, so callers see the same
LF-normalized, fingerprinted content as the engine's persona lookup
(:func:`agentic_v2.engine.prompt_assembly.load_agent_system_prompt`), and
falls back to a direct file read for any name the default registry does
not carry.
"""

from __future__ import annotations

from pathlib import Path

from .registry import (
    PROMPT_VERSIONS,
    PromptRecord,
    PromptRegistry,
    compute_content_hash,
    default_registry,
    normalize_prompt_text,
)

# Directory containing prompt templates
PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a prompt template by name.

    Args:
        name: Prompt name (e.g., 'architect', 'coder', 'tester')
              Extension '.md' is optional.

    Returns:
        The prompt content as a string.

    Raises:
        FileNotFoundError: If prompt file doesn't exist.
    """
    stem = name[: -len(".md")] if name.endswith(".md") else name

    record = default_registry().get_or_none(stem)
    if record is not None:
        return record.content

    prompt_path = PROMPTS_DIR / f"{stem}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {stem}.md")

    return prompt_path.read_text(encoding="utf-8")


def list_prompts() -> list[str]:
    """List all available prompt names.

    Returns:
        List of prompt names (without .md extension).
    """
    return [p.stem for p in PROMPTS_DIR.glob("*.md")]


def get_prompt_path(name: str) -> Path | None:
    """Get the path to a prompt file.

    Args:
        name: Prompt name (without .md extension).

    Returns:
        Path to the prompt file, or None if not found.
    """
    prompt_path = PROMPTS_DIR / f"{name}.md"
    return prompt_path if prompt_path.exists() else None


# Pre-defined prompt names matching actual .md files on disk.
# Kept in sync with prompts/*.md — run `list_prompts()` to verify.
ARCHITECT = "architect"
CODER = "coder"
ORCHESTRATOR = "orchestrator"
PLANNER = "planner"
REVIEWER = "reviewer"
TESTER = "tester"
VALIDATOR = "validator"

__all__ = [
    "load_prompt",
    "list_prompts",
    "get_prompt_path",
    "PROMPTS_DIR",
    # Prompt name constants (alphabetical, matches prompts/*.md)
    "ARCHITECT",
    "CODER",
    "ORCHESTRATOR",
    "PLANNER",
    "REVIEWER",
    "TESTER",
    "VALIDATOR",
    # Re-exported from .registry (ADR-056)
    "PROMPT_VERSIONS",
    "PromptRecord",
    "PromptRegistry",
    "compute_content_hash",
    "default_registry",
    "normalize_prompt_text",
]
