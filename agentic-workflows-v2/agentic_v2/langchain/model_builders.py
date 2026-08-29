"""Factory functions that construct LangChain ``BaseChatModel`` instances.

Each ``build_*`` function accepts the bare model name (without provider prefix)
and a ``temperature`` float, and returns a ready-to-use chat model.

Provider-specific LangChain packages are imported lazily inside each builder so
that only the packages required for the providers actually in use need to be
installed.

Supported providers
-------------------
- GitHub Models     — ``build_github_model``
- OpenAI            — ``build_openai_model``
- NVIDIA NIM        — ``build_nvidia_model``
- OpenRouter        — ``build_openrouter_model``
- Anthropic         — ``build_anthropic_model``
- Gemini            — ``build_gemini_model``
- NotebookLM alias  — ``build_notebooklm_model`` (routes to Gemini)
- Ollama            — ``build_ollama_model``
- LM Studio         — ``build_lmstudio_model``
- Local API         — ``build_local_api_model``
- Local ONNX        — ``build_local_onnx_model``
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# GitHub Models base URL — used by build_github_model
_GH_BASE_URL = "https://models.inference.ai.azure.com"

# Non-secret placeholder for self-hosted NVIDIA NIM, which does not validate the
# API key. A non-empty value is still required by the OpenAI client.
_LOCAL_NIM_PLACEHOLDER_KEY = "not-needed-for-local-nim"

# Env escape hatch for NIM's reasoning-disable request field.  Set to a falsey
# value to stop sending it — only needed for a self-hosted NIM whose chat
# template rejects unknown ``chat_template_kwargs`` (the cloud endpoint does
# not; see ``build_nvidia_model``).
_NVIDIA_DISABLE_THINKING_ENV = "NVIDIA_DISABLE_THINKING"
_FALSEY_ENV_VALUES = frozenset({"0", "false", "no", "off"})

# Cached NIM chat-model subclass, keyed on the ``ChatOpenAI`` base it was
# derived from so every call returns the *same* class (mirroring
# ``_PLACEHOLDER_CHAT_MODEL_CLS``) while a swapped base still rebuilds.
_NIM_CHAT_MODEL_CLS: tuple[Any, Any] | None = None

# Module-level flag so ``build_placeholder_model`` warns once per process
# rather than once per agent step (MED-1 from Sprint B #5 review).
_PLACEHOLDER_WARNED = False

# Cached ``PlaceholderChatModel`` class so every call to
# ``build_placeholder_model`` returns an instance of the *same* class (P4
# from Sprint B #5 follow-up review).  Defining the class at import time
# is not possible because ``BaseChatModel`` lives in the optional
# ``[langchain]`` extra, so the class is built lazily on first call and
# reused thereafter.
_PLACEHOLDER_CHAT_MODEL_CLS: Any | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _import_repo_llm_client() -> Any:
    """Import repo ``tools.llm.llm_client`` with workspace fallback."""
    try:
        from tools.llm.llm_client import LLMClient

        return LLMClient
    except ImportError as exc:
        raise ImportError(
            "Local ONNX provider requires importing tools.llm.llm_client. "
            "Run from repo root or install the agentic-tools package."
        ) from exc


def _resolve_notebooklm_model_name(model_name: str) -> str:
    """Resolve the Gemini model used for NotebookLM alias."""
    raw = (model_name or "").strip()
    if raw:
        return raw

    env_model = (
        os.environ.get("NOTEBOOKLM_MODEL")
        or os.environ.get("NOTEBOOKLM_GEMINI_MODEL")
        or ""
    ).strip()
    if env_model:
        return env_model

    # Default NotebookLM model is curated in the registry (ADR-040); strip the
    # provider prefix since this helper returns a bare gemini model name.
    from ..models.model_registry import special

    value = special("notebooklm_fallback")
    fallback = value if isinstance(value, str) else "gemini:gemini-2.5-pro"
    return fallback.split(":", 1)[-1]


# ---------------------------------------------------------------------------
# Provider builders (public API — no underscore prefix)
# ---------------------------------------------------------------------------


def build_github_model(model_name: str, temperature: float) -> Any:
    """Build a ChatOpenAI instance pointed at GitHub Models.

    Parameters
    ----------
    model_name:
        Bare model name after the ``gh:`` prefix, e.g. ``openai/gpt-4o``.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatOpenAI`` instance configured for the GitHub Models endpoint.

    Raises
    ------
    ImportError
        If ``langchain-openai`` is not installed.
    ValueError
        If ``GITHUB_TOKEN`` is not set.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "langchain-openai is required for GitHub Models. "
            "Install with: pip install langchain-openai"
        ) from exc

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_TOKEN environment variable is required for GitHub Models. "
            "Set it to a GitHub personal access token with 'models:read' scope."
        )

    # GitHub Models API accepts only the bare model name (e.g. "gpt-4o-mini").
    # Strip the optional org/publisher prefix that callers may include,
    # e.g. "openai/gpt-4o-mini" -> "gpt-4o-mini",
    #      "meta/llama-4-scout"  -> "llama-4-scout".
    api_model_name = model_name.split("/", 1)[-1] if "/" in model_name else model_name
    logger.debug("Using GitHub Models: %s (requested: %s)", api_model_name, model_name)
    return ChatOpenAI(
        model=api_model_name,
        base_url=_GH_BASE_URL,
        api_key=token,
        temperature=temperature,
    )


