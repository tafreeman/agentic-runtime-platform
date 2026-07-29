"""Tests for the RAG component factory — config strings to live objects.

These tests must pass both locally (where the optional ``rag`` extra is
installed) and in CI (where it is not).  Nothing here depends on the ambient
presence or absence of ``litellm``, ``lancedb``, or ``sentence-transformers``:
every optional backend is either injected as a fake or explicitly blocked with
``monkeypatch``, in both directions.  No test performs network I/O and no test
uses a real credential.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from agentic_v2.rag import embeddings as rag_embeddings
from agentic_v2.rag import vectorstore as rag_vectorstore
from agentic_v2.rag.config import (
    EmbeddingConfig,
    RAGConfig,
    RerankerConfig,
)
from agentic_v2.rag.contracts import Chunk, RetrievalResult
from agentic_v2.rag.embeddings import FallbackEmbedder, LiteLLMEmbedder
from agentic_v2.rag.errors import EmbeddingError, RAGError, VectorStoreError
from agentic_v2.rag.factory import (
    FALLBACK_EMBEDDING_MODELS,
    RAGComponents,
    build_embedder,
    build_rag_components,
    build_reranker,
    build_vectorstore,
)
from agentic_v2.rag.protocols import (
    EmbeddingProtocol,
    RerankerProtocol,
    VectorStoreProtocol,
)
from agentic_v2.rag.reranking import (
    CrossEncoderReranker,
    LLMReranker,
    NoOpReranker,
)
from agentic_v2.rag.vectorstore import InMemoryVectorStore

RAG_EXTRA_HINT = 'pip install -e ".[rag]"'

# Obviously-fake placeholders. The providers are never contacted; these exist
# only so the embedder's credential check passes and the fake records them.
FAKE_VOYAGE_KEY = "fake-voyage-key-not-real"
FAKE_OPENAI_KEY = "fake-openai-key-not-real"


# ── Fakes for the optional backends ──────────────────────────────────────────


class _FakeLiteLLM:
    """Stand-in for the optional ``litellm`` module.

    Records every request and returns fixed-width vectors, so the whole embed
    path runs where ``litellm`` is genuinely absent.  Accepts arguments through
    ``**kwargs`` because the real API's parameter is named ``input``.
    """

    def __init__(
        self,
        *,
        dimensions: int,
        vectors: Mapping[str, Sequence[float]] | None = None,
        failing_models: Iterable[str] = (),
    ) -> None:
        self.dimensions = dimensions
        self._vectors = dict(vectors or {})
        self._failing_models = frozenset(failing_models)
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.api_keys: list[str | None] = []

    async def aembedding(self, **kwargs: Any) -> dict[str, Any]:
        """Return one vector per input text, or fail for a configured model."""
        model = str(kwargs["model"])
        texts = [str(text) for text in kwargs["input"]]
        self.calls.append((model, tuple(texts)))
        self.api_keys.append(kwargs.get("api_key"))
        if model in self._failing_models:
            raise RuntimeError(f"simulated provider outage for {model}")
        return {"data": [{"embedding": self._vector(text)} for text in texts]}

    @property
    def called_models(self) -> list[str]:
        """Model strings requested so far, in call order."""
        return [model for model, _ in self.calls]

    def _vector(self, text: str) -> list[float]:
        preset = self._vectors.get(text)
        if preset is not None:
            return [float(value) for value in preset]
        return [1.0] + [0.0] * (self.dimensions - 1)


class _RecordingLanceDB:
    """Stand-in for ``LanceDBVectorStore`` that records its constructor args.

    Satisfies :class:`VectorStoreProtocol` so the factory's return value can be
    protocol-checked without ``lancedb`` installed and without touching disk.
    """

    def __init__(
        self,
        db_path: str,
        table_name: str = "chunks",
        embedding_dim: int = 1536,
    ) -> None:
        self.db_path = db_path
        self.table_name = table_name
        self.embedding_dim = embedding_dim

    async def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Accept and discard — construction is what these tests assert on."""

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[RetrievalResult]:
        """Return no matches."""
        return []

    async def delete(self, document_id: str) -> bool:
        """Report nothing deleted."""
        return False


class _ExplodingLanceDB(_RecordingLanceDB):
    """Fails loudly if constructed — proves the factory was never reached."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("build_vectorstore should not have been reached")


class _RecordingCrossEncoder:
    """Stand-in for ``sentence_transformers.CrossEncoder``."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.predict_calls: list[dict[str, Any]] = []

    def predict(
        self, pairs: list[tuple[str, str]], *, batch_size: int = 32
    ) -> list[float]:
        """Score ascending, so the last candidate ranks first after sorting."""
        self.predict_calls.append({"pairs": list(pairs), "batch_size": batch_size})
        return [float(index) for index in range(len(pairs))]


