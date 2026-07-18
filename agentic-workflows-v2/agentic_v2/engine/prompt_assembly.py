"""Prompt assembly — system prompt loading, context formatting, and tool descriptions.

Responsible for constructing the full prompt fed to each LLM-backed step:

1. :func:`load_agent_system_prompt` — resolve and read the Markdown persona file
   for a given agent name.
2. :func:`build_context_block` — serialize the execution-context variable map
   into an indented JSON block for inclusion in the prompt.
3. :func:`format_tool_descriptions` — render a human-readable list of available
   tool names for inclusion in the prompt preamble.
4. :func:`build_system_prompt` — compose the complete prompt string (persona,
   task, context, artifact key list, tooling notice, sentinel contract).

The sentinel output contract constant :data:`SENTINEL_OUTPUT_INSTRUCTIONS` is
exported so the engine can append it consistently regardless of which persona
prompt is loaded.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..prompts.registry import default_registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Directory containing agent-specific system prompt Markdown files.
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# ---------------------------------------------------------------------------
# Universal output format instructions — always appended to every LLM step.
# Prompt files describe agent expertise/persona; this block enforces the
# output contract so it never depends on individual prompt file contents.
# ---------------------------------------------------------------------------

SENTINEL_OUTPUT_INSTRUCTIONS = """
## Output Format (REQUIRED — engine contract)

Your response MUST use sentinel artifact blocks:

<<<ARTIFACT key>>>
FILE: path/to/file.ext
<full file content — no truncation>
ENDFILE
<<<ENDARTIFACT>>>

For structured data (JSON) use:

<<<ARTIFACT key>>>
{"field": "value", ...}
<<<ENDARTIFACT>>>

