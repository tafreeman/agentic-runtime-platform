"""Local model LLM backend implementations.

Concrete backends for locally-hosted model servers and runtimes:

- ``OllamaBackend`` — Ollama local model server (http://localhost:11434),
  backed by the official ``ollama`` Python client (``ollama.AsyncClient``)
  rather than hand-rolled ``httpx`` requests (ADR-036).
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
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ollama

from .backends_base import LLMBackend
from .local_discovery import onnx_roots, parse_onnx_roots
from .secrets import get_first_secret

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


@dataclass
class OllamaBackend(LLMBackend):
    """Backend for Ollama local models, backed by the official ``ollama`` client.

    Wraps :class:`ollama.AsyncClient` instead of hand-rolling ``httpx``
    requests against ``/api/generate`` and ``/api/chat`` (ADR-036). The
    client speaks Ollama's native wire format, so protocol changes — new
    response fields, the ``thinking`` channel for reasoning models, and
    structured ``tool_calls`` — track the SDK rather than bespoke JSON
    parsing. The public surface is unchanged: the ``LLMBackend`` interface
    and the canonical ``complete_chat`` dict shape (ADR-023 Phase 3) are
    preserved; only the transport is swapped.

    ``base_url`` honours ``OLLAMA_BASE_URL`` (matching the LangChain Ollama
    builder), falling back to the local default. ``think`` opts reasoning
    models into a separated chain-of-thought channel; ``None`` (the default)
    leaves the parameter unset, preserving the pre-SDK behaviour where a
    model only emits ``thinking`` if it does so on its own.
    """

    base_url: str = field(
        default_factory=lambda: (
            get_first_secret("OLLAMA_BASE_URL", default="http://localhost:11434")
            or "http://localhost:11434"
        )
    )
    timeout: float = 300.0  # Local models can be slower
    think: bool | None = None
    _client: ollama.AsyncClient | None = field(default=None, repr=False)

    def _get_client(self) -> ollama.AsyncClient:
        if self._client is None:
            self._client = ollama.AsyncClient(host=self.base_url, timeout=self.timeout)
        return self._client

    def _resolve_think(self, model_name: str) -> bool | None:
        """Decide whether to request a separated ``thinking`` channel.

        Returns the backend-level ``think`` setting unchanged. This is the
        seam for per-model policy — e.g. enabling ``think`` only for known
        reasoning families (qwen3 / deepseek-r1 / phi4-reasoning), or
        degrading gracefully for models that reject the parameter. See
        ADR-036 (open decision: think policy).
        """
        return self.think

    @staticmethod
    def _tool_calls_to_dicts(message: Any) -> list[dict[str, Any]] | None:
        """Normalise SDK ``ToolCall`` objects to plain dicts (or ``None``).

        Preserves the historical ``complete_chat`` contract where
        ``tool_calls`` is a JSON-able ``list[dict]`` shaped as
        ``{"function": {"name", "arguments"}}``, or ``None`` when the turn
        made no tool calls.
        """
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            return None
        return [tool_call.model_dump() for tool_call in tool_calls]

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """Send a raw-prompt completion request to Ollama (``/api/generate``)."""
        client = self._get_client()

        # Strip provider prefix if present
        model_name = model.replace("ollama:", "")

        try:
            response = await client.generate(
                model=model_name,
                prompt=prompt,
                think=self._resolve_think(model_name),
                options={"num_predict": max_tokens, "temperature": temperature},
            )
        except ollama.ResponseError as exc:
            raise RuntimeError(f"Ollama API error: {exc}") from exc

        # Reasoning models (qwen3, deepseek-r1, phi4-reasoning) put their
        # chain-of-thought in ``thinking`` and may leave ``response`` empty.
        # Fall back to ``thinking`` content when ``response`` is blank.
        text = response.response or ""
        if not text.strip():
            text = response.thinking or ""
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
        """Send a chat completion request to Ollama (``/api/chat``).

        Returns the canonical dict shape (ADR-023 Phase 3): ``thinking`` is a
        separate top-level key and ``content`` carries only the answer text.
        The SDK exposes ``message.thinking`` and ``message.content`` directly,
        so no inline-marker fold-in is needed — reasoning-only turns keep an
        empty ``content`` and a populated ``thinking``.
        """
        client = self._get_client()

        # Strip provider prefix if present
        model_name = model.replace("ollama:", "")

        try:
            response = await client.chat(
                model=model_name,
                messages=messages,
                tools=tools or None,
                think=self._resolve_think(model_name),
                options={"num_predict": max_tokens, "temperature": temperature},
            )
        except ollama.ResponseError as exc:
            raise RuntimeError(f"Ollama API error: {exc}") from exc

        message = response.message
        return {
            "content": message.content or "",
            "thinking": getattr(message, "thinking", None) or "",
            "tool_calls": self._tool_calls_to_dicts(message),
            "finish_reason": "stop",
            "model": model_name,
            "_raw_ollama": response.model_dump(),
        }

    async def close(self) -> None:
        """Close the HTTP client owned by the Ollama SDK."""
        client = self._client
        if client is None:
            return
        # ``ollama.AsyncClient`` owns an inner ``httpx.AsyncClient``; close it
        # so the connection pool is released. Guarded with getattr so a test
        # double without the inner client (or already closed) is a no-op.
        inner = getattr(client, "_client", None)
        if inner is not None and not getattr(inner, "is_closed", False):
            await inner.aclose()
        self._client = None


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
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, compare=False, repr=False
    )

    def _candidate_roots(self) -> list[Path]:
        """Roots to resolve ``onnx:`` ids against (discovered == runnable).

        Honors an explicitly-set ``model_dir`` (parsed identically to the env
        spec — ``os.pathsep``-separated, ``~`` expanded, with the aigallery
        default appended); otherwise uses :func:`onnx_roots`. Either way the
        backend searches the *same* roots discovery scanned, so a model surfaced
        by the probe loads from the root it was found under.
        """
        if self.model_dir:
            return parse_onnx_roots(self.model_dir)
        return onnx_roots()

    def _resolve_path(self, model: str) -> str:
        name = model.removeprefix("onnx:")
        roots = self._candidate_roots()
        for root in roots:
            if (root / name).exists():
                return str(root / name)
        # Not present under any root yet: return a deterministic, expanded path
        # under the first root so load errors point somewhere sensible and the
        # per-path model cache stays stable across calls.
        return str(roots[0] / name) if roots else name

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

        ONNX model folders ship their own chat template metadata, but
        the onnxruntime-genai Python surface does not apply it
        automatically. A simple, model-agnostic role layout keeps the
        backend usable across model families without hard-coding per-
        model templates.
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content") or ""
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
        new_tokens = output[len(input_tokens) :]
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