def _fake_sentence_transformers(
    created: list[_RecordingCrossEncoder],
) -> SimpleNamespace:
    """Build a fake ``sentence_transformers`` module recording every model."""

    def _cross_encoder(model_name: str) -> _RecordingCrossEncoder:
        encoder = _RecordingCrossEncoder(model_name)
        created.append(encoder)
        return encoder

    return SimpleNamespace(CrossEncoder=_cross_encoder)


# ── Shared helpers ───────────────────────────────────────────────────────────


def _use_fake_litellm(
    monkeypatch: pytest.MonkeyPatch,
    fake: _FakeLiteLLM,
    *,
    via_sys_modules: bool = False,
) -> None:
    """Route the embedder's lazy import at the documented seam."""
    if via_sys_modules:
        monkeypatch.setitem(sys.modules, "litellm", fake)
        return
    monkeypatch.setattr(rag_embeddings, "_load_litellm", lambda: fake)


def _make_chunk(content: str, index: int) -> Chunk:
    return Chunk(
        chunk_id=f"chunk-{index}",
        document_id="doc-1",
        chunk_index=index,
        content=content,
        metadata={"source": "unit-test"},
    )


def _make_result(content: str, score: float = 0.5) -> RetrievalResult:
    return RetrievalResult(
        content=content,
        score=score,
        document_id="doc-1",
        chunk_id=f"chunk-{content}",
        metadata={},
    )


# ── build_vectorstore ────────────────────────────────────────────────────────


