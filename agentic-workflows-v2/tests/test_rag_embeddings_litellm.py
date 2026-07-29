"""Tests for LiteLLMEmbedder — real-provider embeddings through LiteLLM.

``litellm`` ships in the optional ``rag`` extra and **no CI job installs it**.
Every test here therefore drives the real embedder code with an injected fake,
via the module's lazy loader seam
(:func:`agentic_v2.rag.embeddings._load_litellm`) or a ``sys.modules`` entry,
instead of guarding with ``pytest.importorskip``.  A skip guard would leave
this code unproven in CI while the suite stayed green — which is exactly the
failure mode ``tests/test_vectorstore_lancedb.py`` demonstrates.

Nothing here depends on ``litellm`` being ambiently present or absent: both
directions are monkeypatched explicitly, so the file behaves identically on a
developer machine with the ``rag`` extra installed and on a CI runner without
it.  No network calls and no real credentials.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from agentic_v2.rag import embeddings as embeddings_module
from agentic_v2.rag.config import EmbeddingConfig
from agentic_v2.rag.embeddings import (
    LITELLM_PROVIDER_KEY_ENV,
    LITELLM_PROVIDER_PREFIXES,
    EmbeddingProviderIdentity,
    FallbackEmbedder,
    LiteLLMEmbedder,
    litellm_model_string,
)
from agentic_v2.rag.errors import EmbeddingError
from agentic_v2.rag.protocols import EmbeddingProtocol

# Small vectors keep the fakes cheap; the production default is 1536.
_DIMENSIONS = 4

# Obviously-fake credentials. Never a real key, never written anywhere.
_FAKE_VOYAGE_KEY = "voyage-fake-key-not-real"
_FAKE_OPENAI_KEY = "openai-fake-key-not-real"


# ── Helpers ─────────────────────────────────────────────────────────


def _config(**overrides: Any) -> EmbeddingConfig:
    """Build an EmbeddingConfig with small, test-friendly defaults."""
    defaults: dict[str, Any] = {
        "provider": "local",
        "model_name": "nomic-embed-text",
        "dimensions": _DIMENSIONS,
        "batch_size": 2,
        "max_concurrent": 5,
    }
    return EmbeddingConfig(**{**defaults, **overrides})


def _vector_for(text: str, dimensions: int = _DIMENSIONS) -> list[float]:
    """Return a deterministic vector encoding *text*'s index.

    Texts are named ``"text-<n>"``, so the vector value identifies which input
    produced it.  That is what makes input-order assertions meaningful.
    """
    index = float(text.rsplit("-", 1)[1])
    return [index] * dimensions


def _object_response(
    texts: list[str], dimensions: int = _DIMENSIONS
) -> SimpleNamespace:
    """Build an attribute-style LiteLLM embedding response for *texts*."""
    return SimpleNamespace(
        data=[
            SimpleNamespace(embedding=_vector_for(text, dimensions)) for text in texts
        ]
    )


def _mapping_response(
    texts: list[str], dimensions: int = _DIMENSIONS
) -> dict[str, Any]:
    """Build a mapping-style LiteLLM embedding response for *texts*."""
    return {"data": [{"embedding": _vector_for(text, dimensions)} for text in texts]}


def _install_litellm(monkeypatch: pytest.MonkeyPatch, module: Any) -> Any:
    """Replace the lazy ``litellm`` loader with one returning *module*.

    This is the documented seam that lets the whole embed path run where
    ``litellm`` is genuinely not installed.
    """
    monkeypatch.setattr(embeddings_module, "_load_litellm", lambda: module)
    return module


def _block_litellm_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import litellm`` raise ImportError even when it is installed."""
    monkeypatch.setitem(sys.modules, "litellm", None)


def _exploding_loader() -> Any:
    """Loader that fails if called — proves a path never reaches litellm."""
    raise RuntimeError("litellm must not be loaded when there is nothing to embed")