def build_openai_model(model_name: str, temperature: float) -> Any:
    """Build a ChatOpenAI instance for direct OpenAI API.

    Parameters
    ----------
    model_name:
        Bare model name after the ``openai:`` prefix, e.g. ``gpt-4o``.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatOpenAI`` instance.

    Raises
    ------
    ImportError
        If ``langchain-openai`` is not installed.
    ValueError
        If ``OPENAI_API_KEY`` is not set.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "langchain-openai is required for OpenAI models. "
            "Install with: pip install langchain-openai"
        ) from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY environment variable is required for OpenAI models."
        )

    kwargs: dict[str, Any] = {
        "model": model_name,
        "api_key": api_key,
        "temperature": temperature,
    }

    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
    if base_url:
        kwargs["base_url"] = base_url

    org = os.environ.get("OPENAI_ORG_ID")
    if org:
        kwargs["organization"] = org

    logger.debug("Using OpenAI model: %s", model_name)
    return ChatOpenAI(**kwargs)


def _nvidia_thinking_disabled() -> bool:
    """Whether to ask NIM to skip a reasoning model's chain-of-thought phase.

    Defaults to ``True``: the field is inert on every NIM model that does not
    understand it (see :func:`build_nvidia_model`), so opting *out* is the
    exceptional case. ``NVIDIA_DISABLE_THINKING`` set to ``0``/``false``/
    ``no``/``off`` restores the raw pass-through for a self-hosted NIM whose
    chat template rejects the field.
    """
    raw = os.environ.get(_NVIDIA_DISABLE_THINKING_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSEY_ENV_VALUES


def _nim_extra_body() -> dict[str, Any]:
    """Request extras that disable NIM's internal reasoning phase.

    Returned fresh per call so the caller owns the dict rather than sharing
    module-level mutable state with every other NIM model.
    """
    return {"chat_template_kwargs": {"thinking": False}}


def _nim_reasoning_texts(response: Any) -> list[str]:
    """Per-choice ``reasoning_content`` from a NIM chat-completions response.

    ``response`` is either the raw dict or the ``openai`` SDK's typed
    ``ChatCompletion``; the SDK keeps NIM's non-standard ``reasoning_content``
    as a pydantic extra, so it survives ``model_dump()``.
    """
    if isinstance(response, dict):
        payload = response
    else:
        dump = getattr(response, "model_dump", None)
        if dump is None:
            return []
        payload = dump()
    texts: list[str] = []
    for choice in payload.get("choices") or []:
        message = (choice or {}).get("message") or {}
        texts.append(str(message.get("reasoning_content") or ""))
    return texts


def _get_nim_chat_model_cls(base: Any) -> Any:
    """Build (once) the ``ChatOpenAI`` subclass used for NVIDIA NIM.

    ``ChatOpenAI`` targets the official OpenAI specification and documents that
    non-standard provider fields such as ``reasoning_content`` are **not**
    extracted or preserved — verified against the pinned ``langchain-openai``
    1.2.2, where a NIM reasoning turn arrives as ``content=''`` with nothing
    else attached. Recovering the field needs the provider-specific subclass
    that warning points at, so this stashes it in ``additional_kwargs`` where
    :func:`agentic_v2.langchain.graph_wiring.extract_agent_response_text` can
    fall back to it — the LangChain counterpart of ``OllamaBackend``'s
    ``response.thinking`` fallback.

    The class is cached against *base* so production gets one stable class and
    a swapped base (a test double) still rebuilds.
    """
    global _NIM_CHAT_MODEL_CLS
    if _NIM_CHAT_MODEL_CLS is not None and _NIM_CHAT_MODEL_CLS[0] is base:
        return _NIM_CHAT_MODEL_CLS[1]

    class ChatNvidiaNIM(base):  # type: ignore[misc, valid-type]
        """``ChatOpenAI`` that preserves NIM's ``reasoning_content`` channel."""

        def _create_chat_result(
            self, response: Any, generation_info: dict[str, Any] | None = None
        ) -> Any:
            result = super()._create_chat_result(response, generation_info)
            reasoning_texts = _nim_reasoning_texts(response)
            for generation, reasoning in zip(
                result.generations, reasoning_texts, strict=False
            ):
                if reasoning:
                    extras = generation.message.additional_kwargs
                    extras["reasoning_content"] = reasoning
            return result

        def _convert_chunk_to_generation_chunk(
            self,
            chunk: dict[str, Any],
            default_chunk_class: type,
            base_generation_info: dict[str, Any] | None,
        ) -> Any:
            generation = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )
            if generation is None:
                return None
            nested = chunk.get("chunk") or {}
            choices = chunk.get("choices") or nested.get("choices") or []
            if choices:
                delta = (choices[0] or {}).get("delta") or {}
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    # langchain-core merges str additional_kwargs by
                    # concatenation, so per-token deltas accumulate.
                    extras = generation.message.additional_kwargs
                    extras["reasoning_content"] = reasoning
            return generation

    _NIM_CHAT_MODEL_CLS = (base, ChatNvidiaNIM)
    return ChatNvidiaNIM


