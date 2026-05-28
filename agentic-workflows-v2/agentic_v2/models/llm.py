"""LLM Client Adapter for Agentic V2."""

from typing import Any

from agentic_v2_eval.interfaces import LLMClientProtocol

from tools.llm.llm_client import LLMClient as LegacyClient


class LLMClient(LLMClientProtocol):
    """Adapter for the legacy LLMClient to match the new Protocol."""

    def generate_text(
        self,
        model_name: str,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> str:
        """Generate text using the unified client.

        Args:
            model_name: Model identifier
            prompt: User prompt
            temperature: Sampling temperature
            max_tokens: Max output tokens
            **kwargs: Additional args (e.g. system_instruction)
        """
        system_instruction = kwargs.get("system_instruction")

        # Delegate to legacy static method
        return LegacyClient.generate_text(
            model_name=model_name,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
        )
