"""Meta-agent that decomposes tasks and delegates to specialized agents."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import Field

from ..contracts import StepStatus, TaskInput, TaskOutput, WorkflowResult
from ..engine import DAG, ExecutionContext, PipelineBuilder, run_pipeline
from ..engine.protocol import ExecutionEngine
from ..models import ModelTier
from .base import AgentConfig, BaseAgent, agent_to_step
from .capabilities import (
    Capability,
    CapabilitySet,
    CapabilityType,
    OrchestrationMixin,
    get_agent_capabilities,
)
from .json_extraction import extract_json

logger = logging.getLogger(__name__)


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


# Capability used for both the per-file local analysis passes and the
# cross-file integration pass — static analysis is the closest registered
# capability to "read this file and report what it contains".
_PER_FILE_CAPABILITY = CapabilityType.STATIC_ANALYSIS
_CROSS_FILE_CAPABILITY = CapabilityType.STATIC_ANALYSIS
_CROSS_FILE_TASK_ID = "cross_file_integration"


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


class OrchestratorAgent(
    BaseAgent[OrchestratorInput, OrchestratorOutput], OrchestrationMixin
):
    """Meta-agent that coordinates a pool of registered agents."""

    _task_input_factories: dict[type, Callable[[str], Any]] = {}

    @classmethod
    def register_task_input_factory(
        cls, agent_type: type, factory: Callable[[str], Any]
    ) -> None:
        """Register a task input factory for a specific agent type."""
        cls._task_input_factories[agent_type] = factory

    def __init__(
        self,
        config: AgentConfig | None = None,
        agents: dict[str, BaseAgent] | None = None,
        execution_engine: ExecutionEngine | None = None,
        **kwargs,
    ):
        if config is None:
            config = AgentConfig(
                name="orchestrator",
                description="Multi-agent orchestrator",
                system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
                default_tier=ModelTier.TIER_3,
                max_iterations=10,
            )

        super().__init__(config=config, **kwargs)
        self._execution_engine = execution_engine

        # Managed agents
        self._agents: dict[str, BaseAgent] = agents or {}
        self._agent_capabilities: dict[str, CapabilitySet] = {}

        # Execution state
        self._subtasks: dict[str, SubTask] = {}
        self._execution_trace: list[dict[str, Any]] = []

        # Fallback chain: subtask_id -> [agent_name, ...] in score order
        self._fallback_chains: dict[str, list[str]] = {}

        # Lazy-register built-in factories (once)
        if not OrchestratorAgent._task_input_factories:
            _register_default_factories()

    def _resolve_task_input(self, subtask_desc: str, target_agent: BaseAgent) -> Any:
        """Create the right TaskInput subclass for the given agent."""
        for cls in type(target_agent).__mro__:
            factory = self._task_input_factories.get(cls)
            if factory is not None:
                return factory(subtask_desc)

        # Default fallback
        from ..contracts import CodeGenerationInput

        return CodeGenerationInput(
            description=subtask_desc,
            language="python",
        )

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        """Register an agent for orchestration."""
        self._agents[name] = agent
        self._agent_capabilities[name] = get_agent_capabilities(agent)

    def unregister_agent(self, name: str) -> bool:
        """Unregister an agent."""
        if name in self._agents:
            del self._agents[name]
            del self._agent_capabilities[name]
            return True
        return False

    def _format_task_message(self, task: OrchestratorInput) -> str:
        """Format orchestration task."""
        agent_info = []
        for name, agent in self._agents.items():
            caps = self._agent_capabilities.get(name, CapabilitySet())
            cap_list = [c.value for c in caps.list_types()]
            agent_info.append(
                f"- {name}: {agent.config.description} (capabilities: {', '.join(cap_list)})"
            )

        parts = [
            f"Task to orchestrate:\n{task.task}",
            (
                "\nAvailable agents:\n" + "\n".join(agent_info)
                if agent_info
                else "\nNo agents registered"
            ),
            "\nConstraints:",
            f"- Max parallel tasks: {task.max_parallel}",
            f"- Review required: {task.require_review}",
            "\nDecompose this task and provide the execution plan in JSON format.",
        ]

        return "\n".join(parts)

    async def _is_task_complete(self, task: OrchestratorInput, response: str) -> bool:
        """Check if decomposition is complete."""
        try:
            data = self._extract_json(response)
            return "subtasks" in data
        except Exception:
            return False

    async def _parse_output(
        self, task: OrchestratorInput, response: str
    ) -> OrchestratorOutput:
        """Parse orchestration plan and execute."""
        try:
            plan = self._extract_json(response)
        except Exception:
            return OrchestratorOutput(
                success=False, error="Failed to parse execution plan", confidence=0.0
            )

        # Create subtasks
        subtasks = []
        for st_data in plan.get("subtasks", []):
            capabilities = [
                CapabilityType(c)
                for c in st_data.get("capabilities", [])
                if c in [ct.value for ct in CapabilityType]
            ]

            subtask = SubTask(
                id=st_data.get("id", f"task_{len(subtasks)}"),
                description=st_data.get("description", ""),
                required_capabilities=capabilities,
                dependencies=st_data.get("dependencies", []),
            )
            self._subtasks[subtask.id] = subtask
            subtasks.append(
                {
                    "id": subtask.id,
                    "description": subtask.description,
                    "capabilities": [c.value for c in subtask.required_capabilities],
                }
            )

        # Assign agents
        assignments = await self._assign_agents()

        # Execute (if agents available)
        final_result = None
        if self._agents:
            final_result = await self._execute_plan(task)

        return OrchestratorOutput(
            success=True,
            subtasks=subtasks,
            agent_assignments=assignments,
            final_result=final_result,
            execution_trace=self._execution_trace,
            confidence=0.85,
        )

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Call the LLM for orchestration.

        When a backend is configured the real LLM client drives decomposition.
        When it is not (the ``AGENTIC_NO_LLM`` / unit-test baseline) the plan is
        derived deterministically *from the task text itself* via
        :func:`_intent_decomposition` — not from a frozen ``generate``/``review``
        constant.  That makes capability-scored selection operational on the
        no-backend path: a "review" task yields a ``code_review`` subtask, a
        "test" task yields a ``test_generation`` subtask, and so on, so the right
        registered agent is actually scored and assigned.
        """
        task_text = _latest_user_text(messages)

        if self.llm_client.backend is None:
            return {"content": json.dumps(_intent_decomposition(task_text))}

        # Use real LLM client
        result_dict, _, _ = await self.llm_client.complete_chat(
            messages=messages,
            tier=self.config.default_tier,
            temperature=0.2,  # Lower temp for structural task planning
        )
        content = result_dict.get("content", result_dict.get("message", ""))

        # Defensive fallback: a placeholder backend (the AGENTIC_NO_LLM baseline)
        # returns prose with no JSON. Rather than yield an empty plan, derive a
        # capability-tagged plan from the task text so decomposition stays
        # operational and capability-scored selection still has subtasks to route.
        if not _has_extractable_json(content):
            return {"content": json.dumps(_intent_decomposition(task_text))}

        return {"content": content}

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract JSON from response using balanced-brace extraction."""
        return extract_json(text)

    async def _assign_agents(self) -> dict[str, str]:
        """Assign agents to subtasks based on capabilities."""
        assignments = {}

        for task_id, subtask in self._subtasks.items():
            required = CapabilitySet()
            for cap_type in subtask.required_capabilities:
                required.add(Capability(type=cap_type))

            # Score all agents and sort descending
            candidates: list[tuple[str, float]] = []
            for agent_name, agent_caps in self._agent_capabilities.items():
                score = agent_caps.score_match(required)
                if score > 0.0:
                    candidates.append((agent_name, score))

            candidates.sort(key=lambda pair: pair[1], reverse=True)

            if candidates:
                best_agent = candidates[0][0]
                subtask.assigned_agent = best_agent
                assignments[task_id] = best_agent
                # Store fallback chain (excluding primary)
                self._fallback_chains[task_id] = [name for name, _ in candidates[1:]]

        return assignments

    def _find_ready_subtasks(self, executed: set[str]) -> list[SubTask]:
        """Return subtasks whose dependencies are all satisfied and unrun."""
        ready = []
        for task_id, subtask in self._subtasks.items():
            if task_id in executed:
                continue
            if all(dep in executed for dep in subtask.dependencies):
                ready.append(subtask)
        return ready

    async def _execute_subtask_with_fallback(self, st: SubTask) -> tuple[str, Any]:
        """Run a single subtask, trying its primary agent then fallbacks.

        When every candidate agent fails, this emits a structured
        :class:`~agentic_v2.governance.HandoffSummary` (routed to the
        escalation gate) instead of a bare ``{"error": ...}``, so a human or a
        higher-tier recovery agent has the context to act.
        """
        # Build candidate list: primary agent + fallbacks
        candidates: list[str] = []
        if st.assigned_agent:
            candidates.append(st.assigned_agent)
        candidates.extend(self._fallback_chains.get(st.id, []))

        attempted: list[str] = []
        partial_results: dict[str, Any] = {}
        for agent_name in candidates:
            agent = self._agents.get(agent_name)
            if not agent:
                continue
            attempted.append(agent_name)
            try:
                task_input = self._resolve_task_input(st.description, agent)
                result = await agent.run(task_input)
                st.status = StepStatus.SUCCESS
                st.result = result
                return st.id, result
            except Exception as e:
                logger.warning(
                    "Agent %s failed for subtask %s: %s, trying fallback",
                    agent_name,
                    st.id,
                    e,
                )
                partial_results[agent_name] = f"{type(e).__name__}: {e}"
                continue

        st.status = StepStatus.FAILED
        handoff = await self._emit_escalation_handoff(st, attempted, partial_results)
        return st.id, handoff.to_dict()

    async def _emit_escalation_handoff(
        self,
        st: SubTask,
        attempted: list[str],
        partial_results: dict[str, Any],
    ) -> Any:
        """Build and route a structured handoff for an exhausted fallback chain."""
        from ..governance import HandoffSummary, route_handoff

        handoff = HandoffSummary.from_exhausted_chain(
            subtask_id=st.id,
            attempted_agents=attempted,
            partial_results=partial_results,
        )
        return await route_handoff(handoff)

    def _record_batch_results(
        self,
        batch_results: list[Any],
        results: dict[str, Any],
        executed: set[str],
        batch: list[SubTask] | None = None,
    ) -> None:
        """Merge a completed batch into *results* and mark tasks executed.

        ``_execute_plan`` gathers with ``return_exceptions=True``, so an element
        can be a bare ``BaseException`` rather than the expected
        ``(task_id, result)`` tuple (a subtask coroutine that raised before
        returning). Such an element is recorded as a failed subtask and skipped
        instead of failing the whole merge on a tuple-unpack error.
        """
        positions = batch or []
        for index, item in enumerate(batch_results):
            if isinstance(item, BaseException):
                # Recover the originating subtask id by position when available.
                failed_id = (
                    positions[index].id
                    if index < len(positions)
                    else f"unknown_{index}"
                )
                logger.warning(
                    "Subtask %s raised during batch execution: %s",
                    failed_id,
                    item,
                )
                results[failed_id] = {"error": str(item)}
                executed.add(failed_id)
                self._execution_trace.append(
                    {"task_id": failed_id, "result": str(item)[:200]}
                )
                continue

            task_id, result = item
            if isinstance(result, Exception):
                results[task_id] = {"error": str(result)}
            else:
                results[task_id] = result
            executed.add(task_id)

            self._execution_trace.append(
                {"task_id": task_id, "result": str(result)[:200]}
            )

    async def _execute_plan(self, task: OrchestratorInput) -> Any:
        """Execute the decomposed plan with fallback chain support."""
        # Group by dependencies for parallel execution
        executed: set[str] = set()
        results: dict[str, Any] = {}

        while len(executed) < len(self._subtasks):
            ready = self._find_ready_subtasks(executed)
            if not ready:
                break  # No progress possible

            # Execute ready tasks (limited parallelism)
            batch = ready[: task.max_parallel]
            batch_results = await asyncio.gather(
                *[self._execute_subtask_with_fallback(st) for st in batch],
                return_exceptions=True,
            )

            self._record_batch_results(batch_results, results, executed, batch)

        return results

    async def decompose_task(self, task: str) -> list[dict[str, Any]]:
        """Decompose a task into subtasks."""
        input_task = OrchestratorInput(task=task)
        self._memory.add_user(self._format_task_message(input_task))

        response = await self._get_model_response()
        content = response.get("content", "")

        try:
            plan = self._extract_json(content)
            return plan.get("subtasks", [])
        except Exception:
            return []

    # -------------------------------------------------------------------------
    # Adaptive decomposition (ARP-9): investigate -> per-file -> cross-file
    # -------------------------------------------------------------------------

    async def _investigate(self, task: str) -> InvestigationFindings:
        """Run the initial investigation step and return concrete findings.

        This is the first phase of adaptive decomposition: rather than planning
        the whole task up front, the coordinator inspects the task and reports
        only what it can observe — the files it touches and salient notes. Those
        findings *drive* the subtask set produced afterwards.

        With a backend configured, the investigation system prompt is sent to the
        LLM. Without one, findings are derived deterministically from the task
        text (file-like tokens become discovered files) so the adaptive path is
        exercised the same way in the no-key baseline.
        """
        prompt = (
            f"{INVESTIGATION_SYSTEM_PROMPT}\n\nTask to investigate:\n{task}\n\n"
            "Return the investigation JSON now."
        )
        messages = [{"role": "user", "content": prompt}]
        response = await self._call_model(messages)
        content = response.get("content", "")

        try:
            data = self._extract_json(content)
        except Exception:
            data = {}

        files = data.get("files")
        observations = data.get("observations")

        # No-backend / malformed-response fallback: derive findings from the task
        # text itself so the per-file branch still has something to fan out over.
        if not isinstance(files, list):
            files = _extract_file_tokens(task)
        if not isinstance(observations, list):
            observations = []

        return InvestigationFindings(
            files=tuple(str(f) for f in files if str(f).strip()),
            observations=tuple(str(o) for o in observations if str(o).strip()),
        )

    def _subtasks_from_findings(
        self, task: str, findings: InvestigationFindings
    ) -> AdaptiveDecomposition:
        """Generate subtasks *from* investigation findings (not a fixed plan).

        One local-analysis pass is emitted per discovered file, then a single
        cross-file integration pass is emitted that depends on every per-file
        pass. When the investigation found no files, there is nothing to analyze
        locally and the per-file tier is empty; the cross-file pass is only
        emitted when at least one per-file pass exists for it to integrate.
        """
        per_file: list[dict[str, Any]] = []
        for index, file_path in enumerate(findings.files):
            per_file.append(
                {
                    "id": _per_file_task_id(index),
                    "description": (
                        f"Local analysis pass over '{file_path}': summarize its "
                        "role, public surface, and anything relevant to: "
                        f"{task}"
                    ),
                    "capabilities": [_PER_FILE_CAPABILITY.value],
                    "dependencies": [],
                    "file": file_path,
                }
            )

        cross_file: dict[str, Any] | None = None
        if per_file:
            cross_file = {
                "id": _CROSS_FILE_TASK_ID,
                "description": (
                    "Cross-file integration pass: reconcile the per-file analyses "
                    f"into one coherent answer for: {task}. Resolve "
                    "inconsistencies across files and surface interactions."
                ),
                "capabilities": [_CROSS_FILE_CAPABILITY.value],
                "dependencies": [st["id"] for st in per_file],
                "observations": list(findings.observations),
            }

        return AdaptiveDecomposition(
            findings=findings,
            per_file=tuple(per_file),
            cross_file=cross_file,
        )

    async def decompose_adaptive(self, task: str) -> AdaptiveDecomposition:
        """Adaptively decompose *task* into per-file then cross-file passes.

        Phases:
            1. **Investigate** — discover which files/artifacts the task touches.
            2. **Per-file** — emit one local analysis subtask per discovered file.
            3. **Cross-file** — emit a single integration subtask that depends on
               every per-file pass.

        The generated subtasks are registered into ``self._subtasks`` (replacing
        any prior decomposition) so the existing assignment, fallback, and
        execution machinery (:meth:`_assign_agents`, :meth:`_execute_plan`) runs
        over the findings-derived plan unchanged.
        """
        findings = await self._investigate(task)
        decomposition = self._subtasks_from_findings(task, findings)
        self._register_subtasks(decomposition.subtasks)
        return decomposition

    def _register_subtasks(self, subtasks: list[dict[str, Any]]) -> None:
        """Install a freshly generated subtask plan into the orchestrator.

        Clears any prior decomposition state so a re-run does not accumulate
        stale subtasks or fallback chains, then materializes each plan entry as a
        :class:`SubTask`.
        """
        self._subtasks = {}
        self._fallback_chains = {}
        for st_data in subtasks:
            capabilities = [
                CapabilityType(c)
                for c in st_data.get("capabilities", [])
                if c in [ct.value for ct in CapabilityType]
            ]
            subtask = SubTask(
                id=st_data.get("id", f"task_{len(self._subtasks)}"),
                description=st_data.get("description", ""),
                required_capabilities=capabilities,
                dependencies=st_data.get("dependencies", []),
            )
            self._subtasks[subtask.id] = subtask

    async def run_adaptive(
        self, task: str, max_parallel: int = 3
    ) -> OrchestratorOutput:
        """End-to-end adaptive run: investigate, fan out per-file, then integrate.

        Ties :meth:`decompose_adaptive` to the existing assignment and execution
        machinery so the per-file passes run (in parallel, bounded by
        *max_parallel*) and the cross-file pass runs strictly after all of them.
        Returns the same :class:`OrchestratorOutput` shape as :meth:`run`, with
        the adaptive findings attached under ``execution_trace``.
        """
        decomposition = await self.decompose_adaptive(task)

        subtasks_view = [
            {
                "id": st.id,
                "description": st.description,
                "capabilities": [c.value for c in st.required_capabilities],
            }
            for st in self._subtasks.values()
        ]

        assignments = await self._assign_agents()

        final_result = None
        if self._agents:
            final_result = await self._execute_plan(
                OrchestratorInput(task=task, max_parallel=max_parallel)
            )

        trace = list(self._execution_trace)
        trace.append(
            {"phase": "investigation", "findings": decomposition.findings.to_dict()}
        )

        # An empty plan (the task named no files, so no per-file or cross-file
        # passes were produced) is a real no-op, not a success. Surface it as a
        # failure with an explanatory error rather than a silent success.
        if not subtasks_view:
            return OrchestratorOutput(
                success=False,
                error="adaptive decomposition produced no subtasks",
                subtasks=subtasks_view,
                agent_assignments=assignments,
                final_result=final_result,
                execution_trace=trace,
                confidence=0.0,
            )

        return OrchestratorOutput(
            success=True,
            subtasks=subtasks_view,
            agent_assignments=assignments,
            final_result=final_result,
            execution_trace=trace,
            confidence=0.85,
        )

    async def select_agent(
        self, task: dict[str, Any], available_agents: list[BaseAgent]
    ) -> BaseAgent | None:
        """Select best agent for a task."""
        capabilities = task.get("capabilities", [])
        required = CapabilitySet()
        for cap_name in capabilities:
            try:
                cap_type = CapabilityType(cap_name)
                required.add(Capability(type=cap_type))
            except ValueError:
                continue

        best_agent = None
        best_score = 0.0

        for agent in available_agents:
            agent_caps = get_agent_capabilities(agent)
            score = agent_caps.score_match(required)
            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent

    async def execute_as_dag(
        self, task: OrchestratorInput, ctx: ExecutionContext | None = None
    ) -> WorkflowResult:
        """Execute orchestrated task as a DAG for true parallel execution."""
        # First, decompose the task
        result = await self.run(task, ctx)

        if not result.success:
            return WorkflowResult(
                workflow_id=ctx.workflow_id if ctx else "",
                workflow_name=f"orchestrated:{task.task[:30]}",
                overall_status=StepStatus.FAILED,
            )

        # Ensure we have an ExecutionContext
        if ctx is None:
            ctx = ExecutionContext(workflow_id=f"orch-{task.task[:20]}")

        # Build DAG from subtasks with dependencies
        dag = DAG(
            name=f"orchestrated:{task.task[:30]}",
            description=f"DAG generated from task: {task.task}",
        )

        from ..engine.step import StepDefinition

        def _make_step_func(bound_agent, bound_input):
            """Create a step function with bound agent and task input."""

            async def run_subtask(step_ctx: ExecutionContext) -> dict[str, Any]:
                r = await bound_agent.run(bound_input, step_ctx)
                return {"result": r}

            return run_subtask

        for subtask_data in result.subtasks:
            agent_name = result.agent_assignments.get(subtask_data["id"])
            agent = self._agents.get(agent_name or "")

            if agent:
                subtask_input = self._resolve_task_input(
                    subtask_data["description"], agent
                )

                step = StepDefinition(
                    name=subtask_data["id"],
                    description=subtask_data["description"],
                    func=_make_step_func(agent, subtask_input),
                    tier=agent.config.default_tier,
                    timeout_seconds=agent.config.timeout_seconds,
                )
                step.depends_on = subtask_data.get("dependencies", [])
                dag.add(step)

        # Execute DAG with max parallelism via injected engine (or registry default)
        engine = self._execution_engine
        if engine is None:
            from ..adapters.registry import get_registry

            engine = get_registry().get_adapter("native")
        return await engine.execute(dag, ctx, max_concurrency=task.max_parallel)

    async def execute_as_pipeline(
        self, task: OrchestratorInput, ctx: ExecutionContext | None = None
    ) -> WorkflowResult:
        """Execute orchestrated task as a pipeline (legacy)."""
        # First, decompose the task
        result = await self.run(task, ctx)

        if not result.success:
            return WorkflowResult(
                workflow_id=ctx.workflow_id if ctx else "",
                workflow_name=f"orchestrated:{task.task[:30]}",
                overall_status=StepStatus.FAILED,
            )

        # Build pipeline from subtasks
        builder = PipelineBuilder(f"orchestrated:{task.task[:30]}")

        for subtask_data in result.subtasks:
            agent_name = result.agent_assignments.get(subtask_data["id"])
            agent = self._agents.get(agent_name or "")

            if agent:
                step = agent_to_step(agent, subtask_data["id"])
                step.description = subtask_data["description"]
                builder.step(step)

        pipeline = builder.build()
        return await run_pipeline(pipeline, ctx)


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
    from .reviewer import ReviewerAgent

    OrchestratorAgent.register_task_input_factory(
        ReviewerAgent, _reviewer_input_factory
    )
    OrchestratorAgent.register_task_input_factory(CoderAgent, _coder_input_factory)
