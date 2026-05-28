"""Document loaders — read source files into Document objects.

Each loader satisfies :class:`~agentic_v2.rag.protocols.LoaderProtocol`
via structural subtyping.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiofiles

from ..utils.path_safety import ensure_within_base
from .contracts import Document
from .errors import IngestionError

logger = logging.getLogger(__name__)

# Default allowed base directory — current working directory.
# Override per-loader via the ``allowed_base_dir`` constructor arg.
_DEFAULT_BASE_DIR = Path(".")


class MarkdownLoader:
    """Load markdown (.md, .markdown) files as Documents.

    Satisfies :class:`~agentic_v2.rag.protocols.LoaderProtocol`.

    Args:
        allowed_base_dir: Base directory for path traversal protection.
            Defaults to the current working directory.
    """

    def __init__(self, allowed_base_dir: Path | None = None) -> None:
        self._base_dir = (allowed_base_dir or _DEFAULT_BASE_DIR).resolve()

    @property
    def supported_extensions(self) -> list[str]:
        """File extensions handled by this loader."""
        return [".md", ".markdown"]

    async def load(self, source: str, **kwargs: Any) -> list[Document]:
        """Load a markdown file and return it as a single Document.

        Args:
            source: Path to the markdown file.

        Returns:
            List containing one :class:`Document`.

        Raises:
            IngestionError: If the file cannot be read or is outside the
                allowed base directory.
        """
        try:
            path = ensure_within_base(source, self._base_dir)
        except ValueError as exc:
            raise IngestionError(str(exc)) from exc
        if not path.exists():
            raise IngestionError(f"File not found: {source}")
        if not path.is_file():
            raise IngestionError(f"Not a file: {source}")

        try:
            async with aiofiles.open(path, encoding="utf-8") as f:
                content = await f.read()
        except Exception as exc:
            raise IngestionError(f"Failed to read {source}: {exc}") from exc

        if not content.strip():
            logger.warning("Empty file: %s", source)
            return []

        doc = Document(
            source=str(path),
            content=content,
            metadata={
                "file_name": path.name,
                "file_extension": path.suffix,
            },
        )
        return [doc]


class TextLoader:
    """Load plain text (.txt) files as Documents.

    Satisfies :class:`~agentic_v2.rag.protocols.LoaderProtocol`.

    Args:
        allowed_base_dir: Base directory for path traversal protection.
            Defaults to the current working directory.
    """

    def __init__(self, allowed_base_dir: Path | None = None) -> None:
        self._base_dir = (allowed_base_dir or _DEFAULT_BASE_DIR).resolve()

    @property
    def supported_extensions(self) -> list[str]:
        """File extensions handled by this loader."""
        return [".txt"]

    async def load(self, source: str, **kwargs: Any) -> list[Document]:
        """Load a text file and return it as a single Document.

        Args:
            source: Path to the text file.

        Returns:
            List containing one :class:`Document`.

        Raises:
            IngestionError: If the file cannot be read or is outside the
                allowed base directory.
        """
        try:
            path = ensure_within_base(source, self._base_dir)
        except ValueError as exc:
            raise IngestionError(str(exc)) from exc
        if not path.exists():
            raise IngestionError(f"File not found: {source}")
        if not path.is_file():
            raise IngestionError(f"Not a file: {source}")

        try:
            async with aiofiles.open(path, encoding="utf-8") as f:
                content = await f.read()
        except Exception as exc:
            raise IngestionError(f"Failed to read {source}: {exc}") from exc

        if not content.strip():
            return []

        return [
            Document(
                source=str(path),
                content=content,
                metadata={
                    "file_name": path.name,
                    "file_extension": path.suffix,
                },
            )
        ]
