"""RAG subcommand group for the agentic CLI.

Registers a ``rag`` Typer sub-application with two commands:

- ``agentic rag ingest --source <path>``  -- load, chunk, embed, and index
  documents from a file or directory.
- ``agentic rag search <query>``          -- hybrid-retrieve ranked results
  from the in-memory index populated by a prior ingest call.

The actual RAG pipeline logic lives in :mod:`.helpers` (``_rag_ingest_impl``
and ``_rag_search_impl``) so this module stays focused on Click/Typer
decoration and console output.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .helpers import _rag_ingest_impl as _default_rag_ingest_impl
from .helpers import _rag_search_impl as _default_rag_search_impl

console = Console()

rag_group = typer.Typer(
    name="rag",
    help="RAG (Retrieval-Augmented Generation) pipeline commands.",
    add_completion=False,
)


def _compat_impl(name: str, default: Callable) -> Callable:
    """Resolve legacy helper patches applied to ``agentic_v2.cli.main``."""
    main_module = sys.modules.get("agentic_v2.cli.main")
    if main_module is None:
        return default
    return getattr(main_module, name, default)


@rag_group.command("ingest")
def rag_ingest(
    source: Path = typer.Option(
        ...,
        "--source",
        "-s",
        help="Path to file or directory to ingest",
    ),
    collection: str = typer.Option(
        "default",
        "--collection",
        "-c",
        help="Collection name for organizing ingested documents",
    ),
) -> None:
    """Ingest documents into the RAG pipeline.

    Loads, chunks, embeds, and indexes the source file for later retrieval.

    Examples:
        agentic rag ingest --source ./docs/README.md
        agentic rag ingest --source ./docs --collection my_project
    """
    try:
        _rag_ingest_impl = _compat_impl(
            "_rag_ingest_impl", _default_rag_ingest_impl
        )
        chunk_count = _rag_ingest_impl(str(source))
        console.print(f"[green]Ingested {chunk_count} chunks[/green] from {source}")
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from e


@rag_group.command("search")
def rag_search(
    query: str = typer.Argument(
        ...,
        help="Search query string",
    ),
    top_k: int = typer.Option(
        5,
        "--top-k",
        "-k",
        help="Maximum number of results to return",
    ),
) -> None:
    """Search the RAG index for relevant content.

    Returns ranked results from the hybrid retriever (dense + BM25).

    Examples:
        agentic rag search "how does the DAG executor work?"
        agentic rag search "pipeline patterns" --top-k 3
    """
    _rag_search_impl = _compat_impl("_rag_search_impl", _default_rag_search_impl)
    results = _rag_search_impl(query, top_k)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search Results (top {top_k})")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Content")

    for idx, result in enumerate(results, 1):
        content_preview = result["content"]
        if len(content_preview) > 120:
            content_preview = content_preview[:117] + "..."
        table.add_row(
            str(idx),
            f"{result['score']:.3f}",
            content_preview,
        )

    console.print(table)
