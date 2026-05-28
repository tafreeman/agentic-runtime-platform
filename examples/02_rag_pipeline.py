"""02 — RAG pipeline: ingest, embed, retrieve, and assemble context.

Demonstrates the full Retrieval-Augmented Generation pipeline using
only in-memory components (no API keys, no external services):

    1. Create a :class:`Document` with sample text.
    2. Chunk it with :class:`RecursiveChunker`.
    3. Embed chunks with :class:`InMemoryEmbedder` (deterministic hashing).
    4. Store embeddings in :class:`InMemoryVectorStore`.
    5. Build a :class:`HybridRetriever` (dense + BM25 with RRF fusion).
    6. Query the pipeline and assemble results with :class:`TokenBudgetAssembler`.

All components run in-memory with zero external dependencies.

Usage:
    python examples/02_rag_pipeline.py
"""

from __future__ import annotations

import asyncio
import logging
import sys

# ---- RAG imports from the agentic-workflows-v2 package -------------------
from agentic_v2.rag import (
    BM25Index,
    ChunkingConfig,
    Document,
    HybridRetriever,
    InMemoryEmbedder,
    InMemoryVectorStore,
    RecursiveChunker,
    TokenBudgetAssembler,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sample content — a mini knowledge base about Python design patterns
# ---------------------------------------------------------------------------
SAMPLE_DOCUMENT = """
# Python Design Patterns

## Singleton Pattern

The Singleton pattern ensures a class has only one instance and provides
a global point of access to it.  In Python, a common implementation uses
a module-level variable or the __new__ method.

## Observer Pattern

The Observer pattern defines a one-to-many dependency between objects so
that when one object changes state, all its dependents are notified and
updated automatically.  Python's built-in signals or event systems often
implement this pattern.

## Strategy Pattern

The Strategy pattern defines a family of algorithms, encapsulates each
one, and makes them interchangeable.  In Python, this is often implemented
using first-class functions or callable objects instead of class hierarchies.

## Factory Pattern

The Factory pattern provides an interface for creating objects in a
superclass, but allows subclasses to alter the type of objects that will
be created.  Python's dynamic typing and duck typing make factory patterns
particularly clean and simple.

## Adapter Pattern

The Adapter pattern converts the interface of a class into another
interface that clients expect.  It lets classes work together that
couldn't otherwise because of incompatible interfaces.
"""


async def main() -> None:
    """Run the full RAG pipeline end-to-end."""

    # 1. Create a document from raw text ------------------------------------
    doc = Document(
        source="design_patterns.md",
        content=SAMPLE_DOCUMENT,
        metadata={"topic": "python", "type": "tutorial"},
    )
    print(f"Created document: {doc.source} ({len(doc.content)} chars)")

    # 2. Chunk the document -------------------------------------------------
    chunker = RecursiveChunker()
    config = ChunkingConfig(chunk_size=256, chunk_overlap=32)
    chunks = chunker.chunk(doc, config)
    print(f"Chunked into {len(chunks)} chunks")
    for i, chunk in enumerate(chunks):
        preview = chunk.content[:60].replace("\n", " ").strip()
        print(f'  Chunk {i}: "{preview}..." ({len(chunk.content)} chars)')

    # 3. Embed chunks using the deterministic in-memory embedder ------------
    # InMemoryEmbedder uses SHA-256 hashing to produce consistent vectors.
    # No API keys needed.  Same input always yields the same vector.
    embedder = InMemoryEmbedder(dimensions=128)
    texts = [c.content for c in chunks]
    embeddings = await embedder.embed(texts)
    print(f"\nEmbedded {len(embeddings)} chunks (dim={embedder.dimensions})")

    # 4. Store in the in-memory vector store --------------------------------
    vectorstore = InMemoryVectorStore()
    await vectorstore.add(chunks, embeddings)
    print("Indexed chunks in InMemoryVectorStore")

    # 5. Build the hybrid retriever (dense + BM25 with RRF fusion) ----------
    retriever = HybridRetriever(
        embedder=embedder,
        vectorstore=vectorstore,
        rrf_k=60,  # Standard RRF constant
    )
    # The BM25 keyword index also needs the chunks
    retriever.index_chunks(chunks)

    # 6. Query the retriever ------------------------------------------------
    query = "How does the Strategy pattern work in Python?"
    print(f'\nQuery: "{query}"')

    results = await retriever.retrieve(query, top_k=3)
    print(f"Retrieved {len(results)} results via hybrid retrieval (dense + BM25):\n")

    for rank, result in enumerate(results, 1):
        preview = result.content[:80].replace("\n", " ").strip()
        print(f"  [{rank}] score={result.score:.4f}  chunk_id={result.chunk_id[:8]}...")
        print(f'      "{preview}..."')

    # 7. Assemble results within a token budget -----------------------------
    assembler = TokenBudgetAssembler(max_tokens=500)
    response = assembler.assemble(results, query=query)

    print("\n=== Assembled RAG Response ===")
    print(f"Query        : {response.query}")
    print(f"Total results: {response.total_results}")
    print(f"Tokens used  : {response.metadata.get('tokens_used', 'N/A')}")
    print(f"Framing      : {response.metadata.get('framing_enabled', False)}")

    for i, r in enumerate(response.results):
        print(f"\nResult {i + 1} (score={r.score:.4f}):")
        # Show first 120 chars of assembled content
        print(f"  {r.content[:120].strip()}...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
