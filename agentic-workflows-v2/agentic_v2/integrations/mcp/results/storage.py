"""
MCP Output Storage - disk-backed storage for oversized/binary outputs.

When MCP tools/resources return massive or binary payloads, persist them to
disk and return a file pointer + summary to the LLM.
"""

import base64
import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Storage directory (under workspace temp)
DEFAULT_OUTPUT_DIR = ".temp/mcp-outputs"


class McpOutputStorage:
    """
    Manages disk-backed storage for oversized MCP outputs.

    Features:
    - Safe path handling (no traversal attacks)
    - Binary data detection and persistence
    - File pointer generation
    - Automatic cleanup hints
    - Workspace-relative paths for portability
    """

    def __init__(
        self,
        output_dir: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        """
        Initialize output storage.

        Args:
            output_dir: Directory for output files (default: .temp/mcp-outputs)
            workspace_root: Workspace root for relative paths
        """
        self.workspace_root = workspace_root or os.getcwd()
        self.output_dir = output_dir or os.path.join(
            self.workspace_root, DEFAULT_OUTPUT_DIR
        )

        # Create output directory if it doesn't exist
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def save_text_output(
        self,
        content: str,
        server_name: str,
        tool_name: str,
        extension: str = "txt",
    ) -> tuple[str, str]:
        """
        Save text output to disk.

        Args:
            content: Text content to save
            server_name: Server that produced output
            tool_name: Tool that produced output
            extension: File extension (default: txt)

        Returns:
            Tuple of (file_path, workspace_relative_path)
        """
        # Generate safe filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        content_hash = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:8]
        filename = f"{server_name}_{tool_name}_{timestamp}_{content_hash}.{extension}"

        # Sanitize filename (remove path separators)
        filename = filename.replace("/", "_").replace("\\", "_")

        # Full path
        file_path = os.path.join(self.output_dir, filename)

        # Write content
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"Saved text output to {file_path} ({len(content)} chars)")
        except Exception as e:
            logger.error(f"Failed to save text output: {e}")
            raise

        # Get workspace-relative path (always starts with "./" for portability)
        relative_path = os.path.join(".", os.path.relpath(file_path, self.workspace_root))

        return file_path, relative_path

    def save_binary_output(
        self,
        data: bytes,
        server_name: str,
        tool_name: str,
        mime_type: str | None = None,
    ) -> tuple[str, str]:
        """
        Save binary output to disk.

        Args:
            data: Binary data
            server_name: Server that produced output
            tool_name: Tool that produced output
            mime_type: MIME type hint (used to determine extension)

        Returns:
            Tuple of (file_path, workspace_relative_path)
        """
        # Determine extension from MIME type
        extension = self._mime_to_extension(mime_type) if mime_type else "bin"

        # Generate safe filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_hash = hashlib.md5(data, usedforsecurity=False).hexdigest()[:8]
        filename = f"{server_name}_{tool_name}_{timestamp}_{data_hash}.{extension}"

        # Sanitize filename
        filename = filename.replace("/", "_").replace("\\", "_")

        # Full path
        file_path = os.path.join(self.output_dir, filename)

        # Write binary data
        try:
            with open(file_path, "wb") as f:
                f.write(data)

            logger.info(f"Saved binary output to {file_path} ({len(data)} bytes)")
        except Exception as e:
            logger.error(f"Failed to save binary output: {e}")
            raise

        # Get workspace-relative path (always starts with "./" for portability)
        relative_path = os.path.join(".", os.path.relpath(file_path, self.workspace_root))

        return file_path, relative_path

    def save_base64_output(
        self,
        base64_data: str,
        server_name: str,
        tool_name: str,
        mime_type: str | None = None,
    ) -> tuple[str, str]:
        """
        Save base64-encoded output to disk.

        Args:
            base64_data: Base64-encoded string
            server_name: Server name
            tool_name: Tool name
            mime_type: MIME type hint

        Returns:
            Tuple of (file_path, workspace_relative_path)
        """
        try:
            # Decode base64
            binary_data = base64.b64decode(base64_data)
            return self.save_binary_output(
                binary_data, server_name, tool_name, mime_type
            )
        except Exception as e:
            logger.error(f"Failed to decode/save base64 data: {e}")
            raise

    def generate_file_pointer_message(
        self,
        file_path: str,
        original_size: int,
        content_type: str = "output",
        format_description: str | None = None,
    ) -> str:
        """
        Generate a friendly message with file pointer for the LLM.

        Args:
            file_path: Workspace-relative file path
            original_size: Original content size (chars/bytes)
            content_type: Description of content (e.g., "output", "resource")
            format_description: Format details (e.g., "JSON", "PNG image")

        Returns:
            Formatted message string
        """
        format_info = f" (Format: {format_description})" if format_description else ""

        message = (
            f"[{content_type.upper()} SAVED TO DISK]\n\n"
            f"The {content_type} ({self._format_size(original_size)}) has been saved to:\n"
            f"  {file_path}\n\n"
            f"{format_info}\n"
            f"You can read this file using the read_file tool to access the full content."
        )

        return message

    def _mime_to_extension(self, mime_type: str) -> str:
        """
        Map MIME type to file extension.

        Args:
            mime_type: MIME type string

        Returns:
            File extension (without dot)
        """
        # Strip parameters (e.g., "text/html; charset=utf-8" -> "text/html")
        mime_base = mime_type.split(";")[0].strip().lower()

        mime_map = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/gif": "gif",
            "image/webp": "webp",
            "image/svg+xml": "svg",
            "application/pdf": "pdf",
            "application/json": "json",
            "text/plain": "txt",
            "text/html": "html",
            "text/csv": "csv",
            "text/markdown": "md",
            "application/zip": "zip",
            "application/octet-stream": "bin",
        }

        return mime_map.get(mime_base, "bin")

    def _format_size(self, size: int) -> str:
        """
        Format byte/char count into human-readable string.

        Args:
            size: Size in bytes/chars

        Returns:
            Formatted string (e.g., "1.5 MB")
        """
        if size < 1024:
            return f"{size} bytes"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"

    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        """
        Clean up old output files.

        Args:
            max_age_hours: Delete files older than this many hours

        Returns:
            Number of files deleted
        """
        if not os.path.exists(self.output_dir):
            return 0

        now = datetime.now()
        max_age_seconds = max_age_hours * 3600
        deleted_count = 0

        try:
            for filename in os.listdir(self.output_dir):
                file_path = os.path.join(self.output_dir, filename)

                if not os.path.isfile(file_path):
                    continue

                # Check file age
                file_mtime = os.path.getmtime(file_path)
                age_seconds = (now.timestamp() - file_mtime)

                if age_seconds > max_age_seconds:
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.debug(f"Deleted old output file: {filename}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {filename}: {e}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old output files")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

        return deleted_count