class TestBuildVectorstore:
    """``RAGConfig.vectorstore_type`` resolves to a live store."""

    def test_memory_type_builds_in_memory_store(self) -> None:
        store = build_vectorstore(RAGConfig(vectorstore_type="memory"))

        assert isinstance(store, InMemoryVectorStore)
        assert isinstance(store, VectorStoreProtocol)

    def test_memory_is_the_default_backend(self) -> None:
        assert isinstance(build_vectorstore(RAGConfig()), InMemoryVectorStore)

    def test_lancedb_receives_path_collection_and_dimensions(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setattr(
            rag_vectorstore, "LanceDBVectorStore", _RecordingLanceDB, raising=False
        )
        config = RAGConfig(
            vectorstore_type="lancedb",
            db_path=str(tmp_path / "vectors"),
            collection_name="knowledge",
            embedding=EmbeddingConfig(dimensions=256),
        )

        store = build_vectorstore(config)

        assert isinstance(store, _RecordingLanceDB)
        assert store.db_path == str(tmp_path / "vectors")
        assert store.table_name == "knowledge"
        assert store.embedding_dim == 256
        assert isinstance(store, VectorStoreProtocol)

    def test_lancedb_requested_but_not_installed_raises_vectorstore_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        # The exact failure a user hits with `pip install -e .` and no extra:
        # the module-level symbol is None, so calling it would be a TypeError.
        monkeypatch.setattr(rag_vectorstore, "LanceDBVectorStore", None, raising=False)
        config = RAGConfig(vectorstore_type="lancedb", db_path=str(tmp_path))

        with pytest.raises(VectorStoreError) as exc_info:
            build_vectorstore(config)

        message = str(exc_info.value)
        assert RAG_EXTRA_HINT in message
        assert "lancedb" in message
        # A TypeError from calling None would tell the user nothing actionable.
        assert not isinstance(exc_info.value, TypeError)

    def test_lancedb_without_db_path_is_rejected_by_config_not_the_factory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the factory were reached, constructing the store would raise
        # RuntimeError and this test would fail with the wrong exception type.
        monkeypatch.setattr(
            rag_vectorstore, "LanceDBVectorStore", _ExplodingLanceDB, raising=False
        )

        with pytest.raises(ValidationError, match="db_path is required"):
            build_vectorstore(RAGConfig(vectorstore_type="lancedb"))

    def test_lancedb_with_none_db_path_that_bypassed_validation_is_caught(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``model_construct`` skips validators, so the factory's own guard is
        # the last line of defence for a config built that way.
        monkeypatch.setattr(
            rag_vectorstore, "LanceDBVectorStore", _RecordingLanceDB, raising=False
        )
        config = RAGConfig.model_construct(vectorstore_type="lancedb", db_path=None)

        with pytest.raises(VectorStoreError, match="db_path is required"):
            build_vectorstore(config)


# ── build_embedder ───────────────────────────────────────────────────────────


class TestBuildEmbedder:
    """``EmbeddingConfig.provider`` resolves to a LiteLLM-routed embedder."""

    @pytest.mark.parametrize(
        ("provider", "model_name", "expected_model_string"),
        [
            ("openai", "text-embedding-3-small", "openai/text-embedding-3-small"),
            ("voyage", "voyage-3", "voyage/voyage-3"),
            ("local", "nomic-embed-text", "ollama/nomic-embed-text"),
            ("litellm", "azure/my-deployment", "azure/my-deployment"),
        ],
    )
    def test_provider_routes_to_expected_litellm_model_string(
        self, provider: str, model_name: str, expected_model_string: str
    ) -> None:
        config = EmbeddingConfig(
            provider=provider,  # type: ignore[arg-type]
            model_name=model_name,
            dimensions=64,
        )

        embedder = build_embedder(config)

        assert isinstance(embedder, LiteLLMEmbedder)
        assert embedder.litellm_model == expected_model_string
        assert embedder.provider == provider
        assert embedder.model_name == model_name
        assert embedder.dimensions == 64
        assert embedder.embedding_identity.provider == provider
        assert embedder.embedding_identity.model_name == model_name
        assert isinstance(embedder, EmbeddingProtocol)

    def test_unknown_provider_raises_embedding_error_naming_the_options(self) -> None:
        # Literal validation normally blocks this; ``model_construct`` skips it.
        config = EmbeddingConfig.model_construct(
            provider="cohere", model_name="embed-english-v3"
        )

        with pytest.raises(EmbeddingError, match="Unsupported LiteLLM embedding"):
            build_embedder(config)

    def test_fallback_is_off_by_default(self) -> None:
        embedder = build_embedder(EmbeddingConfig(dimensions=8))

        assert isinstance(embedder, LiteLLMEmbedder)
        assert not isinstance(embedder, FallbackEmbedder)

    def test_fallback_chain_is_constructible_and_shares_dimensions(self) -> None:
        config = EmbeddingConfig(provider="voyage", model_name="voyage-3", dimensions=8)

        embedder = build_embedder(config, fallback=True)

        assert isinstance(embedder, FallbackEmbedder)
        # FallbackEmbedder rejects a chain whose members disagree on width or
        # identity; reaching here means the factory built an accepted chain.
        assert embedder.dimensions == 8
        assert embedder.provider == "fallback"
        assert embedder.model_name == "explicitly-compatible"
        assert isinstance(embedder, EmbeddingProtocol)

    def test_fallback_warns_about_the_mixed_semantic_space(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = EmbeddingConfig(dimensions=8)

        with caplog.at_level(logging.WARNING, logger="agentic_v2.rag.factory"):
            build_embedder(config, fallback=True)

        warnings = [
            record.getMessage()
            for record in caplog.records
            if record.levelno >= logging.WARNING
        ]
        assert any("different semantic spaces" in message for message in warnings)

    async def test_fallback_tries_providers_in_the_documented_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VOYAGE_API_KEY", FAKE_VOYAGE_KEY)
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI_KEY)
        expected_order = [
            "voyage/voyage-3",
            f"openai/{FALLBACK_EMBEDDING_MODELS['openai']}",
            f"ollama/{FALLBACK_EMBEDDING_MODELS['local']}",
        ]
        fake = _FakeLiteLLM(dimensions=4, failing_models=expected_order)
        _use_fake_litellm(monkeypatch, fake)
        config = EmbeddingConfig(provider="voyage", model_name="voyage-3", dimensions=4)

        embedder = build_embedder(config, fallback=True)

        with pytest.raises(EmbeddingError, match="All 3 embedding providers failed"):
            await embedder.embed(["hello"])
        assert fake.called_models == expected_order

    async def test_fallback_returns_the_first_provider_that_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VOYAGE_API_KEY", FAKE_VOYAGE_KEY)
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI_KEY)
        fake = _FakeLiteLLM(dimensions=4, failing_models=["voyage/voyage-3"])
        _use_fake_litellm(monkeypatch, fake)
        config = EmbeddingConfig(provider="voyage", model_name="voyage-3", dimensions=4)

        embedder = build_embedder(config, fallback=True)
        vectors = await embedder.embed(["hello"])

        assert vectors == [[1.0, 0.0, 0.0, 0.0]]
        assert fake.called_models == [
            "voyage/voyage-3",
            f"openai/{FALLBACK_EMBEDDING_MODELS['openai']}",
        ]

    async def test_configured_provider_leads_the_fallback_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI_KEY)
        fake = _FakeLiteLLM(dimensions=4)
        _use_fake_litellm(monkeypatch, fake)
        config = EmbeddingConfig(
            provider="openai", model_name="text-embedding-3-large", dimensions=4
        )

        embedder = build_embedder(config, fallback=True)
        await embedder.embed(["hello"])

        # The configured model is tried first and no duplicate openai entry is
        # appended from the documented order.
        assert fake.called_models == ["openai/text-embedding-3-large"]