def build_nvidia_model(model_name: str, temperature: float) -> Any:
    """Build a ChatOpenAI instance pointed at NVIDIA NIM.

    NVIDIA NIM exposes an OpenAI-compatible ``/v1`` surface for both the public
    cloud (``integrate.api.nvidia.com``) and self-hosted containers, so a
    ``ChatOpenAI`` with a swapped ``base_url`` is the whole backend. The base
    URL is resolved by :func:`resolve_nvidia_base_url` — the same helper
    discovery uses — so a model surfaced by the probe is reachable here.

    Two accommodations for NIM-hosted **reasoning** models, which run an
    internal chain-of-thought phase before emitting any answer and so return
    empty content whenever the token budget runs out first:

    - ``extra_body={"chat_template_kwargs": {"thinking": False}}`` asks NIM to
      skip that phase. Sent unconditionally, because it is inert where it is
      not understood: probed live against the cloud endpoint on 2026-08-29,
      **no** model answered differently *because of* the field and none
      returned a 4xx for it. It flipped empty/chain-of-thought output into a
      real answer on ``deepseek-ai/deepseek-v4-flash-0731``, the
      ``nvidia/nemotron-3`` family, ``nvidia/nemotron-3.5-lightning-30b-a3b``
      and ``moonshotai/kimi-k3``; it was silently ignored by
      ``meta/muse-glimmer-30b`` and ``openai/gpt-oss-{20b,120b}`` (which gate
      reasoning on ``reasoning_effort`` instead) and by the non-reasoning
      ``nvidia/ising-calibration-1.5-31b``, whose output was byte-identical
      either way. ``NVIDIA_DISABLE_THINKING=0`` turns it off for a self-hosted
      NIM whose chat template is stricter.
    - The returned class preserves NIM's ``reasoning_content`` (which stock
      ``ChatOpenAI`` discards) so an empty answer still degrades to the
      model's reasoning rather than to an empty string — see
      :func:`_get_nim_chat_model_cls`.

    Parameters
    ----------
    model_name:
        Bare model name after the ``nvidia:`` prefix. NIM expects the full
        ``publisher/model`` id (e.g. ``meta/llama-3.3-70b-instruct``), so it is
        passed through verbatim — unlike GitHub Models, the publisher segment is
        **not** stripped.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatOpenAI`` subclass instance configured for the NIM endpoint.

    Raises
    ------
    ImportError
        If ``langchain-openai`` is not installed.
    ValueError
        If ``NVIDIA_API_KEY`` is unset and no on-prem ``NVIDIA_BASE_URL`` is
        configured (cloud NIM requires a key; a self-hosted NIM does not
        validate one).
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "langchain-openai is required for NVIDIA NIM models. "
            "Install with: pip install langchain-openai"
        ) from exc

    from ..models.cloud_discovery import resolve_nvidia_base_url

    base_url = resolve_nvidia_base_url()
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        if not os.environ.get("NVIDIA_BASE_URL"):
            raise ValueError(
                "NVIDIA_API_KEY environment variable is required for NVIDIA NIM "
                "cloud. Set NVIDIA_BASE_URL to target a self-hosted NIM instead."
            )
        # Self-hosted NIM does not validate the key; send a non-empty placeholder.
        api_key = _LOCAL_NIM_PLACEHOLDER_KEY

    kwargs: dict[str, Any] = {
        "model": model_name,
        "base_url": base_url,
        "api_key": api_key,
        "temperature": temperature,
    }
    if _nvidia_thinking_disabled():
        kwargs["extra_body"] = _nim_extra_body()

    logger.debug("Using NVIDIA NIM: %s at %s", model_name, base_url)
    return _get_nim_chat_model_cls(ChatOpenAI)(**kwargs)


def build_openrouter_model(model_name: str, temperature: float) -> Any:
    """Build a ChatOpenAI instance pointed at the OpenRouter aggregator.

    OpenRouter exposes an OpenAI-compatible ``/v1`` surface for every model it
    fronts, so a ``ChatOpenAI`` with a swapped ``base_url`` is the whole
    backend. The base URL is resolved by :func:`resolve_openrouter_base_url` —
    the same helper discovery uses — so a model surfaced by the probe is
    reachable here. An ``X-Title`` default header attributes traffic to this
    app, per OpenRouter's attribution convention.

    Parameters
    ----------
    model_name:
        Bare model name after the ``openrouter:`` prefix. OpenRouter expects
        the full ``publisher/model`` id, and free-tier ids append ``:free``
        (a full app id such as ``openrouter:meta-llama/llama-3.1-8b-instruct:free``
        carries two colons), so it is passed through verbatim — unlike GitHub
        Models, the publisher segment is **not** stripped.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatOpenAI`` instance configured for the OpenRouter endpoint.

    Raises
    ------
    ImportError
        If ``langchain-openai`` is not installed.
    ValueError
        If ``OPENROUTER_API_KEY`` is not set. OpenRouter is always
        authenticated — there is no keyless or self-hosted mode, so no
        placeholder key is substituted.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "langchain-openai is required for OpenRouter models. "
            "Install with: pip install langchain-openai"
        ) from exc

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY environment variable is required for OpenRouter models."
        )

    from ..models.cloud_discovery import resolve_openrouter_base_url

    base_url = resolve_openrouter_base_url()
    logger.debug("Using OpenRouter: %s at %s", model_name, base_url)
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        default_headers={"X-Title": "agentic-runtime-platform"},
    )


