"""Meta-agent that decomposes tasks and delegates to specialized agents."""

from __future__ import annotations

import asyncio
import json
import logging
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
        """Call LLM for orchestration."""
        if self.llm_client.backend is None:
            # Default implementation for testing
            return {
                "content": json.dumps(
                    {
                        "subtasks": [
                            {
                                "id": "generate",
                                "description": "Generate the code",
                                "capabilities": ["code_generation"],
                                "dependencies": [],
                                "parallel_group": 1,
                            },
                            {
                                "id": "review",
                                "description": "Review the generated code",
                                "capabilities": ["code_review"],
                                "dependencies": ["generate"],
                                "parallel_group": 2,
                            },
                        ],
                        "execution_order": ["generate", "review"],
                    }
                )
            }

        # Use real LLM client
        result_dict, model_used, tokens = await self.llm_client.complete_chat(
            messages=messages,
            tier=self.config.default_tier,
            temperature=0.2,  # Lower temp for structural task planning
        )

        return {"content": result_dict.get("content", result_dict.get("message", ""))}

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

    async def _execute_plan(self, task: OrchestratorInput) -> Any:
        """Execute the decomposed plan with fallback chain support."""
        # Group by dependencies for parallel execution
        executed: set[str] = set()
        results: dict[str, Any] = {}

        while len(executed) < len(self._subtasks):
            # Find tasks ready to execute
            ready = []
            for task_id, subtask in self._subtasks.items():
                if task_id in executed:
                    continue
                if all(dep in executed for dep in subtask.dependencies):
                    ready.append(subtask)

            if not ready:
                break  # No progress possible

            # Execute ready tasks (limited parallelism)
            batch = ready[: task.max_parallel]

            async def execute_subtask(st: SubTask) -> tuple[str, Any]:
                # Build candidate list: primary agent + fallbacks
                candidates: list[str] = []
                if st.assigned_agent:
                    candidates.append(st.assigned_agent)
                candidates.extend(self._fallback_chains.get(st.id, []))

                for agent_name in candidates:
                    agent = self._agents.get(agent_name)
                    if not agent:
                        continue
                    try:
                        task_input = self._resolve_task_input(st.description, agent)
                        result = await agent.run(task_input)
                        st.status = StepStatus.SUCCESS
                        st.result = result
                        return st.id, result
                    except Exception as e:
                        logger.warning(
                            "Agent %s failed for subtask %s: %s, " "trying fallback",
                            agent_name,
                            st.id,
                            e,
                        )
                        continue

                st.status = StepStatus.FAILED
                return st.id, {"error": f"All agents failed for subtask {st.id}"}

            batch_results = await asyncio.gather(
                *[execute_subtask(st) for st in batch], return_exceptions=True
            )

            for task_id, result in batch_results:
                if isinstance(result, Exception):
                    results[task_id] = {"error": str(result)}
                else:
                    results[task_id] = result
                executed.add(task_id)

                self._execution_trace.append(
                    {"task_id": task_id, "result": str(result)[:200]}
                )

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
