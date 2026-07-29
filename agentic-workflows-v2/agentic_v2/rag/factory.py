"""RAG component factory — turn a :class:`RAGConfig` into live objects.

``RAGConfig`` describes a pipeline, but a description only matters if something
reads it.  This module is what reads it: it resolves
``RAGConfig.vectorstore_type``, ``EmbeddingConfig.provider``, and
``RerankerConfig.strategy`` into constructed components.

Provides:
- :func:`build_embedder`: ``EmbeddingConfig`` → a provider-backed embedder.
- :func:`build_vectorstore`: ``RAGConfig`` → an in-memory or LanceDB store.
- :func:`build_reranker`: ``RerankerConfig`` → a reranker.
- :func:`build_rag_components`: all three at once, bundled as
  :class:`RAGComponents`.

Optional backends stay optional.  This module imports cleanly with neither
``litellm`` nor ``lancedb`` installed; a typed error naming
``pip install -e ".[rag]"`` is raised only when a component that needs one is
actually requested.

Note:
    No builder ever returns :class:`~agentic_v2.rag.embeddings.InMemoryEmbedder`.
    That class is a deterministic hash-based **test double**; handing it back for
    a production provider string would silently index fake vectors.  Construct it
    directly when you want it.

Note:
    ``RerankerConfig.top_k`` is not a constructor argument for any reranker — it
    is a per-call argument of ``rerank()``.  Callers must pass
    ``top_k=config.reranker.top_k`` themselves at retrieval time.

Note:
    Call every reranker returned here **positionally**.
    :class:`~agentic_v2.rag.reranking.NoOpReranker` names its first parameter
    ``_query`` where :class:`RerankerProtocol` declares ``query``, so
    ``rerank(query=..., results=...)`` raises ``TypeError`` for the ``"none"``
    strategy while succeeding for the other two.  mypy does not flag the
    mismatch, so nothing catches it before runtime.  Closing it means renaming
    the parameter in ``reranking.py``; it is recorded here, not hidden.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from . import vectorstore as _vectorstore
from .config import EmbeddingConfig, RAGConfig, RerankerConfig
from .embeddings import FallbackEmbedder, LiteLLMEmbedder
from .errors import RAGError, VectorStoreError
from .protocols import EmbeddingProtocol, RerankerProtocol, VectorStoreProtocol
from .reranking import CrossEncoderReranker, LLMReranker, NoOpReranker
from .vectorstore import InMemoryVectorStore

logger = logging.getLogger(__name__)


# Scoring callables the reranker strategies need but ``RerankerConfig`` — a
# frozen, JSON-shaped Pydantic model — cannot carry.
CrossEncoderPredictFn = Callable[[list[tuple[str, str]]], Sequence[float]]
LLMScoreFn = Callable[[str, str], Awaitable[float]]

# ADR-035 documents the embedding fallback order as Voyage → OpenAI
# text-embedding-3-small → local Nomic Embed Text v2 via Ollama.  The configured
# provider always leads the chain; these are the remaining providers, in that
# documented order.
FALLBACK_PROVIDER_ORDER: Final[tuple[str, ...]] = ("voyage", "openai", "local")

# Default model id per fallback provider.  ADR-035 names the OpenAI and Nomic
# models exactly but names the Voyage *family* ("Voyage 4") rather than a
# concrete model id, so the generally available ``voyage-3`` is used.
FALLBACK_EMBEDDING_MODELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "voyage": "voyage-3",
        "openai": "text-embedding-3-small",
        "local": "nomic-embed-text",
    }
)

_RAG_EXTRA_HINT: Final[str] = 'install the RAG extra with: pip install -e ".[rag]"'


@dataclass(frozen=True)
class RAGComponents:
    """Live pipeline components built from a single :class:`RAGConfig`.

    Attributes:
        embedder: Provider-backed embedding component.
        vectorstore: Vector store backend.
        reranker: Reranker (a :class:`NoOpReranker` when reranking is off).
    """

    embedder: EmbeddingProtocol
    vectorstore: VectorStoreProtocol
    reranker: RerankerProtocol


def _fallback_chain(config: EmbeddingConfig) -> list[LiteLLMEmbedder]:
    """Build the ADR-035 embedding fallback chain for *config*.

    The configured provider leads; the remaining providers follow in the order
    ADR-035 documents.  Every member inherits *config*'s dimensions, batch size,
    and concurrency limit, which is what makes the chain constructible at all —
    :class:`FallbackEmbedder` rejects providers whose dimensions differ.

    Args:
        config: Embedding configuration for the primary provider.

    Returns:
        Ordered embedders, primary first.

    Raises:
        EmbeddingError: If any provider in the chain has no LiteLLM routing rule.
    """
    chain = [LiteLLMEmbedder(config)]
    for provider in FALLBACK_PROVIDER_ORDER:
        if provider == config.provider:
            continue
        variant = config.model_copy(
            update={
                "provider": provider,
                "model_name": FALLBACK_EMBEDDING_MODELS[provider],
            }
        )
        chain.append(LiteLLMEmbedder(variant))
    return chain


def build_embedder(
    config: EmbeddingConfig,
    *,
    fallback: bool = False,
) -> EmbeddingProtocol:
    """Build the embedder described by *config*.

    Args:
        config: Embedding settings — provider, model, dimensions, batching.
        fallback: Wrap the configured provider in the ADR-035 fallback chain.
            Off by default, because chained providers embed into *different*
            semantic spaces and a single index built from a chain retrieves
            worse without ever erroring.

    Returns:
        A :class:`LiteLLMEmbedder`, or a :class:`FallbackEmbedder` over the
        ADR-035 chain when *fallback* is set.

    Raises:
        EmbeddingError: If ``config.provider`` has no LiteLLM routing rule.
    """
    if not fallback:
        return LiteLLMEmbedder(config)

    chain = _fallback_chain(config)
    logger.warning(
        "Embedding fallback chain enabled (%s) pinned to %d dimensions. "
        "Providers embed into different semantic spaces; mixing their vectors "
        "in one index degrades retrieval silently. A provider whose native "
        "width differs fails with EmbeddingError rather than storing a "
        "mismatched vector.",
        ", ".join(embedder.litellm_model for embedder in chain),
        config.dimensions,
    )
    return FallbackEmbedder(chain, allow_mixed_provider_identities=True)


def build_vectorstore(config: RAGConfig) -> VectorStoreProtocol:
    """Build the vector store described by *config*.

    Args:
        config: Pipeline configuration supplying ``vectorstore_type``,
            ``db_path``, ``collection_name``, and the embedding dimensionality.

    Returns:
        An :class:`InMemoryVectorStore` or a ``LanceDBVectorStore``.

    Raises:
        VectorStoreError: If ``vectorstore_type`` is ``"lancedb"`` and either
            the ``lancedb`` package is missing or ``db_path`` is unset.
    """
    if config.vectorstore_type == "memory":
        return InMemoryVectorStore()

    store_cls = _vectorstore.LanceDBVectorStore
    if store_cls is None:
        raise VectorStoreError(
            "vectorstore_type='lancedb' was requested but the lancedb package "
            f"is not installed; {_RAG_EXTRA_HINT}"
        )

    db_path = config.db_path
    if db_path is None:
        raise VectorStoreError("db_path is required when vectorstore_type is 'lancedb'")

    # LanceDBVectorStore does not structurally satisfy VectorStoreProtocol:
    # its search() names the third parameter ``_metadata_filter`` (metadata
    # filtering is unimplemented for LanceDB, see vectorstore.py:327), so a
    # keyword call with ``metadata_filter=`` fails there.  Fixing that is a
    # change to vectorstore.py; the mismatch is recorded, not hidden.
    return store_cls(  # type: ignore[return-value]
        db_path=db_path,
        table_name=config.collection_name,
        embedding_dim=config.embedding.dimensions,
    )


def _build_cross_encoder(
    config: RerankerConfig,
    predict_fn: CrossEncoderPredictFn | None,
) -> CrossEncoderReranker:
    """Build a cross-encoder reranker from *config*.

    Args:
        config: Reranking settings supplying ``model_name`` and ``batch_size``.
        predict_fn: Scoring callable ``(pairs) → scores``.  When ``None``,
            :class:`CrossEncoderReranker` loads ``sentence-transformers``, which
            is **not** declared by any extra and must be installed separately.

    Returns:
        The constructed reranker.

    Raises:
        ImportError: If *predict_fn* is ``None`` and ``sentence-transformers``
            is not installed.
    """
    kwargs: dict[str, Any] = {"batch_size": config.batch_size}
    if config.model_name is not None:
        kwargs["model_name"] = config.model_name
    if predict_fn is not None:
        kwargs["predict_fn"] = predict_fn
    return CrossEncoderReranker(**kwargs)


def build_reranker(
    config: RerankerConfig,
    *,
    predict_fn: CrossEncoderPredictFn | None = None,
    score_fn: LLMScoreFn | None = None,
) -> RerankerProtocol:
    """Build the reranker described by *config*.

    ``RerankerConfig`` cannot express a callable, so the two model-backed
    strategies take their scorer here rather than from config.

    Args:
        config: Reranking settings.
        predict_fn: Cross-encoder scorer ``(pairs) → scores``.
        score_fn: Async LLM scorer ``(query, document) → score``.  Required for
            the ``"llm"`` strategy, which has no default.

    Returns:
        A reranker satisfying :class:`RerankerProtocol` structurally.  Call it
        positionally — see the ``NoOpReranker`` caveat in the module docstring.

    Raises:
        RAGError: If ``strategy`` is ``"llm"`` without a *score_fn*, or the
            strategy is unrecognised.
        ImportError: If ``strategy`` is ``"cross_encoder"``, no *predict_fn* is
            given, and ``sentence-transformers`` is not installed.
    """
    if config.strategy == "none":
        # Positional-call only; see the NoOpReranker note in the module docstring.
        return NoOpReranker()

    if config.strategy == "cross_encoder":
        return _build_cross_encoder(config, predict_fn)

    if config.strategy == "llm":
        if score_fn is None:
            raise RAGError(
                "reranker strategy 'llm' requires an async score_fn; "
                "RerankerConfig cannot carry a callable, so pass "
                "score_fn=... to build_reranker()"
            )
        return LLMReranker(score_fn=score_fn)

    raise RAGError(f"Unsupported reranker strategy '{config.strategy}'")


def build_rag_components(
    config: RAGConfig,
    *,
    fallback_embeddings: bool = False,
    reranker_predict_fn: CrossEncoderPredictFn | None = None,
    reranker_score_fn: LLMScoreFn | None = None,
) -> RAGComponents:
    """Build every component described by *config* in one call.

    Args:
        config: Full pipeline configuration.
        fallback_embeddings: Forwarded to :func:`build_embedder` as *fallback*.
        reranker_predict_fn: Forwarded to :func:`build_reranker`.
        reranker_score_fn: Forwarded to :func:`build_reranker`.

    Returns:
        The bundled embedder, vector store, and reranker.

    Raises:
        EmbeddingError: If the embedding provider has no LiteLLM routing rule.
        VectorStoreError: If a LanceDB store is requested without ``lancedb``.
        RAGError: If the reranker strategy cannot be satisfied.
    """
    return RAGComponents(
        embedder=build_embedder(config.embedding, fallback=fallback_embeddings),
        vectorstore=build_vectorstore(config),
        reranker=build_reranker(
            config.reranker,
            predict_fn=reranker_predict_fn,
            score_fn=reranker_score_fn,
        ),
    )