# ── build_reranker ───────────────────────────────────────────────────────────


class TestBuildReranker:
    """``RerankerConfig.strategy`` resolves to a live reranker."""

    async def test_none_strategy_builds_a_passthrough_reranker(self) -> None:
        reranker = build_reranker(RerankerConfig(strategy="none"))
        results = [_make_result("a"), _make_result("b"), _make_result("c")]

        # Positional call — see the NoOpReranker note in the factory docstring.
        reranked = await reranker.rerank("query", results, top_k=2)

        assert isinstance(reranker, NoOpReranker)
        assert isinstance(reranker, RerankerProtocol)
        assert [result.content for result in reranked] == ["a", "b"]

    async def test_cross_encoder_uses_the_injected_predict_fn(self) -> None:
        def predict(pairs: list[tuple[str, str]]) -> list[float]:
            return [float(index) for index in range(len(pairs))]

        reranker = build_reranker(
            RerankerConfig(strategy="cross_encoder"), predict_fn=predict
        )
        results = [_make_result("first"), _make_result("second")]

        reranked = await reranker.rerank("query", results, top_k=2)

        assert isinstance(reranker, CrossEncoderReranker)
        assert isinstance(reranker, RerankerProtocol)
        # Ascending scores mean the last candidate ranks first.
        assert [result.content for result in reranked] == ["second", "first"]

    async def test_cross_encoder_forwards_model_name_and_batch_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created: list[_RecordingCrossEncoder] = []
        monkeypatch.setitem(
            sys.modules, "sentence_transformers", _fake_sentence_transformers(created)
        )
        config = RerankerConfig(
            strategy="cross_encoder",
            model_name="cross-encoder/ms-marco-MiniLM-L-12-v2",
            batch_size=4,
        )

        reranker = build_reranker(config)
        await reranker.rerank("query", [_make_result("only")], top_k=1)

        assert len(created) == 1
        assert created[0].model_name == "cross-encoder/ms-marco-MiniLM-L-12-v2"
        assert created[0].predict_calls[0]["batch_size"] == 4

    async def test_cross_encoder_default_model_name_is_left_to_the_library(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created: list[_RecordingCrossEncoder] = []
        monkeypatch.setitem(
            sys.modules, "sentence_transformers", _fake_sentence_transformers(created)
        )

        build_reranker(RerankerConfig(strategy="cross_encoder"))

        # ``RerankerConfig.model_name`` defaults to None; the factory must not
        # forward that None and clobber the library's own default.
        assert created[0].model_name == "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def test_cross_encoder_without_sentence_transformers_names_the_install(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # sentence-transformers is declared by no extra in pyproject.toml, so
        # this is the out-of-the-box experience even with `.[rag]` installed.
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)

        with pytest.raises(ImportError, match="sentence-transformers is required"):
            build_reranker(RerankerConfig(strategy="cross_encoder"))

    def test_llm_strategy_without_score_fn_raises_a_typed_error(self) -> None:
        with pytest.raises(RAGError, match="requires an async score_fn"):
            build_reranker(RerankerConfig(strategy="llm"))

    async def test_llm_strategy_uses_the_injected_score_fn(self) -> None:
        async def score(query: str, document: str) -> float:
            return float(len(document))

        reranker = build_reranker(RerankerConfig(strategy="llm"), score_fn=score)
        results = [_make_result("short"), _make_result("much-longer-text")]

        reranked = await reranker.rerank("query", results, top_k=2)

        assert isinstance(reranker, LLMReranker)
        assert isinstance(reranker, RerankerProtocol)
        assert [result.content for result in reranked] == [
            "much-longer-text",
            "short",
        ]

    def test_unrecognised_strategy_raises_a_typed_error(self) -> None:
        # Literal validation normally blocks this; ``model_construct`` skips it.
        config = RerankerConfig.model_construct(strategy="hybrid")

        with pytest.raises(RAGError, match="Unsupported reranker strategy 'hybrid'"):
            build_reranker(config)


# ── build_rag_components ─────────────────────────────────────────────────────


