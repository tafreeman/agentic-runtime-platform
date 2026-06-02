"""ADR-023 Phase 2: ensure the LLMBackend type is unified.

Prior to ADR-023 Phase 2, ``agentic_v2.models.client`` defined a local
``Protocol`` named ``LLMBackend`` with only ``complete`` /
``complete_stream`` / ``count_tokens``. Concrete backends inherited a
different ABC defined in ``agentic_v2.models.backends_base`` which also
declares ``complete_chat``. As a result, ``LLMClientWrapper.backend``
was type-hinted against a strict subset and ``complete_chat`` was
invisible to the wrapper.

This test pins the unification: both import paths must resolve to the
**same** class object, and every concrete backend shipped in the
runtime must be a subclass of it.

The test imports backend classes only — it does not instantiate them,
so it runs cleanly with ``AGENTIC_NO_LLM=1`` and no provider keys.
"""

from __future__ import annotations

from agentic_v2.models.backends import (
    AnthropicBackend,
    GeminiBackend,
    GitHubModelsBackend,
    MockBackend,
    MultiBackend,
    OllamaBackend,
    OpenAIBackend,
)
from agentic_v2.models.backends_base import LLMBackend as BackendsBaseLLMBackend
from agentic_v2.models.client import LLMBackend as ClientLLMBackend


def test_llmbackend_definitions_are_the_same_class() -> None:
    """The two import paths must resolve to one class object."""
    assert ClientLLMBackend is BackendsBaseLLMBackend, (
        "agentic_v2.models.client.LLMBackend and "
        "agentic_v2.models.backends_base.LLMBackend must be the SAME class "
        "object after ADR-023 Phase 2. Got "
        f"client={ClientLLMBackend!r} vs base={BackendsBaseLLMBackend!r}."
    )


def test_unified_llmbackend_exposes_complete_chat() -> None:
    """The unified ABC must declare complete_chat (the abstract method
    that was previously missing from the client.py Protocol)."""
    assert hasattr(ClientLLMBackend, "complete_chat"), (
        "Unified LLMBackend must expose complete_chat for the wrapper "
        "and step executor to see it."
    )
    assert hasattr(ClientLLMBackend, "complete")
    assert hasattr(ClientLLMBackend, "complete_stream")
    assert hasattr(ClientLLMBackend, "count_tokens")


def test_all_concrete_backends_inherit_unified_llmbackend() -> None:
    """Every concrete backend shipped in the runtime must inherit the
    unified ABC. This catches drift if a new backend is added that
    bypasses the ABC."""
    concrete_backends = [
        OpenAIBackend,
        AnthropicBackend,
        GeminiBackend,
        GitHubModelsBackend,
        OllamaBackend,
        MultiBackend,
        MockBackend,
    ]

    for backend_cls in concrete_backends:
        assert issubclass(backend_cls, ClientLLMBackend), (
            f"{backend_cls.__name__} must inherit the unified LLMBackend "
            f"ABC from agentic_v2.models.backends_base."
        )
        # Also assert against the other import path to guarantee parity.
        assert issubclass(backend_cls, BackendsBaseLLMBackend), (
            f"{backend_cls.__name__} must inherit the LLMBackend ABC "
            f"under the backends_base import path as well."
        )
