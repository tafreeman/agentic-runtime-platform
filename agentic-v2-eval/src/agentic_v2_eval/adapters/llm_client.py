"""LLM client adapter for tools.llm.LLMClient.

This adapter bridges the tools.llm.llm_client.LLMClient to the
LLMClientProtocol expected by agentic-v2-eval evaluators.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LLMClientAdapter:
    """Adapter that wraps tools.llm.LLMClient to satisfy LLMClientProtocol.

    This adapter allows the agentic-v2-eval evaluators to use the shared
    LLMClient from the tools package, which supports multiple providers:
    - local:* - Local ONNX models
    - windows-ai:* - Windows AI / Phi Silica
    - azure-foundry:* - Azure Foundry API
    - gh:* - GitHub Models
    - gemini:* - Google Gemini
    - claude:* - Anthropic Claude
    - gpt* - OpenAI

    Example:
        >>> from agentic_v2_eval.adapters import LLMClientAdapter
        >>> from agentic_v2_eval.evaluators.llm import LLMEvaluator, STANDARD_CHOICES
        >>>
        >>> client = LLMClientAdapter(default_model="gh:gpt-4o-mini")
        >>> evaluator = LLMEvaluator(
        ...     model_id="gh:gpt-4o-mini",
        ...     system_prompt="You are a helpful evaluator.",
        ...     prompt_template="Rate this: {output}",
        ...     choices=STANDARD_CHOICES,
        ...     llm_client=client,
        ... )
    """

    default_model: str | None = None
    default_temperature: float = 0.0
    default_max_tokens: int = 4096
    system_instruction: str | None = None
    _llm_client_class: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Lazy import LLMClient to avoid circular dependencies."""
        if self._llm_client_class is None:
            try:
                from tools.llm.llm_client import LLMClient

                self._llm_client_class = LLMClient
            except ImportError as e:
                logger.warning(
                    "Could not import tools.llm.LLMClient: %s. "
                    "LLMClientAdapter will not be functional.",
                    e,
                )
                self._llm_client_class = None

    def generate_text(
        self,
        model_name: str,
        prompt: str,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> str:
        """Generate text using tools.llm.LLMClient.

        Args:
            model_name: Model identifier (e.g., "gh:gpt-4o-mini", "local:phi4")
            prompt: The prompt to send to the model
            temperature: Sampling temperature (default: 0.0 for deterministic)
            **kwargs: Additional arguments passed to LLMClient.generate_text
                - system_instruction: Optional system prompt
                - max_tokens: Maximum tokens to generate

        Returns:
            Generated text response from the model.

        Raises:
            RuntimeError: If LLMClient could not be imported.
            Various: Exceptions from the underlying LLM provider.
        """
        if self._llm_client_class is None:
            raise RuntimeError(
                "LLMClient not available. Ensure tools.llm is importable."
            )

        # Use provided model or fall back to default
        effective_model = model_name or self.default_model
        if not effective_model:
            raise ValueError("No model_name provided and no default_model configured.")

        # Extract kwargs that LLMClient.generate_text accepts
        system_instruction = kwargs.pop("system_instruction", self.system_instruction)
        max_tokens = kwargs.pop("max_tokens", self.default_max_tokens)

        # Log any unused kwargs
        if kwargs:
            logger.debug("Unused kwargs passed to generate_text: %s", kwargs.keys())

        response: str = self._llm_client_class.generate_text(
            model_name=effective_model,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response


def create_llm_client(
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    system_instruction: str | None = None,
) -> LLMClientAdapter:
    """Factory function to create an LLMClientAdapter.

    Args:
        model: Default model identifier (optional).
        temperature: Default temperature for generation.
        max_tokens: Default maximum tokens.
        system_instruction: Default system instruction.

    Returns:
        Configured LLMClientAdapter instance.

    Example:
        >>> client = create_llm_client(model="gh:gpt-4o-mini")
        >>> response = client.generate_text("gh:gpt-4o", "Hello!")
    """
    return LLMClientAdapter(
        default_model=model,
        default_temperature=temperature,
        default_max_tokens=max_tokens,
        system_instruction=system_instruction,
    )
