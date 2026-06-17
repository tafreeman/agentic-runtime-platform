"""Deterministic planning helpers for :mod:`.orchestrator`.

These pure functions back the no-backend (``AGENTIC_NO_LLM`` / unit-test)
decomposition path and the message bookkeeping the orchestrator needs when it
talks to the model. They are intentionally free of any orchestrator state so
they can be unit-tested in isolation:

* :func:`_intent_decomposition` derives a capability-tagged plan straight from
  the task text, so capability-scored agent selection still has subtasks to
  route when no LLM is configured.
* :func:`_extract_file_tokens` mines file-like tokens from a task description
  to seed the per-file branch of adaptive decomposition.
* :func:`_latest_user_text` / :func:`_has_extractable_json` /
  :func:`_per_file_task_id` are small bookkeeping utilities.

:class:`OrchestratorAgent` (in :mod:`.orchestrator`) imports and calls these.
"""

from __future__ import annotations

import re
from typing import Any

from .capabilities import CapabilityType
from .json_extraction import extract_json


def _per_file_task_id(index: int) -> str:
    """Stable id for the *index*-th per-file local analysis pass."""
    return f"per_file_{index}"


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    """Return the content of the most recent user message (or "")."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _has_extractable_json(content: str) -> bool:
    """Return True when *content* contains a JSON object the parser can read."""
    if not content:
        return False
    try:
        extract_json(content)
        return True
    except Exception:
        return False


# A token looks like a file when it carries a dotted extension (``a/b.py``,
# ``config.yaml``). The stem (text before the final dot) must contain at least
# one ALPHABETIC char and the extension must START with a letter, so numeric
# tokens ("2.0", "99.9", "3.11", "4.50") and Latin abbreviations are not mistaken
# for files. The stem allows path separators/dots/hyphens/underscores so nested
# paths still match.
_FILE_TOKEN_RE = re.compile(
    r"(?P<stem>[A-Za-z0-9_./\\-]*[A-Za-z][A-Za-z0-9_./\\-]*)"
    r"\.(?P<ext>[A-Za-z][A-Za-z0-9]{0,7})"
)

# Latin/prose abbreviations that match the file shape (alpha stem + letter ext)
# but are never files. Compared case-insensitively against the whole token.
_FILE_TOKEN_ABBREVIATIONS: frozenset[str] = frozenset(
    {"e.g", "i.e", "etc", "vs", "et.al"}
)


def _extract_file_tokens(task: str) -> list[str]:
    """Extract file-like tokens from *task* text, de-duplicated in order.

    Used as the no-backend / fallback investigation: when the LLM is not
    available to report discovered files, any path/extension-shaped token in the
    task description is treated as a file to analyze locally. Version numbers,
    percentages, and decimals (numeric stems) and a curated set of Latin prose
    abbreviations ("e.g.", "i.e.", ...) are rejected so they do not fabricate
    phantom per-file subtasks.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _FILE_TOKEN_RE.finditer(task):
        token = match.group(0).strip(".")
        if not token or token.lower() in _FILE_TOKEN_ABBREVIATIONS:
            continue
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


# Intent keyword -> the capability a matching subtask should require. Ordered so
# the emitted plan reads naturally (generate, then test, then review/analyze).
_INTENT_RULES: tuple[tuple[tuple[str, ...], str, CapabilityType], ...] = (
    (
        ("generat", "build", "create", "implement", "write code", "add"),
        "Generate the implementation",
        CapabilityType.CODE_GENERATION,
    ),
    (
        ("test", "pytest", "coverage"),
        "Generate tests for the implementation",
        CapabilityType.TEST_GENERATION,
    ),
    (
        ("review", "audit", "inspect"),
        "Review the implementation",
        CapabilityType.CODE_REVIEW,
    ),
    (
        ("analyz", "analyse", "investigate", "examine"),
        "Statically analyze the implementation",
        CapabilityType.STATIC_ANALYSIS,
    ),
)


def _intent_decomposition(task_text: str) -> dict[str, Any]:
    """Derive a capability-tagged plan from the *task_text* keywords.

    Replaces the previous frozen ``generate``/``review`` constant on the
    no-backend path. Each matched intent contributes one subtask requiring the
    mapped capability, chained in declaration order so capability-scored
    assignment picks the right registered agent for each. Falls back to a single
    code-generation subtask when no keyword matches, so a plan is always
    produced.
    """
    lowered = task_text.lower()
    subtasks: list[dict[str, Any]] = []
    previous_id: str | None = None

    for keywords, description, capability in _INTENT_RULES:
        if any(keyword in lowered for keyword in keywords):
            task_id = capability.value
            subtasks.append(
                {
                    "id": task_id,
                    "description": description,
                    "capabilities": [capability.value],
                    "dependencies": [previous_id] if previous_id else [],
                }
            )
            previous_id = task_id

    if not subtasks:
        subtasks.append(
            {
                "id": CapabilityType.CODE_GENERATION.value,
                "description": "Complete the requested task",
                "capabilities": [CapabilityType.CODE_GENERATION.value],
                "dependencies": [],
            }
        )

    return {
        "subtasks": subtasks,
        "execution_order": [st["id"] for st in subtasks],
    }