def build_anthropic_model(model_name: str, temperature: float) -> Any:
    """Build a ChatAnthropic instance.

    Parameters
    ----------
    model_name:
        Bare model name after the ``anthropic:`` / ``claude:`` prefix.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatAnthropic`` instance.

    Raises
    ------
    ImportError
        If ``langchain-anthropic`` is not installed.
    ValueError
        If ``ANTHROPIC_API_KEY`` is not set.
    """
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise ImportError(
            "langchain-anthropic is required for Anthropic models. "
            "Install with: pip install langchain-anthropic"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable is required for Anthropic models."
        )

    logger.debug("Using Anthropic model: %s", model_name)
    return ChatAnthropic(
        model=model_name,
        api_key=api_key,
        temperature=temperature,
    )


def build_gemini_model(model_name: str, temperature: float) -> Any:
    """Build a ChatGoogleGenerativeAI instance.

    Parameters
    ----------
    model_name:
        Bare model name after the ``gemini:`` prefix, e.g. ``gemini-2.0-flash``.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatGoogleGenerativeAI`` instance.

    Raises
    ------
    ImportError
        If ``langchain-google-genai`` is not installed.
    ValueError
        If neither ``GOOGLE_API_KEY`` nor ``GEMINI_API_KEY`` is set.
    """
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise ImportError(
            "langchain-google-genai is required for Gemini models. "
            "Install with: pip install langchain-google-genai"
        ) from exc

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) is required for Gemini models."
        )

    logger.debug("Using Gemini model: %s", model_name)
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature,
    )


