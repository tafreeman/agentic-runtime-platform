"""Composable capability system for dynamic agent-to-task matching.

Provides a mixin-based capability model that allows agents to declare what
they can do (code generation, review, testing, orchestration, etc.) and
enables the :class:`~agentic_v2.agents.orchestrator.OrchestratorAgent` to
select the best agent for each subtask at runtime.

Core abstractions:
    :class:`CapabilityType`:
        Enum of standardized capability identifiers.
    :class:`Capability`:
        A single capability with a proficiency level (0.0--1.0).
    :class:`CapabilitySet`:
        Collection of capabilities supporting requirement matching and
        scoring via :meth:`CapabilitySet.score_match`.
    :class:`CapabilityMixin`:
        Abstract mixin that concrete mixins (e.g., :class:`CodeGenerationMixin`,
        :class:`CodeReviewMixin`) extend to inject capabilities into an agent.
    :func:`get_agent_capabilities`:
        MRO-aware introspection that aggregates capabilities from all
        :class:`CapabilityMixin` bases of a :class:`~agentic_v2.agents.base.BaseAgent`.
    :func:`requires_capabilities`:
        Decorator that annotates a method with required capability types for
        runtime validation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .base import BaseAgent


class CapabilityType(str, Enum):
    """Enumeration of standardized agent capability identifiers.

    Organized into logical groups: code operations, testing, documentation,
    analysis, planning, tool use, and meta-capabilities.
    """

    # Code capabilities
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    CODE_REFACTORING = "code_refactoring"
    CODE_EXPLANATION = "code_explanation"

    # Test capabilities
    TEST_GENERATION = "test_generation"
    TEST_EXECUTION = "test_execution"

    # Documentation
    DOCUMENTATION = "documentation"
    API_DOCS = "api_docs"

    # Analysis
    STATIC_ANALYSIS = "static_analysis"
    SECURITY_ANALYSIS = "security_analysis"
    PERFORMANCE_ANALYSIS = "performance_analysis"

    # Planning
    TASK_DECOMPOSITION = "task_decomposition"
    ARCHITECTURE_DESIGN = "architecture_design"

    # Tool use
    FILE_OPERATIONS = "file_operations"
    SHELL_EXECUTION = "shell_execution"
    WEB_SEARCH = "web_search"

    # Meta
    ORCHESTRATION = "orchestration"
    SELF_REFLECTION = "self_reflection"


@dataclass
class Capability:
    """A single declared capability with a proficiency level.

    Attributes:
        type: The :class:`CapabilityType` this capability represents.
        proficiency: Proficiency score in the range ``[0.0, 1.0]``.
            Clamped on construction via ``__post_init__``.
        requirements: Other capability types that must also be present
            for this capability to be exercised.
        metadata: Arbitrary extension data (e.g., supported languages,
            framework preferences).
    """

    type: CapabilityType
    proficiency: float = 1.0  # 0.0 to 1.0
    requirements: list[CapabilityType] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.proficiency = max(0.0, min(1.0, self.proficiency))

    def meets_requirement(self, required: "Capability") -> bool:
        """Check if this capability meets a requirement."""
        if self.type != required.type:
            return False
        return self.proficiency >= required.proficiency


@dataclass
class CapabilitySet:
    """Collection of :class:`Capability` instances with matching and scoring.

    Used by the :class:`~agentic_v2.agents.orchestrator.OrchestratorAgent`
    to evaluate how well an agent's capabilities align with a subtask's
    requirements.

    Attributes:
        capabilities: Mapping from :class:`CapabilityType` to
            :class:`Capability`.  At most one capability per type.
    """

    capabilities: dict[CapabilityType, Capability] = field(default_factory=dict)

    def add(self, capability: Capability) -> None:
        """Add a capability."""
        self.capabilities[capability.type] = capability

    def remove(self, cap_type: CapabilityType) -> bool:
        """Remove a capability."""
        if cap_type in self.capabilities:
            del self.capabilities[cap_type]
            return True
        return False

    def has(self, cap_type: CapabilityType, min_proficiency: float = 0.0) -> bool:
        """Check if capability exists with minimum proficiency."""
        cap = self.capabilities.get(cap_type)
        return cap is not None and cap.proficiency >= min_proficiency

    def get(self, cap_type: CapabilityType) -> Capability | None:
        """Get a capability."""
        return self.capabilities.get(cap_type)

    def list_types(self) -> list[CapabilityType]:
        """List all capability types."""
        return list(self.capabilities.keys())

    def meets_requirements(self, required: "CapabilitySet") -> bool:
        """Check if this set meets all requirements from another set."""
        for cap_type, req_cap in required.capabilities.items():
            if not self.has(cap_type, req_cap.proficiency):
                return False
        return True

    def missing_capabilities(self, required: "CapabilitySet") -> list[CapabilityType]:
        """Get list of missing capabilities."""
        missing = []
        for cap_type, req_cap in required.capabilities.items():
            if not self.has(cap_type, req_cap.proficiency):
                missing.append(cap_type)
        return missing

    def score_match(self, required: "CapabilitySet") -> float:
        """Score how well this set matches requirements.

        Returns:
            0.0-1.0 score (1.0 = perfect match)
        """
        if not required.capabilities:
            return 1.0

        total_score = 0.0
        for cap_type, req_cap in required.capabilities.items():
            our_cap = self.capabilities.get(cap_type)
            if our_cap:
                # Score based on proficiency ratio
                total_score += min(
                    1.0, our_cap.proficiency / max(0.01, req_cap.proficiency)
                )
            # Missing capability contributes 0

        return total_score / len(required.capabilities)

    @classmethod
    def from_types(cls, *cap_types: CapabilityType) -> "CapabilitySet":
        """Create from capability types with default proficiency."""
        cap_set = cls()
        for cap_type in cap_types:
            cap_set.add(Capability(type=cap_type))
        return cap_set


class CapabilityMixin(ABC):
    """Abstract mixin base for injecting capabilities into agents.

    Concrete mixins (e.g., :class:`CodeGenerationMixin`) extend this class
    and implement :meth:`get_capabilities` to declare the capabilities they
    provide.  Agents compose capabilities via multiple inheritance::

        class MyAgent(BaseAgent, CodeGenerationMixin, TestGenerationMixin):
            pass

    The :func:`get_agent_capabilities` function walks the MRO to collect
    all declared capabilities from an agent instance.
    """

    @abstractmethod
    def get_capabilities(self) -> CapabilitySet:
        """Return the capabilities provided by this mixin."""
        pass


class CodeGenerationMixin(CapabilityMixin):
    """Mixin declaring :attr:`CapabilityType.CODE_GENERATION` and
    :attr:`CapabilityType.CODE_EXPLANATION` capabilities.

    Subclasses should override :meth:`generate_code` with a concrete
    implementation.
    """

    def get_capabilities(self) -> CapabilitySet:
        return CapabilitySet.from_types(
            CapabilityType.CODE_GENERATION, CapabilityType.CODE_EXPLANATION
        )

    async def generate_code(
        self, description: str, language: str = "python", context: str | None = None
    ) -> str:
        """Generate code from description."""
        # Default implementation - override in subclass
        raise NotImplementedError("Subclass must implement generate_code")


class CodeReviewMixin(CapabilityMixin):
    """Mixin declaring :attr:`CapabilityType.CODE_REVIEW` and
    :attr:`CapabilityType.STATIC_ANALYSIS` capabilities.

    Subclasses should override :meth:`review_code` with a concrete
    implementation.
    """

    def get_capabilities(self) -> CapabilitySet:
        return CapabilitySet.from_types(
            CapabilityType.CODE_REVIEW, CapabilityType.STATIC_ANALYSIS
        )

    async def review_code(
        self,
        code: str,
        language: str = "python",
        focus_areas: list[str] | None = None,
    ) -> dict[str, Any]:
        """Review code and return issues."""
        raise NotImplementedError("Subclass must implement review_code")


class TestGenerationMixin(CapabilityMixin):
    """Mixin declaring :attr:`CapabilityType.TEST_GENERATION` capability.

    Subclasses should override :meth:`generate_tests` with a concrete
    implementation.
    """

    def get_capabilities(self) -> CapabilitySet:
        return CapabilitySet.from_types(CapabilityType.TEST_GENERATION)

    async def generate_tests(
        self, code: str, language: str = "python", framework: str = "pytest"
    ) -> str:
        """Generate tests for code."""
        raise NotImplementedError("Subclass must implement generate_tests")


class OrchestrationMixin(CapabilityMixin):
    """Mixin declaring :attr:`CapabilityType.ORCHESTRATION` and
    :attr:`CapabilityType.TASK_DECOMPOSITION` capabilities.

    Subclasses should override :meth:`decompose_task` and
    :meth:`select_agent` with concrete implementations.
    """

    def get_capabilities(self) -> CapabilitySet:
        return CapabilitySet.from_types(
            CapabilityType.ORCHESTRATION, CapabilityType.TASK_DECOMPOSITION
        )

    async def decompose_task(self, task: str) -> list[dict[str, Any]]:
        """Decompose a task into subtasks."""
        raise NotImplementedError("Subclass must implement decompose_task")

    async def select_agent(
        self, task: dict[str, Any], available_agents: list["BaseAgent"]
    ) -> "BaseAgent" | None:
        """Select best agent for a task."""
        raise NotImplementedError("Subclass must implement select_agent")


class SelfReflectionMixin(CapabilityMixin):
    """Mixin declaring :attr:`CapabilityType.SELF_REFLECTION` capability.

    Enables agents to critique and revise their own output before
    returning it.  Subclasses should override :meth:`reflect` with
    a concrete implementation.
    """

    def get_capabilities(self) -> CapabilitySet:
        """Return self-reflection capability."""
        return CapabilitySet.from_types(CapabilityType.SELF_REFLECTION)

    async def reflect(
        self, output: str, criteria: str = "correctness"
    ) -> dict[str, Any]:
        """Critique own output and return revision suggestions.

        Args:
            output: The agent's generated output to reflect on.
            criteria: The quality dimension to evaluate.

        Returns:
            Dict with ``needs_revision`` (bool), ``issues`` (list),
            and ``revised_output`` (str, optional).
        """
        raise NotImplementedError("Subclass must implement reflect")


def requires_capabilities(*cap_types: CapabilityType):
    """Decorator that annotates a method with required capability types.

    The annotated capability types are stored on the function object as
    ``_required_capabilities`` for runtime introspection.

    Args:
        *cap_types: One or more :class:`CapabilityType` values that the
            calling agent must possess.

    Returns:
        A decorator that tags the wrapped function with the required
        capabilities.

    Example::

        @requires_capabilities(CapabilityType.CODE_GENERATION)
        async def generate(self, ...):
            ...
    """

    def decorator(func: Callable) -> Callable:
        func._required_capabilities = cap_types
        return func

    return decorator


def get_agent_capabilities(agent: "BaseAgent") -> CapabilitySet:
    """Aggregate capabilities from all :class:`CapabilityMixin` bases of an agent.

    Walks the agent's MRO and calls :meth:`CapabilityMixin.get_capabilities`
    on each mixin class, merging the results into a single
    :class:`CapabilitySet`.

    Args:
        agent: The agent instance to introspect.

    Returns:
        A :class:`CapabilitySet` containing all capabilities declared by
        the agent's mixin hierarchy.
    """
    cap_set = CapabilitySet()

    # Check for capability mixins
    for base in type(agent).__mro__:
        if (
            base is not CapabilityMixin
            and issubclass(base, CapabilityMixin)
            and hasattr(base, "get_capabilities")
        ):
            try:
                mixin_caps = base.get_capabilities(agent)
                for cap in mixin_caps.capabilities.values():
                    cap_set.add(cap)
            except Exception:
                pass

    return cap_set
