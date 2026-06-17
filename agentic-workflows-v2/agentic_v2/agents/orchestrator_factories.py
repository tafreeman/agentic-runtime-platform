"""Task-input factories for :mod:`.orchestrator`.

The orchestrator turns a free-form subtask description into the concrete
``TaskInput`` subclass each managed agent expects. These factories provide the
built-in mappings (reviewer -> :class:`CodeReviewInput`, coder ->
:class:`CodeGenerationInput`) and the one-time registration that wires them
onto :class:`OrchestratorAgent`.

All cross-module imports are deferred to call time, mirroring the original
in-method imports, so this module stays free of import-time coupling to the
contracts layer and the concrete agents (and so importing it never re-enters
:mod:`.orchestrator`).
"""

from __future__ import annotations

from typing import Any


def _reviewer_input_factory(description: str) -> Any:
    """Create CodeReviewInput for subtasks."""
    from ..contracts import CodeReviewInput

    return CodeReviewInput(
        code=f"# Task: {description}\n# (code to be reviewed)",
        language="python",
        context={"subtask_description": description},
    )


def _coder_input_factory(description: str) -> Any:
    """Create CodeGenerationInput for subtasks."""
    from ..contracts import CodeGenerationInput

    return CodeGenerationInput(
        description=description,
        language="python",
    )


def _register_default_factories() -> None:
    """Register default task input factories for built-in agent types."""
    from .coder import CoderAgent
    from .orchestrator import OrchestratorAgent
    from .reviewer import ReviewerAgent

    OrchestratorAgent.register_task_input_factory(
        ReviewerAgent, _reviewer_input_factory
    )
    OrchestratorAgent.register_task_input_factory(CoderAgent, _coder_input_factory)
