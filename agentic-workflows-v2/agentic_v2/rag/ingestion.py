"""Document ingestion pipeline — orchestrates load → chunk.

The :class:`IngestionPipeline` takes a loader and chunker and
provides a single ``ingest(source)`` method that produces chunks
ready for embedding and indexing.
"""

from __future__ import annotations

import logging

from .chunking import RecursiveChunker
from .config import ChunkingConfig
from .contracts import Chunk
from .errors import IngestionError
from .protocols import ChunkerProtocol, LoaderProtocol

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Orchestrate document loading and chunking.

    Usage::

        pipeline = IngestionPipeline(
            loader=MarkdownLoader(),
            chunker=RecursiveChunker(),
        )
        chunks = await pipeline.ingest("docs/README.md")
    """

    def __init__(
        self,
        loader: LoaderProtocol,
        chunker: ChunkerProtocol | None = None,
        chunking_config: ChunkingConfig | None = None,
    ) -> None:
        self._loader = loader
        self._chunker: ChunkerProtocol = chunker or RecursiveChunker()
        self._chunking_config = chunking_config

    async def ingest(self, source: str) -> list[Chunk]:
        """Load and chunk a source file.

        Args:
            source: Path or locator for the document.

        Returns:
            Ordered list of :class:`Chunk` objects.

        Raises:
            IngestionError: If loading or chunking fails.
        """
        logger.info("Ingesting source: %s", source)

        try:
            documents = await self._loader.load(source)
        except IngestionError:
            raise
        except Exception as exc:
            raise IngestionError(f"Loader failed for {source}: {exc}") from exc

        all_chunks: list[Chunk] = []
        for doc in documents:
            try:
                chunks = self._chunker.chunk(doc, self._chunking_config)
                all_chunks.extend(chunks)
                logger.debug(
                    "Chunked %s: %d chunks from document %s",
                    source,
                    len(chunks),
                    doc.document_id,
                )
            except Exception as exc:
                raise IngestionError(
                    f"Chunking failed for document {doc.document_id}: {exc}"
                ) from exc

        logger.info(
            "Ingestion complete: %s → %d documents → %d chunks",
            source,
            len(documents),
            len(all_chunks),
        )
        return all_chunks
