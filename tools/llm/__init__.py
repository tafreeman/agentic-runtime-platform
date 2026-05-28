"""LLM integration layer with multi-provider dispatch.

This sub-package exposes :class:`~tools.llm.llm_client.LLMClient` for
text generation across local (ONNX, Ollama, Windows AI) and remote
(OpenAI, Gemini, Claude, GitHub Models, Azure) backends.

Key modules:
    llm_client: Unified ``LLMClient`` static facade.
    provider_adapters: Per-provider HTTP / SDK adapters.
    local_models: Registry of local ONNX model paths.
    model_inventory: Inventory helpers for listing available models.
"""

from __future__ import annotations
