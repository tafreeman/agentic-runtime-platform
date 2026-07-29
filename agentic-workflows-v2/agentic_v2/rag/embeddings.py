"""RAG embedding providers — in-memory, LiteLLM, and fallback implementations.

Provides:
- :class:`InMemoryEmbedder`: Deterministic hash-based embedder for testing/dev.
- :class:`FallbackEmbedder`: Ordered fallback across multiple embedding providers.
- :class:`LiteLLMEmbedder`: Real provider embeddings (Voyage, OpenAI, local
  Ollama, or any fully qualified LiteLLM model) through LiteLLM's unified
  embedding API.  Requires the optional ``rag`` extra; the import is lazy so
  this module always imports without it.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import math
import os
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Sequence

from .errors import EmbeddingError
from .protocols import EmbeddingProtocol

if TYPE_CHECKING:
    from .config import EmbeddingConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingProviderIdentity:
    """Provider/model identity for an embedding semantic space."""

    provider: str
    model_name: str


def _embedding_identity(
    provider: EmbeddingProtocol,
) -> EmbeddingProviderIdentity | None:
    """Return explicit provider/model identity when the provider exposes it."""
    identity = getattr(provider, "embedding_identity", None)
    if isinstance(identity, EmbeddingProviderIdentity):
        return identity

    provider_name = getattr(provider, "provider", None)
    model_name = getattr(provider, "model_name", None)
    if provider_name is None or model_name is None:
        return None

    return EmbeddingProviderIdentity(
        provider=str(provider_name),
        model_name=str(model_name),
    )


def _provider_label(provider: EmbeddingProtocol) -> str:
    """Return a readable provider label for validation errors."""
    identity = _embedding_identity(provider)
    if identity is not None:
        return f"{identity.provider}/{identity.model_name}"
    return f"{type(provider).__module__}.{type(provider).__qualname__}"


def _validate_provider_dimensions(
    providers: tuple[EmbeddingProtocol, ...],
) -> int:
    """Ensure all providers share one positive vector dimensionality."""
    dimensions = tuple(provider.dimensions for provider in providers)
    for dimension in dimensions:
        if dimension <= 0:
            raise ValueError(f"provider dimensions must be positive, got {dimension}")

    expected = dimensions[0]
    if any(dimension != expected for dimension in dimensions):
        formatted = ", ".join(
            f"{_provider_label(provider)}={dimension}"
            for provider, dimension in zip(providers, dimensions, strict=True)
        )
        raise ValueError(
            "FallbackEmbedder providers must share the same dimensions; "
            f"got {formatted}"
        )
    return expected


def _validate_provider_identities(
    providers: tuple[EmbeddingProtocol, ...],
    *,
    allow_mixed_provider_identities: bool,
) -> tuple[EmbeddingProviderIdentity | None, ...]:
    """Ensure provider/model identities are pinned unless explicitly compatible."""
    identities = tuple(_embedding_identity(provider) for provider in providers)
    if len(providers) == 1 or allow_mixed_provider_identities:
        return identities

    missing = [
        _provider_label(provider)
        for provider, identity in zip(providers, identities, strict=True)
        if identity is None
    ]
    if missing:
        formatted = ", ".join(missing)
        raise ValueError(
            "FallbackEmbedder provider/model identity must be pinned; "
            f"missing provider/model identity for {formatted}. "
            "Expose provider and model_name, or set "
            "allow_mixed_provider_identities=True when explicitly compatible."
        )

    expected = identities[0]
    if any(identity != expected for identity in identities[1:]):
        formatted = ", ".join(
            f"{identity.provider}/{identity.model_name}"
            for identity in identities
            if identity is not None
        )
        raise ValueError(
            "FallbackEmbedder providers must share provider/model identity; "
            f"got {formatted}. Set allow_mixed_provider_identities=True "
            "when explicitly compatible."
        )

    return identities


def _fallback_identity(
    identities: tuple[EmbeddingProviderIdentity | None, ...],
    *,
    allow_mixed_provider_identities: bool,
) -> EmbeddingProviderIdentity:
    """Derive the identity exposed by a fallback chain."""
    first = identities[0]
    if first is not None and all(identity == first for identity in identities):
        return first

    model_name = (
        "explicitly-compatible" if allow_mixed_provider_identities else "unknown"
    )
    return EmbeddingProviderIdentity(provider="fallback", model_name=model_name)


class InMemoryEmbedder:
    """Deterministic hash-based embedder for testing and development.

    Generates embedding vectors by hashing input text with SHA-256, then
    expanding the hash bytes into a float vector of the requested
    dimensionality.  Same input always produces the same output, with
    no external API calls.

    Satisfies :class:`EmbeddingProtocol`.

    Args:
        dimensions: Number of dimensions for embedding vectors (default 384).
    """

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions <= 0:
            raise ValueError(f"dimensions must be positive, got {dimensions}")
        self._dimensions = dimensions

    @property
    def provider(self) -> str:
        """Provider identity for the deterministic local embedder."""
        return "local"

    @property
    def model_name(self) -> str:
        """Model identity for the deterministic local embedder."""
        return "in-memory-hash-v1"

    @property
    def embedding_identity(self) -> EmbeddingProviderIdentity:
        """Provider/model identity for this embedding semantic space."""
        return EmbeddingProviderIdentity(
            provider=self.provider,
            model_name=self.model_name,
        )

    @property
    def dimensions(self) -> int:
        """Dimensionality of the embedding vectors."""
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts using deterministic hashing.

        Args:
            texts: Strings to embed.

        Returns:
            List of embedding vectors (one per input text), each of
            length :attr:`dimensions` with values in [-1.0, 1.0].
        """
        return [self._hash_to_vector(text) for text in texts]

    def _hash_to_vector(self, text: str) -> list[float]:
        """Convert text to a deterministic float vector.

        Uses SHA-256 iteratively to produce enough bytes, then converts
        to floats in [-1.0, 1.0] and L2-normalizes.
        """
        vector: list[float] = []
        seed = text.encode("utf-8")

        # Generate enough floats by chaining hashes
        iteration = 0
        while len(vector) < self._dimensions:
            hash_input = seed + struct.pack(">I", iteration)
            digest = hashlib.sha256(hash_input).digest()
            # Each 4 bytes → one float via unsigned int → [-1, 1]
            for offset in range(0, len(digest), 4):
                if len(vector) >= self._dimensions:
                    break
                uint_val = struct.unpack(">I", digest[offset : offset + 4])[0]
                # Map [0, 2^32) to [-1.0, 1.0)
                float_val = (uint_val / (2**32)) * 2.0 - 1.0
                vector.append(float_val)
            iteration += 1

        # L2-normalize so vectors have unit length
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector


