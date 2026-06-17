"""Meta-agent that decomposes tasks and delegates to specialized agents.

This module is the public home of :class:`OrchestratorAgent`. The agent's
value objects, prompts, deterministic planning helpers, and task-input
factories live in sibling modules (:mod:`.orchestrator_models`,
:mod:`.orchestrator_planning`, :mod:`.orchestrator_factories`); they are
re-exported here so the historical import surface
(``from agentic_v2.agents.orchestrator import X``) is unchanged.

``get_agent_capabilities`` is imported into this module's namespace on
purpose: :meth:`OrchestratorAgent.register_agent` resolves it as a module
global, and the behavioral test-suite monkeypatches
``agentic_v2.agents.orchestrator.get_agent_capabilities`` to inject stub
capability sets. Keep that name resolving here.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from ..contracts import StepStatus, WorkflowResult
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
from .orchestrator_factories import (
    _coder_input_factory,
    _register_default_factories,
    _reviewer_input_factory,
)
from .orchestrator_models import (
    _CROSS_FILE_CAPABILITY,
    _CROSS_FILE_TASK_ID,
    _PER_FILE_CAPABILITY,
    INVESTIGATION_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    AdaptiveDecomposition,
    InvestigationFindings,
    OrchestratorInput,
    OrchestratorOutput,
    SubTask,
)
from .orchestrator_planning import (
    _extract_file_tokens,
    _has_extractable_json,
    _intent_decomposition,
    _latest_user_text,
    _per_file_task_id,
)

logger = logging.getLogger(__name__)


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
        subtasks: list[dict[str, Any]] = []
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
        from .json_extraction import extract_json

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


__all__ = [
    # Agent
    "OrchestratorAgent",
    # I/O contracts and value objects (re-exported from .orchestrator_models)
    "OrchestratorInput",
    "OrchestratorOutput",
    "SubTask",
    "InvestigationFindings",
    "AdaptiveDecomposition",
    # Prompts and capability constants (re-exported from .orchestrator_models)
    "ORCHESTRATOR_SYSTEM_PROMPT",
    "INVESTIGATION_SYSTEM_PROMPT",
    "_PER_FILE_CAPABILITY",
    "_CROSS_FILE_CAPABILITY",
    "_CROSS_FILE_TASK_ID",
    # Deterministic planning helpers (re-exported from .orchestrator_planning)
    "_intent_decomposition",
    "_extract_file_tokens",
    "_latest_user_text",
    "_has_extractable_json",
    "_per_file_task_id",
    # Task-input factories (re-exported from .orchestrator_factories)
    "_reviewer_input_factory",
    "_coder_input_factory",
    "_register_default_factories",
    # Capability lookup — kept importable here because the behavioral suite
    # monkeypatches ``agentic_v2.agents.orchestrator.get_agent_capabilities``.
    "get_agent_capabilities",
]
