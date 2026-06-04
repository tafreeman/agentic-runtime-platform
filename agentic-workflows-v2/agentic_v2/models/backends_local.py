"""Local model LLM backend implementations.

Concrete backends for locally-hosted model servers and runtimes:

- ``OllamaBackend`` — Ollama local model server (http://localhost:11434)
- ``OnnxBackend``   — local ONNX models via onnxruntime-genai (CPU / NPU)

Ollama supports a wide variety of open-weight models including reasoning
models (qwen3, deepseek-r1, phi4-reasoning) whose chain-of-thought output
appears in the ``thinking`` field rather than ``response``/``content``.

``OnnxBackend`` runs quantized open-weight models (Phi-4, Mistral, ...)
directly through Microsoft's onnxruntime-genai. The native dependency is
imported lazily so it is only required when an ``onnx:`` model is actually
invoked — mirroring how ``OllamaBackend`` only needs a running server at
call time.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .backends_base import LLMBackend
from .secrets import get_first_secret

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


@dataclass
class OllamaBackend(LLMBackend):
    """Backend for Ollama local models."""

    base_url: str = "http://localhost:11434"
    timeout: float = 300.0  # Local models can be slower
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """Send completion request to Ollama."""
        client = await self._get_client()

        # Strip provider prefix if present
        model_name = model.replace("ollama:", "")

        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        response = await client.post("/api/generate", json=payload)
        response.raise_for_status()

        data = response.json()
        # Reasoning models (qwen3, deepseek-r1, phi4-reasoning) put their
        # chain-of-thought in a "thinking" field and may leave "response"
        # empty.  Fall back to "thinking" content when "response" is blank.
        text = data.get("response", "")
        if not text.strip():
            text = data.get("thinking", "")
        return text

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send chat completion request to Ollama."""
        client = await self._get_client()

        # Strip provider prefix if present
        model_name = model.replace("ollama:", "")

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        # Ollama supports tools for some models
        if tools:
            payload["tools"] = tools

        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()

        data = response.json()
        message = data.get("message", {})

        # ADR-023 Phase 3: canonicalize the dict shape.  Reasoning models
        # (qwen3, deepseek-r1, phi4-reasoning) put their chain-of-thought
        # in ``message.thinking`` and may leave ``message.content`` empty.
        # The previous adapter folded ``thinking`` into ``content`` when
        # ``content`` was blank, which lost the distinction between answer
        # and reasoning.  The chosen convention (ADR-023 open decision
        # ollama-thinking-marker) is a separate top-level ``thinking`` key
        # with ``content`` carrying only the actual answer text.  The
        # prompt-path wrapper ``complete()`` retains its own fallback for
        # backwards compatibility.
        content = message.get("content", "") or ""
        thinking = message.get("thinking", "") or ""

        return {
            "content": content,
            "thinking": thinking,
            "tool_calls": message.get("tool_calls"),
            "finish_reason": "stop",
            "model": model_name,
            "_raw_ollama": data,
        }

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ---------------------------------------------------------------------------
# ONNX (onnxruntime-genai)
# ---------------------------------------------------------------------------


def _load_onnxruntime_genai() -> Any:
    """Import onnxruntime-genai lazily.

    Kept behind a function so the heavy native dependency is only required
    when an ``onnx:`` model is actually invoked, and so tests can inject a
    stub module. Raises a clear, actionable error when the runtime is
    absent.
    """
    try:
        import onnxruntime_genai as og
    except ImportError as exc:  # pragma: no cover - exercised via stub injection
        raise RuntimeError(
            "onnxruntime-genai is not installed. Install it "
            "(pip install onnxruntime-genai) to use 'onnx:' models."
        ) from exc
    return og


@dataclass
class OnnxBackend(LLMBackend):
    """Backend for local ONNX models via onnxruntime-genai.

    Resolves models from a local cache directory (``ONNX_MODEL_DIR`` or
    ``AIGALLERY_CACHE``); a model string ``onnx:<folder>`` maps to
    ``<model_dir>/<folder>``. Loaded models are cached per directory and
    reused across calls.

    Generation is synchronous and CPU/NPU-bound, so it runs in a worker
    thread to keep the event loop responsive.
    """

    model_dir: str = field(
        default_factory=lambda: (
            get_first_secret("ONNX_MODEL_DIR", "AIGALLERY_CACHE", default="") or ""
        ),
    )
    max_tokens_cap: int = 4096
    # Cache of resolved path -> (og_module, model, tokenizer).
    _models: dict[str, tuple[Any, Any, Any]] = field(default_factory=dict, repr=False)

    def _resolve_path(self, model: str) -> str:
        name = model.removeprefix("onnx:")
        if self.model_dir:
            return str(Path(self.model_dir) / name)
        return name

    def _get_model(self, model: str) -> tuple[Any, Any, Any]:
        path = self._resolve_path(model)
        with self._lock:
            cached = self._models.get(path)
            if cached is None:
                og = _load_onnxruntime_genai()
                loaded = og.Model(path)
                tokenizer = og.Tokenizer(loaded)
                cached = (og, loaded, tokenizer)
                self._models[path] = cached
            return cached

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
        """Flatten chat messages into a generic role-tagged prompt.

        ONNX model folders ship their own chat template metadata, but the
        onnxruntime-genai Python surface does not apply it automatically.
        A simple, model-agnostic role layout keeps the backend usable
        across model families without hard-coding per-model templates.
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"<|{role}|>\n{content}")
        parts.append("<|assistant|>\n")
        return "\n".join(parts)

    def _generate_sync(
        self, model: str, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        og, loaded, tokenizer = self._get_model(model)
        input_tokens = tokenizer.encode(prompt)
        max_len = len(input_tokens) + min(max_tokens, self.max_tokens_cap)

        params = og.GeneratorParams(loaded)
        params.set_search_options(
            max_length=max_len,
            temperature=temperature,
        )

        generator = og.Generator(loaded, params)
        generator.append_tokens(input_tokens)

        while not generator.is_done():
            generator.generate_next_token()

        output = generator.get_sequence(0)
        # get_sequence returns the full sequence (prompt + completion);
        # decode only the newly generated tail.
        new_tokens = output[len(input_tokens):]
        return str(tokenizer.decode(new_tokens))

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """Generate a completion from a raw prompt on a worker thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._generate_sync, model, prompt, max_tokens, temperature
        )

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a chat completion.

        Tool calling is not supported by the onnxruntime-genai surface, so
        ``tools`` is accepted for interface parity but ignored.
        """
        prompt = self._messages_to_prompt(messages)
        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(
            None, self._generate_sync, model, prompt, max_tokens, temperature
        )
        return {
            "content": content,
            "tool_calls": None,
            "finish_reason": "stop",
            "model": model.removeprefix("onnx:"),
        }


__all__ = ["OllamaBackend", "OnnxBackend"]