class _RecordingLiteLLM:
    """Fake ``litellm`` module exposing only the async ``aembedding`` entrypoint."""

    def __init__(self, *, dimensions: int = _DIMENSIONS) -> None:
        self.calls: list[dict[str, Any]] = []
        self._dimensions = dimensions

    async def aembedding(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        return _object_response(kwargs["input"], self._dimensions)

    @property
    def batches(self) -> list[list[str]]:
        """The ``input`` batch of each call, in call order."""
        return [call["input"] for call in self.calls]


class _SyncOnlyLiteLLM:
    """Fake ``litellm`` exposing only the synchronous ``embedding`` entrypoint."""

    def __init__(self, *, dimensions: int = _DIMENSIONS) -> None:
        self.calls: list[dict[str, Any]] = []
        self.call_threads: list[int] = []
        self._dimensions = dimensions

    def embedding(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        self.call_threads.append(threading.get_ident())
        return _object_response(kwargs["input"], self._dimensions)


class _ConcurrencyProbeLiteLLM:
    """Fake ``litellm`` recording the peak number of in-flight requests."""

    def __init__(self, *, delay: float = 0.02) -> None:
        self.calls: list[dict[str, Any]] = []
        self.peak_in_flight = 0
        self._in_flight = 0
        self._delay = delay

    async def aembedding(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            await asyncio.sleep(self._delay)
            return _object_response(kwargs["input"])
        finally:
            self._in_flight -= 1


class _OutOfOrderLiteLLM:
    """Fake ``litellm`` whose earlier batches deliberately finish last."""

    def __init__(self) -> None:
        self.completion_order: list[str] = []

    async def aembedding(self, **kwargs: Any) -> SimpleNamespace:
        texts: list[str] = kwargs["input"]
        first_index = int(texts[0].rsplit("-", 1)[1])
        # Earlier batches sleep longer, so completion order reverses request
        # order and any reliance on completion order would show up as scrambled
        # output.
        await asyncio.sleep(0.05 - first_index * 0.01)
        self.completion_order.append(texts[0])
        return _object_response(texts)


# ── Provider routing ────────────────────────────────────────────────


class TestLiteLLMModelRouting:
    """Verify provider → LiteLLM model-string routing."""

    @pytest.mark.parametrize(
        ("provider", "model_name", "expected"),
        [
            ("voyage", "voyage-3", "voyage/voyage-3"),
            ("openai", "text-embedding-3-small", "openai/text-embedding-3-small"),
            ("local", "nomic-embed-text", "ollama/nomic-embed-text"),
            ("litellm", "azure/my-deployment", "azure/my-deployment"),
        ],
    )
    def test_routes_each_provider_to_its_model_string(
        self, provider: str, model_name: str, expected: str
    ) -> None:
        """Each configurable provider maps onto its documented LiteLLM prefix."""
        assert litellm_model_string(provider, model_name) == expected

    @pytest.mark.parametrize(
        ("provider", "model_name", "expected"),
        [
            ("voyage", "voyage-3", "voyage/voyage-3"),
            ("openai", "text-embedding-3-small", "openai/text-embedding-3-small"),
            ("local", "nomic-embed-text", "ollama/nomic-embed-text"),
            ("litellm", "azure/my-deployment", "azure/my-deployment"),
        ],
    )
    def test_embedder_exposes_the_routed_model_string(
        self, provider: str, model_name: str, expected: str
    ) -> None:
        """The constructed embedder reports the model string it will request."""
        embedder = LiteLLMEmbedder(_config(provider=provider, model_name=model_name))

        assert embedder.litellm_model == expected
        assert embedder.provider == provider
        assert embedder.model_name == model_name

    def test_unsupported_provider_raises_embedding_error(self) -> None:
        """An unroutable provider fails loudly and lists the supported set."""
        with pytest.raises(EmbeddingError, match="Unsupported LiteLLM embedding") as e:
            litellm_model_string("cohere", "embed-english-v3")

        message = str(e.value)
        assert "cohere" in message
        for supported in ("voyage", "openai", "local", "litellm"):
            assert supported in message

    def test_constructor_rejects_an_unroutable_provider(self) -> None:
        """Routing is validated at construction, not deferred to embed time.

        ``EmbeddingConfig.provider`` is a ``Literal`` so normal validation
        already blocks this; ``model_construct`` bypasses validation the way a
        caller building configs by hand could, and the embedder must still
        refuse rather than build a bogus model string.
        """
        config = EmbeddingConfig.model_construct(provider="cohere")

        with pytest.raises(EmbeddingError, match="Unsupported LiteLLM embedding"):
            LiteLLMEmbedder(config)

    def test_routing_tables_cover_every_configurable_provider(self) -> None:
        """Adding a provider to EmbeddingConfig must not silently lose routing."""
        configurable = set(
            get_args(EmbeddingConfig.model_fields["provider"].annotation)
        )

        assert configurable == set(LITELLM_PROVIDER_PREFIXES)
        assert configurable == set(LITELLM_PROVIDER_KEY_ENV)

    def test_exposes_identity_for_semantic_space_checks(self) -> None:
        """Identity is what lets FallbackEmbedder detect a semantic-space swap."""
        embedder = LiteLLMEmbedder(_config(provider="voyage", model_name="voyage-3"))

        assert embedder.embedding_identity == EmbeddingProviderIdentity(
            provider="voyage", model_name="voyage-3"
        )
        assert embedder.dimensions == _DIMENSIONS


# ── Happy path ──────────────────────────────────────────────────────


class TestLiteLLMEmbed:
    """Verify the embed path against a fake async ``aembedding``."""

    async def test_returns_one_vector_per_text_in_input_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Vectors come back in input order, not completion order."""
        probe = _install_litellm(monkeypatch, _OutOfOrderLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=2))
        texts = [f"text-{i}" for i in range(6)]

        vectors = await embedder.embed(texts)

        assert vectors == [_vector_for(text) for text in texts]
        # The fake finished the batches backwards; input order still held.
        assert probe.completion_order == ["text-4", "text-2", "text-0"]

    async def test_accepts_a_mapping_style_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LiteLLM's response type has varied; dict-shaped payloads still parse."""

        class _MappingLiteLLM:
            async def aembedding(self, **kwargs: Any) -> dict[str, Any]:
                return _mapping_response(kwargs["input"])

        _install_litellm(monkeypatch, _MappingLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        vectors = await embedder.embed(["text-0", "text-1"])

        assert vectors == [_vector_for("text-0"), _vector_for("text-1")]

    async def test_empty_input_returns_empty_without_touching_litellm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing to embed means no import, no credential read, no request."""
        monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
        monkeypatch.setattr(embeddings_module, "_load_litellm", _exploding_loader)
        embedder = LiteLLMEmbedder(_config(provider="voyage", model_name="voyage-3"))

        assert await embedder.embed([]) == []

    async def test_satisfies_embedding_protocol(self) -> None:
        """LiteLLMEmbedder must be usable anywhere EmbeddingProtocol is required."""
        embedder = LiteLLMEmbedder(_config())

        assert isinstance(embedder, EmbeddingProtocol)


# ── Batching and concurrency ────────────────────────────────────────


class TestLiteLLMBatching:
    """Verify batch splitting and the in-flight concurrency bound."""

    async def test_splits_texts_into_configured_batch_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """batch_size controls both the number of calls and their contents."""
        fake = _install_litellm(monkeypatch, _RecordingLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=2))

        vectors = await embedder.embed([f"text-{i}" for i in range(5)])

        assert len(fake.calls) == 3
        assert sorted(fake.batches) == [
            ["text-0", "text-1"],
            ["text-2", "text-3"],
            ["text-4"],
        ]
        assert len(vectors) == 5

    async def test_sends_a_single_request_when_texts_fit_one_batch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No needless fan-out when the input fits inside one batch."""
        fake = _install_litellm(monkeypatch, _RecordingLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        await embedder.embed(["text-0", "text-1", "text-2"])

        assert fake.batches == [["text-0", "text-1", "text-2"]]

    async def test_every_request_carries_the_routed_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each batch is dispatched against the same resolved model string."""
        fake = _install_litellm(monkeypatch, _RecordingLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=1))

        await embedder.embed(["text-0", "text-1"])

        assert [call["model"] for call in fake.calls] == [
            "ollama/nomic-embed-text",
            "ollama/nomic-embed-text",
        ]

    async def test_max_concurrent_bounds_in_flight_requests(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """At most max_concurrent batches may be in flight at once."""
        probe = _install_litellm(monkeypatch, _ConcurrencyProbeLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=1, max_concurrent=2))

        await embedder.embed([f"text-{i}" for i in range(6)])

        assert len(probe.calls) == 6
        # Reaching the bound proves batches really do overlap...
        assert probe.peak_in_flight == 2

    async def test_max_concurrent_of_one_serializes_requests(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bound of one means no two requests are ever in flight together."""
        probe = _install_litellm(monkeypatch, _ConcurrencyProbeLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=1, max_concurrent=1))

        vectors = await embedder.embed(["text-0", "text-1", "text-2"])

        assert len(probe.calls) == 3
        assert probe.peak_in_flight == 1
        assert vectors == [_vector_for(f"text-{i}") for i in range(3)]


# ── Synchronous entrypoint fallback ─────────────────────────────────


class TestLiteLLMSyncEntrypoint:
    """Verify the offload path used when litellm exposes no async entrypoint."""

    async def test_uses_sync_embedding_when_aembedding_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An older litellm exposing only ``embedding`` still works."""
        fake = _install_litellm(monkeypatch, _SyncOnlyLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        vectors = await embedder.embed(["text-0", "text-1"])

        assert vectors == [_vector_for("text-0"), _vector_for("text-1")]
        assert len(fake.calls) == 1

    async def test_sync_entrypoint_runs_off_the_event_loop_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The blocking call is offloaded to an executor thread."""
        fake = _install_litellm(monkeypatch, _SyncOnlyLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        await embedder.embed(["text-0"])

        assert fake.call_threads == [fake.call_threads[0]]
        assert fake.call_threads[0] != threading.get_ident()

    async def test_sync_entrypoint_does_not_block_the_event_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The loop keeps running callbacks while the sync provider blocks.

        The worker signals the loop with ``call_soon_threadsafe`` and then
        blocks.  A loop that had been blocked by a synchronous provider call
        could never run that callback, so the release would never arrive and
        the worker's bounded wait would fail the test.
        """
        loop = asyncio.get_running_loop()
        worker_started = asyncio.Event()
        release = threading.Event()

        class _BlockingLiteLLM:
            def embedding(self, **kwargs: Any) -> SimpleNamespace:
                loop.call_soon_threadsafe(worker_started.set)
                if not release.wait(timeout=5.0):
                    raise TimeoutError("event loop was blocked by the sync call")
                return _object_response(kwargs["input"])

        _install_litellm(monkeypatch, _BlockingLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        async def _release_once_the_worker_is_blocked() -> None:
            await asyncio.wait_for(worker_started.wait(), timeout=5.0)
            release.set()

        vectors, _ = await asyncio.gather(
            embedder.embed(["text-0"]),
            _release_once_the_worker_is_blocked(),
        )

        assert vectors == [_vector_for("text-0")]

    async def test_missing_both_entrypoints_raises_embedding_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A litellm with neither entrypoint is reported, not called as None."""
        _install_litellm(monkeypatch, SimpleNamespace())
        embedder = LiteLLMEmbedder(_config())

        with pytest.raises(EmbeddingError, match="neither 'aembedding' nor"):
            await embedder.embed(["text-0"])


# ── Response validation ─────────────────────────────────────────────


class TestLiteLLMResponseValidation:
    """Verify malformed and wrong-shaped provider responses fail loudly."""

    @staticmethod
    def _responder(payload: Any) -> Any:
        """Build a fake litellm returning *payload* for every request."""

        class _FixedLiteLLM:
            async def aembedding(self, **kwargs: Any) -> Any:
                return payload

        return _FixedLiteLLM()

    async def test_dimension_mismatch_names_expected_and_actual(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A width mismatch must fail rather than corrupt the index."""
        payload = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * 8)])
        _install_litellm(monkeypatch, self._responder(payload))
        embedder = LiteLLMEmbedder(_config(dimensions=4, batch_size=10))

        with pytest.raises(EmbeddingError) as excinfo:
            await embedder.embed(["text-0"])

        message = str(excinfo.value)
        assert "8-dimensional" in message
        assert "4 dimensions are configured" in message
        assert "ollama/nomic-embed-text" in message

    async def test_wrong_number_of_vectors_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A provider returning the wrong vector count is a hard error."""
        payload = SimpleNamespace(
            data=[
                SimpleNamespace(embedding=[0.1] * _DIMENSIONS),
                SimpleNamespace(embedding=[0.2] * _DIMENSIONS),
            ]
        )
        _install_litellm(monkeypatch, self._responder(payload))
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        with pytest.raises(EmbeddingError) as excinfo:
            await embedder.embed(["text-0"])

        message = str(excinfo.value)
        assert "returned 2 embeddings" in message
        assert "1 input texts" in message

    @pytest.mark.parametrize(
        "payload",
        [
            SimpleNamespace(),
            {"model": "ollama/nomic-embed-text"},
            SimpleNamespace(data=None),
            SimpleNamespace(data={"embedding": [0.1] * _DIMENSIONS}),
        ],
        ids=["no-data-attr", "mapping-without-data", "data-none", "data-not-a-list"],
    )
    async def test_response_without_a_usable_data_list_raises(
        self, monkeypatch: pytest.MonkeyPatch, payload: Any
    ) -> None:
        """Any response lacking a ``data`` sequence is rejected."""
        _install_litellm(monkeypatch, self._responder(payload))
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        with pytest.raises(EmbeddingError, match="no usable 'data' list"):
            await embedder.embed(["text-0"])

    @pytest.mark.parametrize(
        "item",
        [SimpleNamespace(), {"index": 0}, SimpleNamespace(embedding=None)],
        ids=["no-embedding-attr", "mapping-without-embedding", "embedding-none"],
    )
    async def test_response_item_without_a_vector_raises(
        self, monkeypatch: pytest.MonkeyPatch, item: Any
    ) -> None:
        """A data element carrying no ``embedding`` list is rejected."""
        _install_litellm(monkeypatch, self._responder(SimpleNamespace(data=[item])))
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        with pytest.raises(EmbeddingError, match="no usable 'embedding' list"):
            await embedder.embed(["text-0"])

    async def test_non_numeric_vector_value_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A vector of non-numbers is rejected and chained to the parse error."""
        payload = SimpleNamespace(
            data=[SimpleNamespace(embedding=["nan-ish", "b", "c", "d"])]
        )
        _install_litellm(monkeypatch, self._responder(payload))
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        with pytest.raises(EmbeddingError, match="non-numeric vector value") as excinfo:
            await embedder.embed(["text-0"])

        assert isinstance(excinfo.value.__cause__, (TypeError, ValueError))


# ── Failure modes ───────────────────────────────────────────────────


class TestLiteLLMLazyImport:
    """Verify the real lazy loader — the seam every other test replaces.

    These tests drive ``_load_litellm`` itself rather than a patched
    substitute, in both directions, so the genuine ``import litellm``
    statement is exercised on a CI runner that lacks the ``rag`` extra.
    """

    def test_loader_returns_the_imported_module(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The loader hands back whatever ``import litellm`` resolves to."""
        stand_in = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "litellm", stand_in)

        assert embeddings_module._load_litellm() is stand_in

    async def test_embed_reaches_litellm_through_the_real_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The full embed path resolves litellm by import, not by test seam.

        Nothing here patches ``_load_litellm``; the fake is reached through the
        module's own lazy import statement.
        """
        fake = _RecordingLiteLLM()
        monkeypatch.setitem(sys.modules, "litellm", fake)
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        vectors = await embedder.embed(["text-0", "text-1"])

        assert vectors == [_vector_for("text-0"), _vector_for("text-1")]
        assert fake.batches == [["text-0", "text-1"]]

    def test_missing_litellm_reports_the_rag_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The loader turns a missing dependency into an actionable error."""
        _block_litellm_import(monkeypatch)

        with pytest.raises(EmbeddingError) as excinfo:
            embeddings_module._load_litellm()

        assert 'pip install -e ".[rag]"' in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, ImportError)

    async def test_missing_litellm_surfaces_through_embed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The install hint reaches the caller through the real embed path."""
        _block_litellm_import(monkeypatch)
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        with pytest.raises(EmbeddingError) as excinfo:
            await embedder.embed(["text-0"])

        assert 'pip install -e ".[rag]"' in str(excinfo.value)


class TestLiteLLMFailureModes:
    """Verify provider-error handling."""

    async def test_provider_exception_is_wrapped_and_chained(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An arbitrary provider failure becomes a chained EmbeddingError."""
        failure = RuntimeError("upstream returned 429")

        class _FailingLiteLLM:
            async def aembedding(self, **kwargs: Any) -> Any:
                raise failure

        _install_litellm(monkeypatch, _FailingLiteLLM())
        embedder = LiteLLMEmbedder(_config(batch_size=10))

        with pytest.raises(EmbeddingError, match="LiteLLM embedding call failed") as e:
            await embedder.embed(["text-0"])

        assert e.value.__cause__ is failure
        assert "ollama/nomic-embed-text" in str(e.value)
        assert "upstream returned 429" in str(e.value)


# ── Credentials ─────────────────────────────────────────────────────


class TestLiteLLMCredentials:
    """Verify credentials are read from the environment and never leaked."""

    async def test_voyage_key_is_read_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Voyage credential is forwarded from VOYAGE_API_KEY."""
        monkeypatch.setenv("VOYAGE_API_KEY", _FAKE_VOYAGE_KEY)
        fake = _install_litellm(monkeypatch, _RecordingLiteLLM())
        embedder = LiteLLMEmbedder(
            _config(provider="voyage", model_name="voyage-3", batch_size=10)
        )

        await embedder.embed(["text-0"])

        assert fake.calls[0]["api_key"] == _FAKE_VOYAGE_KEY
        assert fake.calls[0]["model"] == "voyage/voyage-3"

    async def test_openai_key_is_read_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The OpenAI credential is forwarded from OPENAI_API_KEY."""
        monkeypatch.setenv("OPENAI_API_KEY", _FAKE_OPENAI_KEY)
        fake = _install_litellm(monkeypatch, _RecordingLiteLLM())
        embedder = LiteLLMEmbedder(
            _config(
                provider="openai", model_name="text-embedding-3-small", batch_size=10
            )
        )

        await embedder.embed(["text-0"])

        assert fake.calls[0]["api_key"] == _FAKE_OPENAI_KEY

    @pytest.mark.parametrize(
        ("provider", "model_name"),
        [("local", "nomic-embed-text"), ("litellm", "azure/my-deployment")],
    )
    async def test_credential_free_providers_forward_no_api_key(
        self, monkeypatch: pytest.MonkeyPatch, provider: str, model_name: str
    ) -> None:
        """Local and fully qualified models let LiteLLM resolve their own auth."""
        fake = _install_litellm(monkeypatch, _RecordingLiteLLM())
        embedder = LiteLLMEmbedder(
            _config(provider=provider, model_name=model_name, batch_size=10)
        )

        await embedder.embed(["text-0"])

        assert "api_key" not in fake.calls[0]

    async def test_missing_key_names_the_variable_not_the_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unset credential fails before any request, naming the env var."""
        monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
        fake = _install_litellm(monkeypatch, _RecordingLiteLLM())
        embedder = LiteLLMEmbedder(_config(provider="voyage", model_name="voyage-3"))

        with pytest.raises(EmbeddingError, match="VOYAGE_API_KEY is not set") as e:
            await embedder.embed(["text-0"])

        assert "voyage" in str(e.value)
        assert fake.calls == []

    async def test_empty_key_is_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty string is not a usable credential."""
        monkeypatch.setenv("VOYAGE_API_KEY", "")
        _install_litellm(monkeypatch, _RecordingLiteLLM())
        embedder = LiteLLMEmbedder(_config(provider="voyage", model_name="voyage-3"))

        with pytest.raises(EmbeddingError, match="VOYAGE_API_KEY is not set"):
            await embedder.embed(["text-0"])

    async def test_credential_is_read_at_call_time_not_construction_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rotating the env var takes effect without rebuilding the embedder."""
        monkeypatch.setenv("VOYAGE_API_KEY", _FAKE_VOYAGE_KEY)
        fake = _install_litellm(monkeypatch, _RecordingLiteLLM())
        embedder = LiteLLMEmbedder(
            _config(provider="voyage", model_name="voyage-3", batch_size=10)
        )

        await embedder.embed(["text-0"])
        monkeypatch.setenv("VOYAGE_API_KEY", "voyage-fake-rotated-key")
        await embedder.embed(["text-1"])

        assert [call["api_key"] for call in fake.calls] == [
            _FAKE_VOYAGE_KEY,
            "voyage-fake-rotated-key",
        ]

    async def test_key_is_scrubbed_from_error_message_and_logs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A provider echoing the credential back must not leak it onward."""
        monkeypatch.setenv("VOYAGE_API_KEY", _FAKE_VOYAGE_KEY)

        class _EchoingLiteLLM:
            async def aembedding(self, **kwargs: Any) -> Any:
                raise RuntimeError(f"401 unauthorized (api_key={kwargs['api_key']})")

        _install_litellm(monkeypatch, _EchoingLiteLLM())
        embedder = LiteLLMEmbedder(
            _config(provider="voyage", model_name="voyage-3", batch_size=10)
        )

        with caplog.at_level(logging.DEBUG, logger="agentic_v2.rag.embeddings"):
            with pytest.raises(EmbeddingError) as excinfo:
                await embedder.embed(["text-0"])

        message = str(excinfo.value)
        assert _FAKE_VOYAGE_KEY not in message
        assert "401 unauthorized" in message
        assert "***" in message
        assert _FAKE_VOYAGE_KEY not in caplog.text


# ── Composition with FallbackEmbedder ───────────────────────────────


class TestLiteLLMFallbackComposition:
    """Verify LiteLLMEmbedder composes inside FallbackEmbedder."""

    async def test_composes_with_an_identical_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two embedders sharing dimensions and identity form a valid chain."""
        _install_litellm(monkeypatch, _RecordingLiteLLM())
        config = _config(batch_size=10)
        chain = FallbackEmbedder(
            providers=[LiteLLMEmbedder(config), LiteLLMEmbedder(config)]
        )

        assert isinstance(chain, EmbeddingProtocol)
        assert chain.dimensions == _DIMENSIONS
        assert chain.embedding_identity == EmbeddingProviderIdentity(
            provider="local", model_name="nomic-embed-text"
        )
        assert await chain.embed(["text-0"]) == [_vector_for("text-0")]

    def test_rejects_mixed_identities_without_an_explicit_override(self) -> None:
        """Distinct providers are a semantic-space swap unless declared safe.

        The error names the identity mismatch rather than a missing identity,
        which is what proves LiteLLMEmbedder exposes its identity at all.
        """
        voyage = LiteLLMEmbedder(_config(provider="voyage", model_name="voyage-3"))
        openai = LiteLLMEmbedder(
            _config(provider="openai", model_name="text-embedding-3-small")
        )

        with pytest.raises(ValueError, match="must share provider/model identity"):
            FallbackEmbedder(providers=[voyage, openai])

    async def test_falls_back_from_a_failing_provider_to_a_working_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A provider outage routes the request to the next chain member."""
        monkeypatch.setenv("VOYAGE_API_KEY", _FAKE_VOYAGE_KEY)
        monkeypatch.setenv("OPENAI_API_KEY", _FAKE_OPENAI_KEY)

        class _VoyageDownLiteLLM:
            def __init__(self) -> None:
                self.models: list[str] = []

            async def aembedding(self, **kwargs: Any) -> SimpleNamespace:
                self.models.append(kwargs["model"])
                if kwargs["model"].startswith("voyage/"):
                    raise RuntimeError("voyage is unavailable")
                return _object_response(kwargs["input"])

        fake = _install_litellm(monkeypatch, _VoyageDownLiteLLM())
        chain = FallbackEmbedder(
            providers=[
                LiteLLMEmbedder(
                    _config(provider="voyage", model_name="voyage-3", batch_size=10)
                ),
                LiteLLMEmbedder(
                    _config(
                        provider="openai",
                        model_name="text-embedding-3-small",
                        batch_size=10,
                    )
                ),
            ],
            allow_mixed_provider_identities=True,
        )

        vectors = await chain.embed(["text-0"])

        assert vectors == [_vector_for("text-0")]
        assert fake.models == ["voyage/voyage-3", "openai/text-embedding-3-small"]

    async def test_falls_back_when_the_primary_credential_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing credential is an EmbeddingError, so the chain continues."""
        monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", _FAKE_OPENAI_KEY)
        fake = _install_litellm(monkeypatch, _RecordingLiteLLM())
        chain = FallbackEmbedder(
            providers=[
                LiteLLMEmbedder(
                    _config(provider="voyage", model_name="voyage-3", batch_size=10)
                ),
                LiteLLMEmbedder(
                    _config(
                        provider="openai",
                        model_name="text-embedding-3-small",
                        batch_size=10,
                    )
                ),
            ],
            allow_mixed_provider_identities=True,
        )

        vectors = await chain.embed(["text-0"])

        assert vectors == [_vector_for("text-0")]
        assert [call["model"] for call in fake.calls] == [
            "openai/text-embedding-3-small"
        ]

    async def test_fallback_warning_does_not_leak_the_credential(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """FallbackEmbedder logs the failure; the credential must not be in it."""
        monkeypatch.setenv("VOYAGE_API_KEY", _FAKE_VOYAGE_KEY)
        monkeypatch.setenv("OPENAI_API_KEY", _FAKE_OPENAI_KEY)

        class _EchoingLiteLLM:
            async def aembedding(self, **kwargs: Any) -> SimpleNamespace:
                if kwargs["model"].startswith("voyage/"):
                    raise RuntimeError(f"401 for key {kwargs['api_key']}")
                return _object_response(kwargs["input"])

        _install_litellm(monkeypatch, _EchoingLiteLLM())
        chain = FallbackEmbedder(
            providers=[
                LiteLLMEmbedder(
                    _config(provider="voyage", model_name="voyage-3", batch_size=10)
                ),
                LiteLLMEmbedder(
                    _config(
                        provider="openai",
                        model_name="text-embedding-3-small",
                        batch_size=10,
                    )
                ),
            ],
            allow_mixed_provider_identities=True,
        )

        with caplog.at_level(logging.WARNING, logger="agentic_v2.rag.embeddings"):
            vectors = await chain.embed(["text-0"])

        assert vectors == [_vector_for("text-0")]
        # Non-vacuous: the warning really was captured, and it is scrubbed.
        assert "Embedding provider failed" in caplog.text
        assert _FAKE_VOYAGE_KEY not in caplog.text
        assert "***" in caplog.text