def build_notebooklm_model(model_name: str, temperature: float) -> Any:
    """NotebookLM alias routed through Gemini models.

    Parameters
    ----------
    model_name:
        Optional bare model name after the ``notebooklm:`` prefix.  When empty
        the value is resolved from ``NOTEBOOKLM_MODEL`` / ``NOTEBOOKLM_GEMINI_MODEL``
        env vars, falling back to ``gemini-2.5-pro``.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatGoogleGenerativeAI`` instance for the resolved Gemini model.
    """
    resolved = _resolve_notebooklm_model_name(model_name)
    logger.debug("Using NotebookLM alias via Gemini model: %s", resolved)
    return build_gemini_model(resolved, temperature)


def build_ollama_model(model_name: str, temperature: float) -> Any:
    """Build a ChatOllama instance for a local or ollama.com-hosted model.

    Local-first (ADR-051): a model present in the local daemon's ``/api/tags``
    is served from ``OLLAMA_BASE_URL`` exactly as before. When the model is
    absent locally and ``OLLAMA_API_KEY`` is set, the call is routed to the
    hosted ``https://ollama.com`` API with bearer auth instead — otherwise
    cloud-catalog models are listed by discovery but 404 at execution time.
    Without an API key, behavior is unchanged.

    Parameters
    ----------
    model_name:
        Bare model name after the ``ollama:`` prefix, e.g. ``qwen2.5-coder``.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatOllama`` instance.

    Raises
    ------
    ImportError
        If ``langchain-ollama`` is not installed.
    """
    try:
        from langchain_ollama import ChatOllama
    except ImportError as exc:
        raise ImportError(
            "langchain-ollama is required for Ollama models. "
            "Install with: pip install langchain-ollama"
        ) from exc

    from ..models.ollama_discovery import (
        CLOUD_HOST,
        DEFAULT_LOCAL_HOST,
        ENV_API_KEY,
        ENV_BASE_URL,
        is_served_locally,
    )

    base_url = os.environ.get(ENV_BASE_URL, DEFAULT_LOCAL_HOST)
    client_kwargs: dict[str, Any] = {}
    api_key = os.environ.get(ENV_API_KEY)
    if api_key and not is_served_locally(model_name):
        base_url = CLOUD_HOST
        client_kwargs = {"headers": {"Authorization": f"Bearer {api_key}"}}
        logger.debug("Using Ollama cloud: %s at %s", model_name, base_url)
    else:
        logger.debug("Using Ollama: %s at %s", model_name, base_url)
    return ChatOllama(
        model=model_name,
        base_url=base_url,
        temperature=temperature,
        client_kwargs=client_kwargs,
        async_client_kwargs=client_kwargs,
    )