class TestBuildRAGComponents:
    """One config in, three protocol-satisfying components out."""

    def test_bundle_parts_satisfy_their_protocols(self) -> None:
        components = build_rag_components(RAGConfig())

        assert isinstance(components, RAGComponents)
        assert isinstance(components.embedder, EmbeddingProtocol)
        assert isinstance(components.vectorstore, VectorStoreProtocol)
        assert isinstance(components.reranker, RerankerProtocol)

    def test_bundle_is_immutable(self) -> None:
        components = build_rag_components(RAGConfig())
        replacement = build_embedder(EmbeddingConfig(dimensions=8))

        with pytest.raises((AttributeError, TypeError)):
            components.embedder = replacement  # type: ignore[misc]

        assert components.embedder is not replacement

    def test_bundle_honours_the_configured_backends(self) -> None:
        config = RAGConfig(
            embedding=EmbeddingConfig(
                provider="voyage", model_name="voyage-3", dimensions=8
            ),
        )

        components = build_rag_components(config)

        assert isinstance(components.embedder, LiteLLMEmbedder)
        assert components.embedder.litellm_model == "voyage/voyage-3"
        assert isinstance(components.vectorstore, InMemoryVectorStore)
        assert isinstance(components.reranker, NoOpReranker)

    def test_fallback_embeddings_flag_is_forwarded(self) -> None:
        components = build_rag_components(
            RAGConfig(embedding=EmbeddingConfig(dimensions=8)),
            fallback_embeddings=True,
        )

        assert isinstance(components.embedder, FallbackEmbedder)

    def test_reranker_scorers_are_forwarded(self) -> None:
        def predict(pairs: list[tuple[str, str]]) -> list[float]:
            return [0.0] * len(pairs)

        components = build_rag_components(
            RAGConfig(reranker=RerankerConfig(strategy="cross_encoder")),
            reranker_predict_fn=predict,
        )

        assert isinstance(components.reranker, CrossEncoderReranker)

    def test_missing_lancedb_surfaces_through_the_bundle(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setattr(rag_vectorstore, "LanceDBVectorStore", None, raising=False)
        config = RAGConfig(vectorstore_type="lancedb", db_path=str(tmp_path))

        with pytest.raises(VectorStoreError, match=re.escape(RAG_EXTRA_HINT)):
            build_rag_components(config)

    async def test_built_components_ingest_and_retrieve_end_to_end(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cats = "alpha document about cats"
        dogs = "beta document about dogs"
        fake = _FakeLiteLLM(
            dimensions=4,
            vectors={
                cats: [1.0, 0.0, 0.0, 0.0],
                dogs: [0.0, 1.0, 0.0, 0.0],
                "cats": [1.0, 0.0, 0.0, 0.0],
            },
        )
        # Route through the real lazy import to prove the built pipeline works
        # with litellm absent from the environment entirely.
        _use_fake_litellm(monkeypatch, fake, via_sys_modules=True)
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI_KEY)
        config = RAGConfig(
            embedding=EmbeddingConfig(dimensions=4, batch_size=1),
            top_k=2,
        )

        components = build_rag_components(config)
        chunks = [_make_chunk(cats, 0), _make_chunk(dogs, 1)]
        vectors = await components.embedder.embed([chunk.content for chunk in chunks])
        await components.vectorstore.add(chunks, vectors)

        query_vector = (await components.embedder.embed(["cats"]))[0]
        results = await components.vectorstore.search(query_vector, top_k=config.top_k)
        reranked = await components.reranker.rerank("cats", results, top_k=1)

        assert len(vectors) == 2
        assert [result.content for result in results] == [cats, dogs]
        assert results[0].score > results[1].score
        assert [result.content for result in reranked] == [cats]
        # Credentials are read at call time and forwarded, never logged.
        assert set(fake.api_keys) == {FAKE_OPENAI_KEY}

    async def test_built_components_respect_metadata_filtering(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeLiteLLM(dimensions=4)
        _use_fake_litellm(monkeypatch, fake)
        monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI_KEY)
        components = build_rag_components(
            RAGConfig(embedding=EmbeddingConfig(dimensions=4))
        )
        chunk = _make_chunk("only document", 0)
        vectors = await components.embedder.embed([chunk.content])
        await components.vectorstore.add([chunk], vectors)

        matched = await components.vectorstore.search(
            vectors[0], top_k=5, metadata_filter={"source": "unit-test"}
        )
        unmatched = await components.vectorstore.search(
            vectors[0], top_k=5, metadata_filter={"source": "elsewhere"}
        )

        assert [result.chunk_id for result in matched] == ["chunk-0"]
        assert unmatched == []
