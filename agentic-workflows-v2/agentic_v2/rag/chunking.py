"""Document chunking — split documents into manageable chunks.

Implements :class:`ChunkerProtocol` via :class:`RecursiveChunker`,
which splits text on hierarchical separators (paragraph → line →
sentence → word → character).
"""

from __future__ import annotations

from .config import ChunkingConfig
from .contracts import Chunk, Document


class RecursiveChunker:
    """Split documents using recursive character text splitting.

    Tries each separator in order (``\\n\\n``, ``\\n``, ``. ``, `` ``, ``""``)
    and recursively splits oversized segments until all chunks fit within
    the configured ``chunk_size``.

    Satisfies :class:`~agentic_v2.rag.protocols.ChunkerProtocol`.
    """

    def chunk(
        self,
        document: Document,
        config: ChunkingConfig | None = None,
    ) -> list[Chunk]:
        """Split *document* into chunks.

        Args:
            document: Source document to split.
            config: Chunking configuration (uses defaults if omitted).

        Returns:
            Ordered list of :class:`Chunk` objects.
        """
        config = config or ChunkingConfig()
        text = document.content
        segments = self._recursive_split(
            text,
            config.separators,
            config.chunk_size,
            config.chunk_overlap,
        )

        chunks: list[Chunk] = []
        for idx, segment in enumerate(segments):
            chunk = Chunk(
                document_id=document.document_id,
                chunk_index=idx,
                content=segment,
                metadata={
                    "source": document.source,
                    **document.metadata,
                },
            )
            chunks.append(chunk)

        return chunks

    def _recursive_split(
        self,
        text: str,
        separators: list[str],
        chunk_size: int,
        overlap: int,
    ) -> list[str]:
        """Recursively split *text* using *separators* until all segments fit.

        Returns:
            List of text segments, each within *chunk_size* characters.
        """
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        # Try each separator in order of decreasing granularity
        for sep in separators:
            if sep and sep in text:
                parts = text.split(sep)
                break
        else:
            # No separator found — hard split by chunk_size
            return self._hard_split(text, chunk_size, overlap)

        # Merge small parts back into chunk-sized segments
        return self._merge_segments(parts, sep, chunk_size, overlap, separators)

    def _merge_segments(
        self,
        parts: list[str],
        separator: str,
        chunk_size: int,
        overlap: int,
        separators: list[str],
    ) -> list[str]:
        """Merge split parts into right-sized chunks with overlap."""
        results: list[str] = []
        current: list[str] = []
        current_len = 0

        for part in parts:
            part_len = len(part) + (len(separator) if current else 0)

            if current_len + part_len > chunk_size and current:
                segment = separator.join(current)
                if len(segment) > chunk_size:
                    # Segment still too large — recurse with finer separators
                    next_seps = (
                        separators[separators.index(separator) + 1 :]
                        if separator in separators
                        else [""]
                    )
                    results.extend(
                        self._recursive_split(segment, next_seps, chunk_size, overlap)
                    )
                else:
                    results.append(segment)

                # Overlap: keep last portion of current for context
                if overlap > 0 and current:
                    overlap_text = separator.join(current)
                    overlap_parts = []
                    olen = 0
                    for p in reversed(current):
                        olen += len(p) + len(separator)
                        if olen > overlap:
                            break
                        overlap_parts.insert(0, p)
                    current = overlap_parts
                    current_len = sum(len(p) for p in current) + len(separator) * max(
                        0, len(current) - 1
                    )
                else:
                    current = []
                    current_len = 0

            current.append(part)
            current_len += part_len

        if current:
            segment = separator.join(current)
            if segment.strip():
                results.append(segment)

        return [r for r in results if r.strip()]

    def _hard_split(self, text: str, chunk_size: int, overlap: int) -> list[str]:
        """Split text by character count as a last resort."""
        results: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            segment = text[start:end]
            if segment.strip():
                results.append(segment)
            start = end - overlap if overlap > 0 else end
            if start >= end:
                break
        return results