def build_lmstudio_model(model_name: str, temperature: float) -> Any:
    """Build a ChatOpenAI instance for local LM Studio server.

    Parameters
    ----------
    model_name:
        Bare model name after the ``lmstudio:`` prefix.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatOpenAI`` instance pointed at the local LM Studio endpoint.

    Raises
    ------
    ImportError
        If ``langchain-openai`` is not installed.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "langchain-openai is required for LM Studio models. "
            "Install with: pip install langchain-openai"
        ) from exc

    # Resolve the host the same way discovery does (LMSTUDIO_HOST, else the
    # first reachable of :1234 / :12340) so a model surfaced by the probe is
    # reachable at the host we send inference to — discovered == runnable.
    from ..models.local_discovery import resolve_lmstudio_host
    from ..models.secrets import get_first_secret

    base_url = resolve_lmstudio_host()
    if not base_url.endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"

    logger.debug("Using LM Studio: %s at %s", model_name, base_url)
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=get_first_secret("LM_API_TOKEN", default="") or "lm-studio",
        temperature=temperature,
    )


def build_local_api_model(model_name: str, temperature: float) -> Any:
    """Build a ChatOpenAI instance for generic local OpenAI-compatible API.

    The base URL is resolved from environment variables in priority order:
    ``OPENAI_BASE_URL``, ``OPENAI_API_BASE``, ``LOCAL_AI_API_BASE_URL``,
    ``LOCAL_OPENAI_BASE_URL``, falling back to ``http://localhost:1234/v1``.

    Parameters
    ----------
    model_name:
        Bare model name after the ``local-api:`` prefix.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``ChatOpenAI`` instance pointed at the local API endpoint.

    Raises
    ------
    ImportError
        If ``langchain-openai`` is not installed.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "langchain-openai is required for local API models. "
            "Install with: pip install langchain-openai"
        ) from exc

    base_url = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
        or os.getenv("LOCAL_AI_API_BASE_URL")
        or os.getenv("LOCAL_OPENAI_BASE_URL")
        or "http://localhost:1234/v1"
    )
    if not base_url.endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"

    logger.debug("Using Local API: %s at %s", model_name, base_url)
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key="local-api",
        temperature=temperature,
    )


def build_local_onnx_model(model_name: str, temperature: float) -> Any:
    """Build a minimal chat wrapper over repo-local ONNX via ``LLMClient``.

    Constructs and returns a ``LocalOnnxChatModel`` subclass of
    ``BaseChatModel``.  This path is prompt-only and does **not** support
    structured tool-calling.

    Parameters
    ----------
    model_name:
        Bare model name after the ``local:`` prefix, e.g. ``phi4mini``.
    temperature:
        Sampling temperature.

    Returns
    -------
    A ``BaseChatModel`` instance backed by the repo's ``LLMClient``.

    Raises
    ------
    ImportError
        If ``langchain-core`` is not installed or ``tools.llm.llm_client``
        cannot be imported.
    """
    try:
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import (
            AIMessage,
            BaseMessage,
            HumanMessage,
            SystemMessage,
        )
        from langchain_core.outputs import ChatGeneration, ChatResult
    except ImportError as exc:
        raise ImportError(
            "langchain-core is required for local ONNX chat wrapper. "
            "Install with: pip install langchain-core"
        ) from exc

    llm_client = _import_repo_llm_client()
    key = (model_name or "phi4mini").strip()

    class LocalOnnxChatModel(BaseChatModel):
        model_key: str = key
        default_temperature: float = temperature

        @property
        def _llm_type(self) -> str:
            return "local-onnx"

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

        def _messages_to_prompt(
            self,
            messages: list[BaseMessage],
        ) -> tuple[str, str | None]:
            system_text: str | None = None
            chunks: list[str] = []
            for msg in messages:
                if isinstance(msg, SystemMessage):
                    system_text = str(msg.content)
                elif isinstance(msg, HumanMessage):
                    chunks.append(f"User: {msg.content}")
                else:
                    chunks.append(f"Assistant: {msg.content}")
            prompt = "\n\n".join(chunks) if chunks else ""
            return prompt, system_text

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any | None = None,
            **kwargs: Any,
        ) -> Any:
            prompt, system_text = self._messages_to_prompt(messages)
            response = llm_client.generate_text(
                model_name=f"local:{self.model_key}",
                prompt=prompt,
                system_instruction=system_text,
                temperature=float(kwargs.get("temperature", self.default_temperature)),
                max_tokens=int(kwargs.get("max_tokens", 4096)),
            )
            text = response
            if stop:
                for token in stop:
                    if token and token in text:
                        text = text.split(token, 1)[0]
                        break
            message = AIMessage(content=text)
            return ChatResult(generations=[ChatGeneration(message=message)])

    logger.warning(
        "Using local ONNX wrapper for 'local:%s'. This path is prompt-only and "
        "does not support structured tool-calling.",
        key,
    )
    return LocalOnnxChatModel()