class FallbackEmbedder:
    """Ordered fallback across multiple embedding providers.

    Tries each provider in sequence.  On :class:`EmbeddingError` from
    one provider, falls back to the next.  Other exception types are treated
    as provider bugs and propagated without fallback.  If all providers fail,
    raises :class:`EmbeddingError` listing all collected errors.

    All providers must have identical dimensions.  Provider/model identity
    must also match unless ``allow_mixed_provider_identities`` explicitly
    marks the providers as compatible.

    Satisfies :class:`EmbeddingProtocol`.

    Args:
        providers: Ordered sequence of embedding providers to try.
        allow_mixed_provider_identities: Permit same-dimension providers with
            different provider/model identities when they are explicitly known
            to be compatible.

    Raises:
        ValueError: If *providers* is empty, dimensions differ, or identities
            differ without an explicit compatibility override.
    """

    def __init__(
        self,
        providers: Sequence[EmbeddingProtocol],
        *,
        allow_mixed_provider_identities: bool = False,
    ) -> None:
        if not providers:
            raise ValueError("FallbackEmbedder requires at least one provider")
        self._providers: tuple[EmbeddingProtocol, ...] = tuple(providers)
        self._dimensions = _validate_provider_dimensions(self._providers)
        self._identities = _validate_provider_identities(
            self._providers,
            allow_mixed_provider_identities=allow_mixed_provider_identities,
        )
        self._identity = _fallback_identity(
            self._identities,
            allow_mixed_provider_identities=allow_mixed_provider_identities,
        )

    @property
    def dimensions(self) -> int:
        """Shared dimensionality of the fallback provider chain."""
        return self._dimensions

    @property
    def provider(self) -> str:
        """Provider identity for this fallback chain."""
        return self._identity.provider

    @property
    def model_name(self) -> str:
        """Model identity for this fallback chain."""
        return self._identity.model_name

    @property
    def embedding_identity(self) -> EmbeddingProviderIdentity:
        """Provider/model identity for this fallback chain."""
        return self._identity

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the first available provider.

        Tries each provider in order.  Falls back on :class:`EmbeddingError`.

        Args:
            texts: Strings to embed.

        Returns:
            List of embedding vectors from the first successful provider.

        Raises:
            EmbeddingError: If all providers fail.
        """
        errors: list[EmbeddingError] = []

        for provider in self._providers:
            try:
                return await provider.embed(texts)
            except EmbeddingError as exc:
                logger.warning(
                    "Embedding provider failed, trying next: %s",
                    exc,
                )
                errors.append(exc)

        error_messages = "; ".join(str(e) for e in errors)
        raise EmbeddingError(
            f"All {len(errors)} embedding providers failed: {error_messages}"
        )


# ---------------------------------------------------------------------------
# LiteLLM-backed embeddings (optional ``rag`` extra)
# ---------------------------------------------------------------------------

# LiteLLM model-string prefix for each configured provider.  ``None`` means the
# configured ``model_name`` is already fully qualified and is passed through
# verbatim.
LITELLM_PROVIDER_PREFIXES: Final[Mapping[str, str | None]] = MappingProxyType(
    {
        "voyage": "voyage",
        "openai": "openai",
        "local": "ollama",
        "litellm": None,
    }
)

# Environment variable holding the credential for each provider.  ``None`` means
# no credential is read or forwarded by this module — a local Ollama endpoint
# needs none, and a fully qualified ``litellm`` model string lets LiteLLM
# resolve its own credentials from its own environment conventions.
LITELLM_PROVIDER_KEY_ENV: Final[Mapping[str, str | None]] = MappingProxyType(
    {
        "voyage": "VOYAGE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "local": None,
        "litellm": None,
    }
)


def litellm_model_string(provider: str, model_name: str) -> str:
    """Build the LiteLLM model string for a provider/model pair.

    Args:
        provider: Configured embedding provider name.
        model_name: Configured model identifier.

    Returns:
        The fully qualified LiteLLM model string (e.g. ``"voyage/voyage-3"``).

    Raises:
        EmbeddingError: If *provider* has no LiteLLM routing rule.
    """
    if provider not in LITELLM_PROVIDER_PREFIXES:
        supported = ", ".join(sorted(LITELLM_PROVIDER_PREFIXES))
        raise EmbeddingError(
            f"Unsupported LiteLLM embedding provider '{provider}'; "
            f"expected one of: {supported}"
        )

    prefix = LITELLM_PROVIDER_PREFIXES[provider]
    if prefix is None:
        return model_name
    return f"{prefix}/{model_name}"


def _load_litellm() -> Any:
    """Import the optional ``litellm`` dependency lazily.

    This is the seam tests replace.  Keeping the import inside a module-level
    function means importing :mod:`agentic_v2.rag.embeddings` never requires
    the ``rag`` extra, and a test can exercise the whole embed path with a
    fake module even where ``litellm`` is genuinely absent.

    Returns:
        The imported ``litellm`` module.

    Raises:
        EmbeddingError: If ``litellm`` is not installed.
    """
    try:
        import litellm
    except ImportError as exc:
        raise EmbeddingError(
            "litellm is required for LiteLLMEmbedder but is not installed; "
            'install the RAG extra with: pip install -e ".[rag]"'
        ) from exc
    return litellm


def _redact_secret(text: str, secret: str | None) -> str:
    """Replace *secret* with a placeholder wherever it appears in *text*.

    Provider errors can echo request material back to the caller.  Scrubbing
    the credential before it reaches a log record or an exception message
    keeps it out of both.

    Args:
        text: Message that may contain the credential.
        secret: The credential to scrub, if any.

    Returns:
        *text* with every occurrence of *secret* replaced by ``"***"``.
    """
    if not secret:
        return text
    return text.replace(secret, "***")


def _embedding_response_items(response: Any) -> list[Any]:
    """Extract the per-input items from a LiteLLM embedding response.

    Tolerates both an object exposing ``.data`` and a mapping carrying a
    ``"data"`` key, since LiteLLM's response type has varied across releases.

    Args:
        response: Raw value returned by LiteLLM.

    Returns:
        The list of per-input response items.

    Raises:
        EmbeddingError: If the response carries no usable ``data`` sequence.
    """
    data = getattr(response, "data", None)
    if data is None and isinstance(response, Mapping):
        data = response.get("data")

    if not isinstance(data, (list, tuple)):
        raise EmbeddingError(
            "LiteLLM embedding response has no usable 'data' list "
            f"(response type: {type(response).__name__})"
        )
    return list(data)


def _embedding_vector(item: Any) -> list[float]:
    """Extract one embedding vector from a LiteLLM response item.

    Args:
        item: A single element of the response ``data`` list.

    Returns:
        The embedding vector as a list of floats.

    Raises:
        EmbeddingError: If the item carries no numeric ``embedding`` list.
    """
    vector = getattr(item, "embedding", None)
    if vector is None and isinstance(item, Mapping):
        vector = item.get("embedding")

    if not isinstance(vector, (list, tuple)):
        raise EmbeddingError(
            "LiteLLM embedding response item has no usable 'embedding' list "
            f"(item type: {type(item).__name__})"
        )

    try:
        return [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise EmbeddingError(
            "LiteLLM embedding response contained a non-numeric vector value"
        ) from exc


def _parse_embedding_response(
    response: Any,
    *,
    expected_count: int,
    expected_dimensions: int,
    model: str,
) -> list[list[float]]:
    """Parse and validate a LiteLLM embedding response.

    Args:
        response: Raw value returned by LiteLLM.
        expected_count: Number of texts sent in this request.
        expected_dimensions: Configured vector dimensionality.
        model: LiteLLM model string, used in error messages.

    Returns:
        One vector per input text, in request order.

    Raises:
        EmbeddingError: If the payload is unparseable, returns the wrong
            number of vectors, or returns a vector of the wrong width.
    """
    vectors = [_embedding_vector(item) for item in _embedding_response_items(response)]

    if len(vectors) != expected_count:
        raise EmbeddingError(
            f"LiteLLM returned {len(vectors)} embeddings for {expected_count} "
            f"input texts (model '{model}')"
        )

    for vector in vectors:
        if len(vector) != expected_dimensions:
            raise EmbeddingError(
                f"LiteLLM returned a {len(vector)}-dimensional embedding but "
                f"{expected_dimensions} dimensions are configured (model "
                f"'{model}'); storing mismatched vectors would corrupt the index"
            )

    return vectors


class LiteLLMEmbedder:
    """Embedding provider backed by LiteLLM's unified embedding API.

    Routes :attr:`EmbeddingConfig.provider` onto a LiteLLM model string via
    :data:`LITELLM_PROVIDER_PREFIXES` (``voyage`` → ``voyage/…``, ``openai`` →
    ``openai/…``, ``local`` → ``ollama/…``, ``litellm`` → passed through), then
    embeds in batches of ``config.batch_size`` with at most
    ``config.max_concurrent`` requests in flight.  Results are returned in
    input order.

    The credential is read from the environment at call time (see
    :data:`LITELLM_PROVIDER_KEY_ENV`) and is never accepted as a constructor
    argument, logged, or included in an error message.

    Requires the optional ``litellm`` dependency (``pip install -e ".[rag]"``).
    The import is lazy, so constructing this class — and importing this module —
    works without the extra; only :meth:`embed` needs it.

    Satisfies :class:`EmbeddingProtocol`.

    Args:
        config: Embedding configuration supplying provider, model, dimensions,
            batch size, and concurrency limit.

    Raises:
        EmbeddingError: If ``config.provider`` has no LiteLLM routing rule.
    """

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._model_string = litellm_model_string(
            config.provider,
            config.model_name,
        )
        self._api_key_env = LITELLM_PROVIDER_KEY_ENV.get(config.provider)

    @property
    def provider(self) -> str:
        """Configured provider name."""
        return str(self._config.provider)

    @property
    def model_name(self) -> str:
        """Configured model identifier."""
        return self._config.model_name

    @property
    def litellm_model(self) -> str:
        """Fully qualified LiteLLM model string used for every request."""
        return self._model_string

    @property
    def embedding_identity(self) -> EmbeddingProviderIdentity:
        """Provider/model identity for this embedding semantic space."""
        return EmbeddingProviderIdentity(
            provider=self.provider,
            model_name=self.model_name,
        )

    @property
    def dimensions(self) -> int:
        """Configured dimensionality of the embedding vectors."""
        return self._config.dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* through LiteLLM, batched and concurrency-bounded.

        Args:
            texts: Strings to embed.  An empty list short-circuits with no
                network call.

        Returns:
            One vector per input text, in input order, each of length
            :attr:`dimensions`.

        Raises:
            EmbeddingError: If ``litellm`` is missing, a required credential
                env var is unset, the provider call fails, or the response is
                unparseable / the wrong shape.
        """
        if not texts:
            return []

        api_key = self._resolve_api_key()
        batch_size = self._config.batch_size
        batches = [
            texts[start : start + batch_size]
            for start in range(0, len(texts), batch_size)
        ]
        semaphore = asyncio.Semaphore(self._config.max_concurrent)

        batched_vectors = await asyncio.gather(
            *(self._embed_batch(batch, semaphore, api_key) for batch in batches)
        )
        return [vector for batch in batched_vectors for vector in batch]

    def _resolve_api_key(self) -> str | None:
        """Read the provider credential from the environment at call time.

        Returns:
            The credential, or ``None`` when the provider needs none.

        Raises:
            EmbeddingError: If the provider requires a credential and the
                environment variable is unset or empty.  The message names the
                variable, never its value.
        """
        if self._api_key_env is None:
            return None

        api_key = os.getenv(self._api_key_env)
        if not api_key:
            raise EmbeddingError(
                f"{self._api_key_env} is not set; it is required for embedding "
                f"provider '{self.provider}' (model '{self._model_string}')"
            )
        return api_key

    async def _embed_batch(
        self,
        batch: list[str],
        semaphore: asyncio.Semaphore,
        api_key: str | None,
    ) -> list[list[float]]:
        """Embed a single batch under the concurrency bound.

        Args:
            batch: Texts for this request.
            semaphore: Shared in-flight-request limiter.
            api_key: Credential to forward, or ``None``.

        Returns:
            One vector per text in *batch*, in order.

        Raises:
            EmbeddingError: If the call fails or the response is invalid.
        """
        async with semaphore:
            response = await self._call_litellm(batch, api_key)

        return _parse_embedding_response(
            response,
            expected_count=len(batch),
            expected_dimensions=self._config.dimensions,
            model=self._model_string,
        )

    async def _call_litellm(self, batch: list[str], api_key: str | None) -> Any:
        """Dispatch one embedding request, preferring the async entrypoint.

        Uses ``litellm.aembedding`` when the installed version exposes it;
        otherwise offloads the synchronous ``litellm.embedding`` to the default
        executor so the event loop is never blocked.

        Args:
            batch: Texts for this request.
            api_key: Credential to forward, or ``None``.

        Returns:
            The raw LiteLLM response.

        Raises:
            EmbeddingError: If ``litellm`` is missing, exposes no embedding
                entrypoint, or the call raises.  Provider messages are scrubbed
                of the credential before being surfaced.
        """
        litellm = _load_litellm()
        kwargs: dict[str, Any] = {
            "model": self._model_string,
            "input": list(batch),
        }
        if api_key is not None:
            kwargs["api_key"] = api_key

        entrypoint = getattr(litellm, "aembedding", None)
        is_async = entrypoint is not None
        if entrypoint is None:
            entrypoint = getattr(litellm, "embedding", None)
        if entrypoint is None:
            raise EmbeddingError(
                "The installed litellm exposes neither 'aembedding' nor "
                "'embedding'; upgrade litellm (>=1.84,<2) to use LiteLLMEmbedder"
            )

        try:
            if is_async:
                return await entrypoint(**kwargs)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                functools.partial(entrypoint, **kwargs),
            )
        except Exception as exc:
            detail = _redact_secret(str(exc), api_key)
            raise EmbeddingError(
                "LiteLLM embedding call failed for model "
                f"'{self._model_string}': {detail}"
            ) from exc
