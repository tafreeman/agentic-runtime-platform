"""Prompt templates for agentic_v2 agents.

This module provides system prompts for various agent roles. Prompts are
stored as markdown files and loaded dynamically.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

# Directory containing prompt templates
PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
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
    if not name.endswith(".md"):
        name = f"{name}.md"

    prompt_path = PROMPTS_DIR / name
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {name}")

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
]
