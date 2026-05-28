"""Structural typing protocols for the evaluation framework.

Defines the two core protocols that decouple evaluator implementations
from concrete LLM clients and scoring strategies, enabling dependency
injection and simplified testing with mocks.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMClientProtocol(Protocol):
    """Structural protocol for LLM text-generation clients.

    Any object whose ``generate_text`` method matches this signature
    satisfies the protocol at both static (mypy) and runtime
    (``isinstance``) levels, allowing evaluators to accept arbitrary
    LLM backends without import-time coupling.
    """

    def generate_text(
        self,
        model_name: str,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> str:
        """Generate text from a prompt.

        Args:
            model_name: Provider-qualified model identifier.
            prompt: The user prompt to send.
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum tokens to generate.
            **kwargs: Provider-specific overrides.

        Returns:
            Generated text string.
        """
        ...


class Evaluator(Protocol):
    """Structural protocol for evaluation strategies.

    Implementations score a model output (optionally against an expected
    reference) and return a result dict containing at minimum ``score``
    and ``passed`` keys.
    """

    def evaluate(
        self, output: str, expected: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Evaluate an output against expectations.

        Args:
            output: The model-generated text to evaluate.
            expected: Optional reference / ground-truth text.
            **kwargs: Strategy-specific context.

        Returns:
            Dict with at least ``score`` (float) and ``passed`` (bool).
        """
        ...
