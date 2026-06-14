"""Tier 0 file operation tools - No LLM required."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import aiofiles

from ...settings import get_settings as _get_settings
from ...utils.path_safety import ensure_within_base
from ..base import BaseTool, ToolResult

# Base directory for path validation.  When ``AGENTIC_FILE_BASE_DIR`` is set
# tools will reject any path that escapes it.  When unset, all file operations
# fail closed with a clear error directing the operator to configure the
# sandbox root.
_FILE_BASE_DIR: str | None = _get_settings().agentic_file_base_dir


def _validate_path(path: str) -> Path:
    """Resolve and validate that *path* is within the configured base directory.

    When ``AGENTIC_FILE_BASE_DIR`` is not set or empty, this function raises a
    ``ValueError`` so that every file tool fails closed. Operators must set the
    environment variable to a directory that agents are permitted to read and
    write.

    Raises:
        ValueError: If ``AGENTIC_FILE_BASE_DIR`` is unset/empty, or the path
            escapes the configured base directory.
    """
    if not _FILE_BASE_DIR:
        raise ValueError(
            "AGENTIC_FILE_BASE_DIR must be set to use file tools. "
            "Set it to the directory agents are allowed to read and write."
        )
    return ensure_within_base(path, _FILE_BASE_DIR)


class FileCopyTool(BaseTool):
    """Copy a file from source to destination."""

    @property
    def name(self) -> str:
        return "file_copy"

    @property
    def requires_approval(self) -> bool:
        # High-impact: creates/overwrites a destination file. Gated by default.
        return True

    @property
    def description(self) -> str:
        return (
            "Copy a single file from `source` to `destination`, LEAVING the "
            "source in place (this is the non-destructive duplicate). Both are "
            "filesystem paths; `destination` is created or overwritten. Edge "
            "cases: a missing source fails fast; paths are containment-checked, "
            "so escaping the workspace is rejected; directories are not "
            "supported (file-only). Requires approval (writes a new file). "
            "PREFER `file_copy` when the original must survive; use `file_move` "
            "instead to relocate/rename (which DELETES the source)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "source": {
                "type": "string",
                "description": "Source file path",
                "required": True,
            },
            "destination": {
                "type": "string",
                "description": "Destination file path",
                "required": True,
            },
            "overwrite": {
                "type": "boolean",
                "description": "Whether to overwrite if destination exists",
                "required": False,
                "default": False,
            },
        }

    async def execute(
        self, source: str, destination: str, overwrite: bool = False
    ) -> ToolResult:
        """Execute file copy."""
        try:
            try:
                _validate_path(source)
                _validate_path(destination)
            except ValueError as e:
                return ToolResult(success=False, error=str(e))

            src_path = Path(source)
            dst_path = Path(destination)

            if not src_path.exists():
                return ToolResult(
                    success=False, error=f"Source file does not exist: {source}"
                )

            if dst_path.exists() and not overwrite:
                return ToolResult(
                    success=False,
                    error=f"Destination file already exists: {destination}",
                )

            # Create parent directories if needed
            dst_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy file
            shutil.copy2(str(src_path), str(dst_path))

            return ToolResult(
                success=True,
                data={"source": source, "destination": destination},
                metadata={"bytes_copied": dst_path.stat().st_size},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to copy file: {e!s}")


class FileMoveTool(BaseTool):
    """Move or rename a file."""

    @property
    def name(self) -> str:
        return "file_move"

    @property
    def requires_approval(self) -> bool:
        # High-impact: moves/renames (removes the source). Gated by default.
        return True

    @property
    def description(self) -> str:
        return (
            "Move or rename a file from `source` to `destination`, REMOVING the "
            "source (destructive — the original no longer exists afterward). "
            "Use the same path with a new filename to rename in place. Edge "
            "cases: a missing source fails fast; both paths are "
            "containment-checked; an existing destination is overwritten. "
            "Requires approval. PREFER `file_move` to relocate or rename; use "
            "`file_copy` instead when the original must be preserved."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "source": {
                "type": "string",
                "description": "Source file path",
                "required": True,
            },
            "destination": {
                "type": "string",
                "description": "Destination file path",
                "required": True,
            },
            "overwrite": {
                "type": "boolean",
                "description": "Whether to overwrite if destination exists",
                "required": False,
                "default": False,
            },
        }

    async def execute(
        self, source: str, destination: str, overwrite: bool = False
    ) -> ToolResult:
        """Execute file move."""
        try:
            try:
                _validate_path(source)
                _validate_path(destination)
            except ValueError as e:
                return ToolResult(success=False, error=str(e))

            src_path = Path(source)
            dst_path = Path(destination)

            if not src_path.exists():
                return ToolResult(
                    success=False, error=f"Source file does not exist: {source}"
                )

            if dst_path.exists() and not overwrite:
                return ToolResult(
                    success=False,
                    error=f"Destination file already exists: {destination}",
                )

            # Create parent directories if needed
            dst_path.parent.mkdir(parents=True, exist_ok=True)

            # Move file
            shutil.move(str(src_path), str(dst_path))

            return ToolResult(
                success=True, data={"source": source, "destination": destination}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to move file: {e!s}")


class FileDeleteTool(BaseTool):
    """Delete a file."""

    @property
    def name(self) -> str:
        return "file_delete"

    @property
    def requires_approval(self) -> bool:
        # High-impact: irreversible deletion. Gated by default.
        return True

    @property
    def description(self) -> str:
        return (
            "Permanently delete a single file at `path` (irreversible — there "
            "is no trash/undo). Set `missing_ok=True` to treat an absent file "
            "as success (returns deleted=False) instead of an error; with the "
            "default `missing_ok=False` a nonexistent path fails. The path is "
            "containment-checked; directories are not deleted (file-only). "
            "Requires approval. This removes a file outright — use `file_move` "
            "to relocate one without losing it."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "Path to the file to delete",
                "required": True,
            },
            "missing_ok": {
                "type": "boolean",
                "description": "If True, don't raise error if file doesn't exist",
                "required": False,
                "default": False,
            },
        }

    async def execute(self, path: str, missing_ok: bool = False) -> ToolResult:
        """Execute file deletion."""
        try:
            try:
                _validate_path(path)
            except ValueError as e:
                return ToolResult(success=False, error=str(e))

            file_path = Path(path)

            if not file_path.exists():
                if missing_ok:
                    return ToolResult(
                        success=True,
                        data={"path": path, "deleted": False},
                        metadata={"reason": "File did not exist"},
                    )
                return ToolResult(success=False, error=f"File does not exist: {path}")

            file_path.unlink()

            return ToolResult(success=True, data={"path": path, "deleted": True})
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to delete file: {e!s}")


class DirectoryCreateTool(BaseTool):
    """Create a directory (like mkdir -p)."""

    @property
    def name(self) -> str:
        return "directory_create"

    @property
    def requires_approval(self) -> bool:
        # High-impact: mutates the filesystem tree. Gated by default.
        return True

    @property
    def description(self) -> str:
        return (
            "Create a directory at `path`, creating any missing parent "
            "directories along the way (like `mkdir -p`). Idempotent: an "
            "already-existing directory is a no-op success, not an error. The "
            "path is containment-checked. Requires approval (mutates the "
            "filesystem tree). Creates empty folders only; to create a file "
            "use `file_write` (which already makes any missing parent dirs)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "Path to the directory to create",
                "required": True,
            },
            "exist_ok": {
                "type": "boolean",
                "description": "If True, don't raise error if directory exists",
                "required": False,
                "default": True,
            },
        }

    async def execute(self, path: str, exist_ok: bool = True) -> ToolResult:
        """Execute directory creation."""
        try:
            try:
                _validate_path(path)
            except ValueError as e:
                return ToolResult(success=False, error=str(e))

            dir_path = Path(path)
            dir_path.mkdir(parents=True, exist_ok=exist_ok)

            return ToolResult(success=True, data={"path": path, "created": True})
        except FileExistsError:
            return ToolResult(success=False, error=f"Directory already exists: {path}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to create directory: {e!s}")


class FileReadTool(BaseTool):
    """Read file contents."""

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def description(self) -> str:
        return (
            "Read the full text contents of one file at `path` into memory, "
            "returning the content plus size_bytes and line count. `encoding` "
            "defaults to utf-8. Read-only and ungated. Edge cases: a missing "
            "path fails fast; the path is containment-checked; the whole file "
            "is loaded (no range/streaming), so avoid very large files. This "
            "returns a file's CONTENT — use `grep`/`search` to find WHERE a "
            "string occurs across many files, or `file_write` to modify one."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "Path to the file to read",
                "required": True,
            },
            "encoding": {
                "type": "string",
                "description": "File encoding (default: utf-8)",
                "required": False,
                "default": "utf-8",
            },
        }

    async def execute(self, path: str, encoding: str = "utf-8") -> ToolResult:
        """Execute file read."""
        try:
            try:
                _validate_path(path)
            except ValueError as e:
                return ToolResult(success=False, error=str(e))

            file_path = Path(path)

            if not file_path.exists():
                return ToolResult(success=False, error=f"File does not exist: {path}")

            async with aiofiles.open(file_path, encoding=encoding) as f:
                content = await f.read()

            return ToolResult(
                success=True,
                data={"path": path, "content": content},
                metadata={
                    "size_bytes": file_path.stat().st_size,
                    "lines": content.count("\n") + 1,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read file: {e!s}")


class FileWriteTool(BaseTool):
    """Write content to a file."""

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def requires_approval(self) -> bool:
        # High-impact: writes/overwrites filesystem content. Gated by default.
        return True

    @property
    def description(self) -> str:
        return (
            "Write `content` to a file at `path`, creating any missing parent "
            "directories automatically. By default (`overwrite=True`) it "
            "replaces the whole file; set `overwrite=False` to refuse and fail "
            "if the file already exists (safe create-only). `encoding` defaults "
            "to utf-8. This is a FULL-content write, not an append or patch — "
            "to keep existing text, `file_read` it first and write the merged "
            "result. The path is containment-checked. Requires approval."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "Path to the file to write",
                "required": True,
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file",
                "required": True,
            },
            "encoding": {
                "type": "string",
                "description": "File encoding (default: utf-8)",
                "required": False,
                "default": "utf-8",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Whether to overwrite if file exists",
                "required": False,
                "default": True,
            },
        }

    async def execute(
        self, path: str, content: str, encoding: str = "utf-8", overwrite: bool = True
    ) -> ToolResult:
        """Execute file write."""
        try:
            try:
                _validate_path(path)
            except ValueError as e:
                return ToolResult(success=False, error=str(e))

            file_path = Path(path)

            if file_path.exists() and not overwrite:
                return ToolResult(success=False, error=f"File already exists: {path}")

            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            async with aiofiles.open(file_path, "w", encoding=encoding) as f:
                await f.write(content)

            return ToolResult(
                success=True,
                data={"path": path, "bytes_written": len(content.encode(encoding))},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to write file: {e!s}")