def _get_placeholder_chat_model_cls() -> Any:
    """Return the module-level ``PlaceholderChatModel`` class, building it lazily.

    Deferred so that users who never take the no-LLM LangChain path
    aren't forced to install ``langchain-core``.  Cached so all callers
    see the same class object (``isinstance`` checks and pickling both
    rely on class identity).
    """
    global _PLACEHOLDER_CHAT_MODEL_CLS
    if _PLACEHOLDER_CHAT_MODEL_CLS is not None:
        return _PLACEHOLDER_CHAT_MODEL_CLS

    try:
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
        from langchain_core.outputs import (
            ChatGeneration,
            ChatGenerationChunk,
            ChatResult,
        )
    except ImportError as exc:
        raise ImportError(
            "langchain-core is required for the placeholder chat model. "
            "Install with: pip install langchain-core"
        ) from exc

    # Late import to keep the module import graph acyclic and cheap when
    # the no-LLM path isn't exercised.
    from ..models.backends import PLACEHOLDER_RESPONSE_TEXT

    class PlaceholderChatModel(BaseChatModel):
        """Deterministic LangChain chat model used under ``AGENTIC_NO_LLM=1``.

        Returns :data:`PLACEHOLDER_RESPONSE_TEXT` for every prompt, on
        every engine path (sync ``_generate`` and async ``_astream``).
        ``bind_tools`` returns a *new* instance rather than ``self`` so
        concurrent callers cannot accidentally share mutable state (P3
        from Sprint B #5 follow-up review).
        """

        @property
        def _llm_type(self) -> str:
            return "placeholder"

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            # Intentionally returns a fresh instance, not ``self``: matches
            # LangChain's "bind_tools returns a new thing" contract well
            # enough for the placeholder use case without implementing
            # the full ``RunnableBinding`` protocol.  Tools are ignored —
            # the placeholder response never produces tool calls.
            return PlaceholderChatModel()

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any | None = None,
            **kwargs: Any,
        ) -> Any:
            return ChatResult(
                generations=[
                    ChatGeneration(message=AIMessage(content=PLACEHOLDER_RESPONSE_TEXT))
                ]
            )

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any | None = None,
            **kwargs: Any,
        ) -> Any:
            # One-shot chunk — matches the documented "streaming yields
            # the entire placeholder as one chunk" contract.  Defining
            # this explicitly (rather than inheriting the ABC fallback
            # that re-runs ``_generate`` in a thread pool) future-proofs
            # against upstream signature churn (P1).
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=PLACEHOLDER_RESPONSE_TEXT)
            )

    _PLACEHOLDER_CHAT_MODEL_CLS = PlaceholderChatModel
    return _PLACEHOLDER_CHAT_MODEL_CLS


def build_placeholder_model(_temperature: float = 0.0) -> Any:
    """Build a LangChain chat model that returns a fixed placeholder.

    Used when ``AGENTIC_NO_LLM=1``.  No API calls, no provider package
    beyond ``langchain-core`` (the only hard dep of the LangChain engine
    — declared in the ``[langchain]`` install extra).  ``bind_tools`` is
    accepted and ignored so workflows that bind tools don't crash; the
    returned model never emits tool calls.

    The placeholder class is cached module-wide so every call returns an
    instance of the *same* class; ``isinstance`` checks across calls are
    stable.
    """
    cls = _get_placeholder_chat_model_cls()
    global _PLACEHOLDER_WARNED
    if not _PLACEHOLDER_WARNED:
        logger.warning(
            "AGENTIC_NO_LLM=1: LangChain engine using PlaceholderChatModel. "
            "Disable for production workloads."
        )
        _PLACEHOLDER_WARNED = True
    return cls()


def _reset_placeholder_state_for_tests() -> None:
    """Reset module-level placeholder caches.  For test fixtures only.

    Clears both the warning flag (so caplog assertions work across
    tests) and the cached class (so test runs that toggle the flag mid-
    session don't see a stale class object).
    """
    global _PLACEHOLDER_WARNED, _PLACEHOLDER_CHAT_MODEL_CLS
    _PLACEHOLDER_WARNED = False
    _PLACEHOLDER_CHAT_MODEL_CLS = None
