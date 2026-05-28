"""LangChain adapter for the repo LLMClient.

Provides a minimal interface compatible with various LangChain versions so
`LLMChain` and similar utilities can call into the repo's `LLMClient`.

The adapter tries to construct real `langchain.schema` objects when the
library is available; otherwise it returns simple, duck-typed structures.
"""

from __future__ import annotations

from typing import Any

from tools.llm.llm_client import LLMClient


class LangChainAdapter:
    """Adapter that exposes a minimal LLM surface for LangChain integration.

    Methods provided:
    - __call__(prompt, **kwargs) -> str
    - generate(prompts, **kwargs) -> LLMResult-like object
    - predict(prompt, **kwargs) -> str
    """

    def __init__(self, model_name: str):
        self.model_name = model_name

    def __call__(self, prompt: str, **kwargs) -> str:
        return self.predict(prompt, **kwargs)

    def predict(self, prompt: str, **kwargs) -> str:
        return LLMClient.generate_text(
            self.model_name,
            prompt,
            system_instruction=kwargs.get("system"),
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 1024),
        )

    def generate(self, prompts: list[str], **kwargs) -> Any:
        """Return a LangChain-compatible result for a list of prompts.

        If `langchain.schema` types are available, returns an `LLMResult`
        instance; otherwise returns a simple dict with `generations`.
        """
        texts = [self.predict(p, **kwargs) for p in prompts]

        # Try to build real langchain.schema types when present
        try:
            import langchain.schema as _schema

            generations = []
            for t in texts:
                gen = _schema.Generation(text=t)
                generations.append([gen])
            result = _schema.LLMResult(generations=generations)
            return result
        except Exception:
            # Fallback simple structure
            return {"generations": [[{"text": t}] for t in texts]}

    # Some LangChain variants call ._identifying_params or ._llm_type
    def _identifying_params(self) -> dict:
        return {"model_name": self.model_name}

    @property
    def _llm_type(self) -> str:
        return "custom-repo-llm"