Rules:
- One <<<ARTIFACT key>>> block per logical output (e.g. backend_code, review_report)
- FILE/ENDFILE inside code artifacts; raw JSON inside data artifacts
- ENDFILE on its own line; <<<ENDARTIFACT>>> on its own line
- Complete files only — no truncation, no TODO stubs
""".strip()

# Backward-compatibility alias
_SENTINEL_OUTPUT_INSTRUCTIONS = SENTINEL_OUTPUT_INSTRUCTIONS


# ---------------------------------------------------------------------------
# Persona prompt loading
# ---------------------------------------------------------------------------


def load_agent_system_prompt(
    agent_name: str,
    prompt_file_override: str | None = None,
) -> str | None:
    """Return the Markdown persona prompt for *agent_name*, or None.

    Resolution order:

    1. Explicit ``prompt_file_override`` from the YAML step definition
       (always a direct file read -- overrides bypass the registry).
    2. ``prompts/<role>.md`` where ``<role>`` is the suffix after the tier
       prefix (e.g. ``tier2_coder`` → ``coder.md``), resolved via the
       shared :func:`default_registry` (ADR-056) when the role is
       registered, falling back to a direct file read otherwise.
    3. ``prompts/default.md`` fallback.

    Note: Output format instructions are injected separately by the step
    factory via :data:`SENTINEL_OUTPUT_INSTRUCTIONS` — prompt files only need
    to describe the agent's persona/expertise.
    """
    # 1. Explicit override
    if prompt_file_override:
        override_path = _PROMPTS_DIR / prompt_file_override
        if override_path.exists():
            return override_path.read_text(encoding="utf-8")
        logger.warning(
            "prompt_file '%s' for agent '%s' not found in %s; "
            "falling back to role-based lookup.",
            prompt_file_override,
            agent_name,
            _PROMPTS_DIR,
        )

    # 2. Role-based lookup
    if "_" in agent_name:
        role = agent_name.split("_", 1)[1]  # "tier2_coder" → "coder"
        record = default_registry().get_or_none(role)
        if record is not None:
            logger.debug(
                "Resolved persona prompt for role '%s' from registry (%s).",
                role,
                record.qualified_version,
            )
            # The registry lives outside the strict-mypy surface, so its
            # attributes arrive as Any under --follow-imports=skip; pin the
            # declared return type at the boundary.
            content: str = record.content
            return content
        role_path = _PROMPTS_DIR / f"{role}.md"
        if role_path.exists():
            return role_path.read_text(encoding="utf-8")

    # 3. Default fallback
    default_path = _PROMPTS_DIR / "default.md"
    if default_path.exists():
        return default_path.read_text(encoding="utf-8")

    logger.debug(
        "No system prompt found for agent '%s'; using inline output instructions only.",
        agent_name,
    )
    return None


# Backward-compatibility alias
_load_agent_system_prompt = load_agent_system_prompt


# ---------------------------------------------------------------------------
# Tool contract resolution (parameter spec conversion)
# ---------------------------------------------------------------------------


def parameter_spec_to_json_schema(spec: Any) -> dict[str, Any]:
    """Convert internal tool parameter spec to JSON schema object."""
    if not isinstance(spec, dict):
        return {"type": "string"}

    normalized: dict[str, Any] = {}
    for key, value in spec.items():
        if key == "required":
            continue
        normalized[key] = value

    normalized.setdefault("type", "string")
    return normalized


# Backward-compatibility alias
_parameter_spec_to_json_schema = parameter_spec_to_json_schema


# ---------------------------------------------------------------------------
# Context serialization helpers
# ---------------------------------------------------------------------------


def build_context_block(all_vars: dict[str, Any]) -> str:
    """Serialize execution-context variables as an indented JSON block.

    Returns a ready-to-embed string (no surrounding labels).  Callers are
    responsible for adding a ``"Available context:"`` label before the block.
    """
    return json.dumps(all_vars, indent=2, default=str)


def format_tool_descriptions(tool_names: list[str]) -> str:
    """Return a comma-separated list of sorted tool names for prompt embedding."""
    return ", ".join(sorted(tool_names))


# ---------------------------------------------------------------------------
# Full prompt assembly
# ---------------------------------------------------------------------------


def build_system_prompt(
    agent_name: str,
    description: str,
    all_vars: dict[str, Any],
    expected_output_keys: list[str] | None,
    bound_tool_names: list[str],
    persona_prompt: str | None,
) -> str:
    """Compose the complete prompt string for a single LLM step invocation.

    Assembly order:

    1. Agent persona (Markdown, if available).
    2. Agent name, task description, and serialized execution context.
    3. Required artifact key list (when ``expected_output_keys`` is provided).
    4. Tooling notice (when bound tools are present).
    5. :data:`SENTINEL_OUTPUT_INSTRUCTIONS` — always appended last.

    Args:
        agent_name: Logical agent identifier (e.g. ``tier2_coder``).
        description: Human-readable task description from the YAML step.
        all_vars: Flattened execution-context variable map.
        expected_output_keys: Keys that MUST appear as <<<ARTIFACT>>> blocks,
            or ``None`` if unconstrained.
        bound_tool_names: Names of tools available to this step (may be empty).
        persona_prompt: Pre-loaded Markdown persona text, or ``None``.

    Returns:
        Fully assembled prompt string ready to pass as the ``user`` message.
    """
    prompt_parts: list[str] = []

    # 1. Agent persona
    if persona_prompt:
        prompt_parts += [persona_prompt, "", "---", ""]

    # 2. Task + context
    prompt_parts += [
        f"You are acting as agent '{agent_name}'.",
        f"Task: {description}",
        "",
        "Available context:",
        build_context_block(all_vars),
        "",
    ]

    # 3. Required artifact keys
    if expected_output_keys:
        prompt_parts += [
            "Your response MUST include <<<ARTIFACT key>>> blocks for: "
            + ", ".join(expected_output_keys)
            + ".",
            "",
        ]

    # 4. Tooling notice
    if bound_tool_names:
        prompt_parts += [
            "Tooling access is enabled for this step.",
            "Use tools to fetch facts or inspect artifacts instead of guessing.",
            "Available tools: " + format_tool_descriptions(bound_tool_names) + ".",
            "",
        ]

    # 5. Universal output format contract (always appended)
    prompt_parts += [SENTINEL_OUTPUT_INSTRUCTIONS, ""]

    return "\n".join(prompt_parts)
