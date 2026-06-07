"""Agent specialized for system architecture design.

Provides :class:`ArchitectAgent`, a :class:`~agentic_v2.agents.base.BaseAgent`
subclass that takes system requirements and produces structured architecture
recommendations including tech stack choices with justifications, Mermaid
component diagrams, API strategy, data flow descriptions, deployment
architecture, scalability analysis, and security considerations.

Output is returned as :class:`ArchitectureOutput` with parsed
:class:`TechStackChoice` entries extracted from the LLM's JSON response.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from ..contracts import TaskInput, TaskOutput
from ..models import ModelTier
from .base import AgentConfig, BaseAgent
from .json_extraction import extract_json


class ArchitectureInput(TaskInput):
    """Input schema for the :class:`ArchitectAgent`.

    Attributes:
        requirements: System requirements to design for (required,
            non-empty).
        arch_constraints: Architecture-level constraints (e.g., cloud
            provider restrictions, latency budgets).  Distinct from the
            inherited ``TaskInput.constraints`` field.
        user_stories: Optional user stories to inform the design.
        existing_architecture: Description of an existing system to
            extend or integrate with.
        preferences: Technology preference hints (e.g.,
            ``{"database": "PostgreSQL"}``).
    """

    requirements: str = Field(
        description="System requirements to design for", min_length=1
    )
    arch_constraints: str | None = Field(
        default=None,
        description="Architecture constraints (not to be confused with TaskInput.constraints)",
    )
    user_stories: str | None = Field(
        default=None, description="User stories to consider"
    )
    existing_architecture: str | None = Field(
        default=None, description="Existing architecture to extend or integrate with"
    )
    preferences: dict[str, Any] = Field(
        default_factory=dict, description="Technology preferences"
    )


class TechStackChoice(BaseModel):
    """A single technology choice in the architecture's tech stack.

    Attributes:
        name: Name of the chosen technology (e.g., ``"React"``,
            ``"PostgreSQL"``).
        justification: Rationale for selecting this technology.
        alternatives: Other technologies considered but not selected.
    """

    name: str = Field(default="", description="Technology name")
    justification: str = Field(default="", description="Why this choice")
    alternatives: list[str] = Field(
        default_factory=list, description="Alternative options considered"
    )


class ArchitectureOutput(TaskOutput):
    """Structured output from the :class:`ArchitectAgent`.

    Attributes:
        tech_stack: Mapping of stack layer (e.g., ``"frontend"``,
            ``"backend"``, ``"database"``) to :class:`TechStackChoice`.
        component_diagram: Mermaid-syntax diagram of system components.
        api_strategy: API design decisions (type, versioning,
            authentication, rate limiting).
        data_flow: Textual description of data flow through the system.
        deployment: Deployment strategy details (environments, CI/CD).
        scalability: Scalability analysis (bottlenecks, recommendations).
        security: Security considerations (auth, authorization, data
            protection, compliance).
        raw_response: Unprocessed model response for debugging.
    """

    tech_stack: dict[str, TechStackChoice] = Field(default_factory=dict)
    component_diagram: str = Field(default="", description="Mermaid diagram")
    api_strategy: dict[str, Any] = Field(default_factory=dict)
    data_flow: str = Field(default="", description="Data flow description")
    deployment: dict[str, Any] = Field(default_factory=dict)
    scalability: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    raw_response: str = Field(default="", description="Raw model response")


SYSTEM_PROMPT = """You are a senior software architect with expertise in full-stack application design.

Your task is to design comprehensive system architecture including:
1. Tech stack recommendation with justification for each choice
2. Component diagram using Mermaid syntax
3. API strategy (REST/GraphQL, versioning, authentication)
4. Database design and data flow
5. Authentication and authorization strategy
6. Deployment architecture (environments, CI/CD)
7. Scalability considerations and bottleneck analysis
8. Security considerations

Design Principles:
- Separation of concerns
- Domain-driven design where appropriate
- Security by design
- Performance optimization
- Cost-effectiveness
- Developer experience

