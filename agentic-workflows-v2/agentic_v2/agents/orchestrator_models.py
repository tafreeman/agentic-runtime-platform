"""Data structures, I/O schemas, and prompts for :mod:`.orchestrator`.

This module holds the value objects the orchestrator passes around — the
subtask record, the immutable adaptive-decomposition results, and the
Pydantic input/output contracts — plus the system prompts and the small set
of capability constants used by the adaptive (investigate -> per-file ->
cross-file) decomposition path.

It deliberately depends only on :mod:`..contracts` and :mod:`.capabilities`
so it carries no orchestration logic and can be imported without pulling in
the engine. :class:`OrchestratorAgent` (in :mod:`.orchestrator`) consumes
everything defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import Field

from ..contracts import StepStatus, TaskInput, TaskOutput
from .capabilities import CapabilityType


@dataclass
class SubTask:
    """A single subtask produced by the orchestrator's task decomposition."""

    id: str
    description: str
    required_capabilities: list[CapabilityType]
    dependencies: list[str] = field(default_factory=list)
    assigned_agent: str | None = None
    result: Any | None = None
    status: StepStatus = StepStatus.PENDING


@dataclass(frozen=True)
class InvestigationFindings:
    """Immutable result of the orchestrator's initial investigation step.

    The investigation phase of adaptive decomposition discovers what the task
    actually touches *before* any analysis subtask is generated.  ``files`` is
    the concrete list of artifacts found (each becomes its own per-file local
    analysis pass); ``observations`` are free-form notes that seed the cross-file
    integration pass.
    """

    files: tuple[str, ...] = ()
    observations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the findings."""
        return {
            "files": list(self.files),
            "observations": list(self.observations),
        }


@dataclass(frozen=True)
class AdaptiveDecomposition:
    """Immutable output of :meth:`OrchestratorAgent.decompose_adaptive`.

    Captures the full adaptive trajectory: the ``findings`` from the initial
    investigation, the ``per_file`` subtasks derived from those findings (one
    local analysis pass per discovered file), and the single ``cross_file``
    integration subtask that depends on every per-file pass.

    ``subtasks`` is the flattened, dependency-ordered plan (investigation is not
    re-emitted as a subtask — it has already run to produce ``findings``).
    """

    findings: InvestigationFindings
    per_file: tuple[dict[str, Any], ...]
    cross_file: dict[str, Any] | None

    @property
    def subtasks(self) -> list[dict[str, Any]]:
        """Flatten per-file passes followed by the cross-file pass."""
        plan: list[dict[str, Any]] = list(self.per_file)
        if self.cross_file is not None:
            plan.append(self.cross_file)
        return plan

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the decomposition."""
        return {
            "findings": self.findings.to_dict(),
            "per_file": list(self.per_file),
            "cross_file": self.cross_file,
            "subtasks": self.subtasks,
        }


class OrchestratorInput(TaskInput):
    """Input schema for OrchestratorAgent."""

    task: str = Field(default="", description="Task description to orchestrate")
    available_agents: list[str] = Field(
        default_factory=list, description="Available agent names"
    )
    max_parallel: int = Field(default=3, description="Max parallel tasks")
    require_review: bool = Field(default=True, description="Whether review is required")


class OrchestratorOutput(TaskOutput):
    """Output schema produced by OrchestratorAgent."""

    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    agent_assignments: dict[str, str] = Field(default_factory=dict)
    final_result: Any | None = Field(default=None)
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)


ORCHESTRATOR_SYSTEM_PROMPT = """You are an expert task orchestrator that coordinates multiple AI agents.

Your responsibilities:
1. Analyze complex tasks and break them into subtasks
2. Identify required capabilities for each subtask
3. Assign subtasks to appropriate agents
4. Aggregate results and ensure quality

When decomposing tasks, provide JSON with this structure:
{
    "subtasks": [
        {
            "id": "unique_id",
            "description": "What needs to be done",
            "capabilities": ["code_generation", "test_generation"],
            "dependencies": ["id_of_dependent_task"],
            "parallel_group": 1
        }
    ],
    "execution_order": ["id1", "id2"],
    "validation_steps": ["How to validate the result"]
}"""


INVESTIGATION_SYSTEM_PROMPT = """You are an investigation agent that runs the FIRST step of an adaptive task decomposition.

You do NOT plan the whole task up front. Instead you inspect the task and report
only what you can concretely observe: which files/artifacts it touches and any
salient observations. A later step turns each discovered file into its own local
analysis pass, then a separate cross-file integration pass reasons over those
per-file results.

Respond with JSON of exactly this shape:
{
    "files": ["path/or/name/of/each/file/the/task/touches"],
    "observations": ["short factual note", "another note"]
}

Rules:
- List every distinct file the task references or implies, one entry each.
- If the task names no files, return an empty "files" list — do NOT invent paths.
- Keep observations factual and short; they seed the cross-file pass."""


# Capability used for both the per-file local analysis passes and the
# cross-file integration pass — static analysis is the closest registered
# capability to "read this file and report what it contains".
_PER_FILE_CAPABILITY = CapabilityType.STATIC_ANALYSIS
_CROSS_FILE_CAPABILITY = CapabilityType.STATIC_ANALYSIS
_CROSS_FILE_TASK_ID = "cross_file_integration"
