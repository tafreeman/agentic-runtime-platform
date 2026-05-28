"""RAG context assembly — token-budget-aware result assembler.

Provides:
- :class:`TokenBudgetAssembler`: Greedily assembles retrieval results into a
  :class:`RAGResponse` within a configurable token budget.
- :func:`frame_content`: Wraps retrieved content in delimiter tags for
  prompt injection defense.

Security note:
    Retrieved documents may contain adversarial content designed to hijack
    LLM behavior ("Ignore all previous instructions...").  The delimiter
    framing wraps each chunk in ``<retrieved_context>`` tags, signaling to
    the LLM that the content is **untrusted user-provided data** and should
    not be interpreted as instructions.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from .contracts import RAGResponse, RetrievalResult

logger = logging.getLogger(__name__)

# Delimiter tags for prompt injection defense.  The LLM system prompt
# should instruct the model to treat content within these tags as
# untrusted retrieved data, never as instructions.
CONTEXT_DELIMITER_START = "<retrieved_context>"
CONTEXT_DELIMITER_END = "</retrieved_context>"
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def sanitize_content(content: str) -> str:
    """Normalize retrieved content before it reaches the model.

    The sanitization step deliberately avoids semantic rewriting. It
    removes control characters, neutralizes attempts to smuggle
    retrieval delimiters, and prefixes each line so instruction-like
    text is preserved as quoted data.
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _CONTROL_CHAR_PATTERN.sub(" ", normalized)
    normalized = normalized.replace(
        CONTEXT_DELIMITER_START,
        "[blocked-retrieved-context-start]",
    )
    normalized = normalized.replace(
        CONTEXT_DELIMITER_END,
        "[blocked-retrieved-context-end]",
    )

    quoted_lines = [f"| {line}" if line else "|" for line in normalized.split("\n")]
    return "\n".join(quoted_lines)


def sanitize_provenance_value(value: object | None) -> str:
    """Normalize provenance metadata so it cannot forge wrapper structure."""
    normalized = "" if value is None else str(value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _CONTROL_CHAR_PATTERN.sub(" ", normalized)
    normalized = normalized.replace(
        CONTEXT_DELIMITER_START,
        "[blocked-retrieved-context-start]",
    )
    normalized = normalized.replace(
        CONTEXT_DELIMITER_END,
        "[blocked-retrieved-context-end]",
    )
    return (
        " ".join(part for part in normalized.split("\n") if part).strip() or "unknown"
    )


def frame_content(
    content: str,
    *,
    document_id: str | None = None,
    chunk_id: str | None = None,
    score: float | None = None,
    metadata: dict[str, object] | None = None,
) -> str:
    """Wrap retrieved content in a provenance-aware untrusted-data envelope.

    Args:
        content: Raw retrieved chunk content.
        document_id: Source document identifier, when available.
        chunk_id: Source chunk identifier, when available.
        score: Retrieval relevance score, when available.
        metadata: Optional retrieval metadata used for provenance hints.

    Returns:
        Content wrapped in ``<retrieved_context>`` delimiters.
    """
    safe_content = sanitize_content(content)
    provenance_lines = [
        "trust_level: untrusted_retrieved_data",
        f"document_id: {sanitize_provenance_value(document_id)}",
        f"chunk_id: {sanitize_provenance_value(chunk_id)}",
    ]
    if score is not None:
        provenance_lines.append(f"retrieval_score: {score:.4f}")

    if metadata:
        source = metadata.get("source")
        if isinstance(source, str) and source.strip():
            provenance_lines.append(f"source: {sanitize_provenance_value(source)}")

    provenance_block = "\n".join(provenance_lines)
    return (
        f"{CONTEXT_DELIMITER_START}\n"
        "[retrieval_provenance]\n"
        f"{provenance_block}\n"
        "[/retrieval_provenance]\n"
        "[retrieved_data]\n"
        f"{safe_content}\n"
        "[/retrieved_data]\n"
        f"{CONTEXT_DELIMITER_END}"
    )


def _default_token_estimator(text: str) -> int:
    """Estimate token count as ``len(text) // 4``.

    This is the same heuristic used by ConversationMemory and is a
    reasonable approximation for English text across most tokenizers.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count.
    """
    return len(text) // 4


class TokenBudgetAssembler:
    """Assemble retrieval results into a RAGResponse within a token budget.

    Greedily adds results in descending score order until the token budget
    is exhausted.  Never exceeds ``max_tokens``.

    When ``frame_results`` is enabled (default), each result's content is
    wrapped in ``<retrieved_context>`` delimiters for prompt injection
    defense.  The token budget accounts for the framing overhead.

    Args:
        max_tokens: Maximum token budget for assembled context.
        token_estimator: Callable that estimates tokens for a given text.
            Defaults to ``len(text) // 4``.
        frame_results: Whether to wrap results in injection-defense
            delimiters.  Defaults to ``True``.
    """

    def __init__(
        self,
        *,
        max_tokens: int = 4000,
        token_estimator: Callable[[str], int] | None = None,
        frame_results: bool = True,
    ) -> None:
        self._max_tokens = max_tokens
        self._estimate_tokens = token_estimator or _default_token_estimator
        self._frame_results = frame_results

    def assemble(
        self,
        results: list[RetrievalResult],
        *,
        query: str | None = None,
    ) -> RAGResponse:
        """Assemble retrieval results into a RAGResponse within token budget.

        Results are sorted by score (descending) and greedily added until
        the budget is exhausted.

        Args:
            results: Retrieval results to assemble.
            query: Original query string (included in the response).

        Returns:
            A :class:`RAGResponse` with results that fit within the budget.
        """
        sorted_results = sorted(results, key=lambda r: r.score, reverse=True)

        assembled: list[RetrievalResult] = []
        tokens_used = 0

        for result in sorted_results:
            framed_content = (
                frame_content(
                    result.content,
                    document_id=result.document_id,
                    chunk_id=result.chunk_id,
                    score=result.score,
                    metadata=result.metadata,
                )
                if self._frame_results
                else result.content
            )
            result_tokens = self._estimate_tokens(framed_content)
            if tokens_used + result_tokens > self._max_tokens:
                logger.debug(
                    "Token budget exhausted at %d/%d tokens, "
                    "dropping remaining %d results",
                    tokens_used,
                    self._max_tokens,
                    len(sorted_results) - len(assembled),
                )
                break

            if self._frame_results:
                framed = RetrievalResult(
                    content=framed_content,
                    score=result.score,
                    document_id=result.document_id,
                    chunk_id=result.chunk_id,
                    metadata=dict(result.metadata),
                )
                assembled.append(framed)
            else:
                assembled.append(result)
            tokens_used += result_tokens

        return RAGResponse(
            query=query or "",
            results=assembled,
            total_results=len(assembled),
            metadata={
                "max_tokens": self._max_tokens,
                "tokens_used": tokens_used,
                "results_considered": len(results),
                "results_included": len(assembled),
                "framing_enabled": self._frame_results,
                "sanitization_enabled": self._frame_results,
            },
        )