Output your response as valid JSON with this structure:
{
    "tech_stack": {
        "frontend": {"name": "...", "justification": "...", "alternatives": [...]},
        "backend": {"name": "...", "justification": "...", "alternatives": [...]},
        "database": {"name": "...", "justification": "...", "alternatives": [...]},
        "infrastructure": {"name": "...", "justification": "...", "alternatives": [...]}
    },
    "component_diagram": "```mermaid\\ngraph TD\\n...\\n```",
    "api_strategy": {
        "type": "REST|GraphQL|gRPC",
        "versioning": "...",
        "authentication": "...",
        "rate_limiting": "..."
    },
    "data_flow": "Description of data flow...",
    "deployment": {
        "strategy": "blue-green|rolling|canary",
        "environments": ["dev", "staging", "prod"],
        "ci_cd": "..."
    },
    "scalability": {
        "bottlenecks": ["..."],
        "recommendations": ["..."],
        "estimated_capacity": "..."
    },
    "security": {
        "authentication": "...",
        "authorization": "...",
        "data_protection": "...",
        "compliance": ["..."]
    }
}
"""


class ArchitectAgent(BaseAgent[ArchitectureInput, ArchitectureOutput]):
    """Agent that designs system architecture from requirements.

    Extends :class:`~agentic_v2.agents.base.BaseAgent` parameterized with
    :class:`ArchitectureInput` / :class:`ArchitectureOutput`.

    The agent prompts the LLM with a detailed system-design persona and
    parses the JSON response into structured output.  When no LLM backend
    is configured, a mock response is returned for testing.

    JSON extraction is resilient: the parser tries fenced ``json`` blocks,
    generic fenced blocks, and raw ``{...}`` extraction in sequence.
    Mermaid diagrams are extracted separately as a fallback.

    Args:
        config: Agent configuration. Defaults to a Tier-3 config (higher
            tier for complex architectural reasoning) with 3 max iterations.
        **kwargs: Passed through to :class:`BaseAgent.__init__`.
    """

    def __init__(self, config: AgentConfig | None = None, **kwargs):
        if config is None:
            config = AgentConfig(
                name="architect",
                description="System architecture design agent",
                system_prompt=SYSTEM_PROMPT,
                default_tier=ModelTier.TIER_3,  # Higher tier for complex reasoning
                max_iterations=3,
            )

        super().__init__(config=config, **kwargs)

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Call the underlying LLM to generate architecture design.

        Args:
            messages: Chat messages to send
            tools: Optional tools (not typically used for architecture)

        Returns:
            Model response dict with "content" key
        """
        # If no backend is configured, return a mock response for testing
        if self.llm_client.backend is None:
            return {
                "content": json.dumps(
                    {
                        "tech_stack": {
                            "frontend": {
                                "name": "React",
                                "justification": "Mock response",
                            },
                            "backend": {
                                "name": "Python/FastAPI",
                                "justification": "Mock response",
                            },
                        },
                        "component_diagram": "```mermaid\ngraph TD\n    A[Frontend] --> B[Backend]\n```",
                        "api_strategy": {"style": "REST", "versioning": "URL path"},
                        "data_flow": "Frontend -> API -> Database",
                        "deployment": {"platform": "Cloud", "containerized": True},
                        "scalability": {"recommendations": ["Horizontal scaling"]},
                        "security": {"authentication": "JWT"},
                    }
                )
            }

        # Use real LLM client
        result_dict, _, _ = await self.llm_client.complete_chat(
            messages=messages,
            tier=self.config.default_tier,
            temperature=0.3,  # Lower temp for architecture consistency
        )

        return {"content": result_dict.get("content", result_dict.get("message", ""))}

    def _format_task_message(self, task: ArchitectureInput) -> str:
        """Format architecture design task."""
        parts = ["## Requirements", "", task.requirements, ""]

        if task.user_stories:
            parts.extend(
                [
                    "## User Stories",
                    "",
                    task.user_stories,
                    "",
                ]
            )

        if task.arch_constraints:
            parts.extend(
                [
                    "## Constraints",
                    "",
                    task.arch_constraints,
                    "",
                ]
            )

        if task.existing_architecture:
            parts.extend(
                [
                    "## Existing Architecture",
                    "",
                    task.existing_architecture,
                    "",
                ]
            )

        if task.preferences:
            parts.extend(
                [
                    "## Preferences",
                    "",
                    json.dumps(task.preferences, indent=2),
                    "",
                ]
            )

        parts.extend(
            [
                "## Task",
                "",
                "Design a comprehensive system architecture for the above requirements.",
                "Provide your response as valid JSON matching the specified structure.",
                "Include Mermaid diagrams where applicable.",
            ]
        )

        return "\n".join(parts)

    async def _is_task_complete(self, task: ArchitectureInput, response: str) -> bool:
        """Check if response contains valid architecture."""
        # Must have some JSON structure
        return "{" in response and "}" in response

    async def _parse_output(
        self, task: ArchitectureInput, response: str
    ) -> ArchitectureOutput:
        """Parse response into ArchitectureOutput."""
        architecture = self._parse_architecture_json(response)

        # Convert tech_stack dict entries to TechStackChoice objects
        tech_stack = {}
        for key, value in architecture.get("tech_stack", {}).items():
            if isinstance(value, dict):
                tech_stack[key] = TechStackChoice(
                    name=value.get("name", value.get("framework", "")),
                    justification=value.get("justification", ""),
                    alternatives=value.get("alternatives", []),
                )
            else:
                tech_stack[key] = TechStackChoice(name=str(value), justification="")

        return ArchitectureOutput(
            tech_stack=tech_stack,
            component_diagram=architecture.get("component_diagram", ""),
            api_strategy=architecture.get("api_strategy", {}),
            data_flow=architecture.get("data_flow", ""),
            deployment=architecture.get("deployment", {}),
            scalability=architecture.get("scalability", {}),
            security=architecture.get("security", {}),
            raw_response=response,
        )

    def _parse_architecture_json(self, response: str) -> dict[str, Any]:
        """Extract JSON architecture from model response.

        Delegates to :func:`extract_json` which uses balanced-brace
        extraction instead of the previous fragile ``index()``/``rindex()``
        approach.
        """
        try:
            return extract_json(response)
        except (json.JSONDecodeError, ValueError) as e:
            # Return structured fallback
            return {
                "raw_response": response,
                "parse_error": str(e),
                "tech_stack": {},
                "component_diagram": self._extract_mermaid(response),
                "api_strategy": {},
            }

    def _extract_mermaid(self, response: str) -> str:
        """Extract Mermaid diagram from response."""
        match = re.search(r"```mermaid\n(.*?)\n```", response, re.DOTALL)
        if match:
            return f"```mermaid\n{match.group(1)}\n```"
        return ""


# Convenience factory
def create_architect_agent(**kwargs) -> ArchitectAgent:
    """Create an architect agent with optional overrides."""
    return ArchitectAgent(**kwargs)
