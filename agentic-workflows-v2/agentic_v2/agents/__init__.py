"""Specialized AI agents for task execution within agentic workflows.

This package provides a hierarchy of agents built on :class:`BaseAgent`, each
specialized for a different software-engineering concern (code generation,
review, testing, architecture design, orchestration).  Agents are composed
with capability mixins from :mod:`.capabilities` and integrate with the DAG
execution engine via :func:`agent_to_step`.

Exports:
    Base classes and lifecycle primitives:
        :class:`BaseAgent`, :class:`AgentConfig`, :class:`AgentState`,
        :class:`AgentEvent`, :class:`ConversationMemory`,
        :class:`ConversationMessage`, :func:`agent_to_step`

    Capability system:
        :class:`Capability`, :class:`CapabilitySet`, :class:`CapabilityType`,
        :class:`CapabilityMixin`, :class:`CodeGenerationMixin`,
        :class:`CodeReviewMixin`, :class:`OrchestrationMixin`,
        :class:`TestGenerationMixin`, :func:`get_agent_capabilities`,
        :func:`requires_capabilities`

    Concrete agents:
        :class:`CoderAgent`, :class:`ReviewerAgent`,
        :class:`OrchestratorAgent`, :class:`ArchitectAgent`,
        :class:`TestAgent`

    Orchestrator I/O:
        :class:`OrchestratorInput`, :class:`OrchestratorOutput`,
        :class:`SubTask`

    Architect I/O:
        :class:`ArchitectureInput`, :class:`ArchitectureOutput`,
        :class:`TechStackChoice`

    Test agent I/O:
        :class:`TestGenerationInput`, :class:`TestGenerationOutput`,
        :class:`TestFile`, :class:`TestType`
"""

from .architect import (
    ArchitectAgent,
    ArchitectureInput,
    ArchitectureOutput,
    TechStackChoice,
)
from .base import (
    AgentConfig,
    AgentEvent,
    AgentState,
    BaseAgent,
    ConversationMemory,
    ConversationMessage,
    agent_to_step,
)
from .capabilities import (
    Capability,
    CapabilityMixin,
    CapabilitySet,
    CapabilityType,
    CodeGenerationMixin,
    CodeReviewMixin,
    OrchestrationMixin,
    TestGenerationMixin,
    get_agent_capabilities,
    requires_capabilities,
)
from .coder import CoderAgent
from .orchestrator import (
    OrchestratorAgent,
    OrchestratorInput,
    OrchestratorOutput,
    SubTask,
)
from .reviewer import ReviewerAgent
from .test_agent import (
    TestAgent,
    TestFile,
    TestGenerationInput,
    TestGenerationOutput,
    TestType,
)

__all__ = [
    # Base
    "AgentConfig",
    "AgentEvent",
    "AgentState",
    "BaseAgent",
    "ConversationMemory",
    "ConversationMessage",
    "agent_to_step",
    # Capabilities
    "Capability",
    "CapabilityMixin",
    "CapabilitySet",
    "CapabilityType",
    "CodeGenerationMixin",
    "CodeReviewMixin",
    "OrchestrationMixin",
    "TestGenerationMixin",
    "get_agent_capabilities",
    "requires_capabilities",
    # Agents
    "CoderAgent",
    "ReviewerAgent",
    "OrchestratorAgent",
    "OrchestratorInput",
    "OrchestratorOutput",
    "SubTask",
    # Architect Agent
    "ArchitectAgent",
    "ArchitectureInput",
    "ArchitectureOutput",
    "TechStackChoice",
    # Test Agent
    "TestAgent",
    "TestGenerationInput",
    "TestGenerationOutput",
    "TestFile",
    "TestType",
]
