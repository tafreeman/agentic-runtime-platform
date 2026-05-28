"""Tests for output safety and context budget protection.

Validates:
- Token counting and estimation
- Text truncation with clear messaging
- Content block truncation
- Disk-backed storage for oversized outputs
- File pointer generation
- Path safety and sanitization
"""

import os
import tempfile

from agentic_v2.integrations.mcp.results.budget import (
    ContextBudgetGuard,
    estimate_content_blocks_tokens,
    estimate_token_count,
)
from agentic_v2.integrations.mcp.results.storage import McpOutputStorage


class TestTokenEstimation:
    """Test token counting and estimation."""

    def test_estimate_token_count_simple(self):
        """Test basic token estimation (4 chars per token)."""
        text = "This is a test string with some words."
        tokens = estimate_token_count(text)

        # Rough estimate: 40 chars / 4 = 10 tokens
        assert 8 <= tokens <= 12

    def test_estimate_token_count_empty(self):
        """Test token count for empty string."""
        assert estimate_token_count("") == 0

    def test_estimate_content_blocks_text(self):
        """Test token estimation for text content blocks."""
        blocks = [
            {"type": "text", "text": "First block with text."},
            {"type": "text", "text": "Second block with more text."},
        ]

        tokens = estimate_content_blocks_tokens(blocks)
        assert tokens > 0

    def test_estimate_content_blocks_image(self):
        """Test token estimation includes image blocks (1600 tokens each)."""
        blocks = [{"type": "image", "data": "base64data", "mimeType": "image/png"}]

        tokens = estimate_content_blocks_tokens(blocks)
        assert tokens == 1600

    def test_estimate_content_blocks_mixed(self):
        """Test token estimation with mixed content types."""
        blocks = [
            {"type": "text", "text": "Some text here."},
            {"type": "image", "data": "data", "mimeType": "image/png"},
            {"type": "resource", "uri": "file:///path"},
        ]

        tokens = estimate_content_blocks_tokens(blocks)
        # Text (~4 tokens) + image (1600) + resource (50) ≈ 1654
        assert tokens > 1600


class TestContextBudgetGuard:
    """Test ContextBudgetGuard truncation functionality."""

    def test_guard_creation_default_limit(self):
        """Test creating guard with default token limit."""
        guard = ContextBudgetGuard()
        assert guard.max_tokens == 25000  # Default

    def test_guard_creation_custom_limit(self):
        """Test creating guard with custom limit."""
        guard = ContextBudgetGuard(max_tokens=10000)
        assert guard.max_tokens == 10000

    def test_is_oversized_small_text(self):
        """Test small text is not oversized."""
        guard = ContextBudgetGuard(max_tokens=1000)
        text = "This is a small piece of text."

        assert not guard.is_oversized(text)

    def test_is_oversized_large_text(self):
        """Test large text is detected as oversized."""
        guard = ContextBudgetGuard(max_tokens=10)
        text = "This is a much longer piece of text " * 100

        assert guard.is_oversized(text)

    def test_check_and_truncate_text_no_truncation(self):
        """Test text under budget is not truncated."""
        guard = ContextBudgetGuard(max_tokens=1000)
        text = "Small text"

        result, was_truncated = guard.check_and_truncate_text(text, "server", "tool")

        assert result == text
        assert not was_truncated

    def test_check_and_truncate_text_with_truncation(self):
        """Test oversized text is truncated."""
        guard = ContextBudgetGuard(max_tokens=10)
        text = "This is a very long piece of text " * 100

        result, was_truncated = guard.check_and_truncate_text(text, "server", "tool")

        assert len(result) < len(text)
        assert was_truncated
        assert "TRUNCATED" in result

    def test_check_and_truncate_content_blocks_no_truncation(self):
        """Test content blocks under budget are not truncated."""
        guard = ContextBudgetGuard(max_tokens=10000)
        blocks = [{"type": "text", "text": "Short text"}]

        result, was_truncated = guard.check_and_truncate_content_blocks(
            blocks, "server", "tool"
        )

        assert result == blocks
        assert not was_truncated

    def test_check_and_truncate_content_blocks_with_truncation(self):
        """Test oversized content blocks are truncated."""
        guard = ContextBudgetGuard(max_tokens=100)
        blocks = [
            {"type": "text", "text": "Block 1 " * 100},
            {"type": "text", "text": "Block 2 " * 100},
            {"type": "text", "text": "Block 3 " * 100},
        ]

        result, was_truncated = guard.check_and_truncate_content_blocks(
            blocks, "server", "tool"
        )

        assert len(result) < len(blocks)
        assert was_truncated
        # Should have truncation message as final block
        assert any("TRUNCATED" in str(block) for block in result)

    def test_get_budget_summary(self):
        """Test budget summary provides accurate metrics."""
        guard = ContextBudgetGuard(max_tokens=1000)
        text = "Test text " * 50

        summary = guard.get_budget_summary(text)

        assert "tokens" in summary
        assert "max_tokens" in summary
        assert summary["max_tokens"] == 1000
        assert "percentage_used" in summary
        assert "is_oversized" in summary


class TestMcpOutputStorage:
    """Test McpOutputStorage disk persistence."""

    def test_storage_creation(self):
        """Test creating output storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = McpOutputStorage(
                output_dir=os.path.join(tmpdir, "outputs"),
                workspace_root=tmpdir,
            )

            # Output directory should be created
            assert os.path.exists(storage.output_dir)

    def test_save_text_output(self):
        """Test saving text output to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = McpOutputStorage(
                output_dir=os.path.join(tmpdir, "outputs"),
                workspace_root=tmpdir,
            )

            content = "This is test output content."
            file_path, rel_path = storage.save_text_output(
                content, "test-server", "test-tool"
            )

            # File should exist
            assert os.path.exists(file_path)

            # Content should match
            with open(file_path) as f:
                saved_content = f.read()
            assert saved_content == content

            # Relative path should be workspace-relative
            assert rel_path.startswith(".")

    def test_save_binary_output(self):
        """Test saving binary output to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = McpOutputStorage(
                output_dir=os.path.join(tmpdir, "outputs"),
                workspace_root=tmpdir,
            )

            binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            file_path, rel_path = storage.save_binary_output(
                binary_data, "server", "tool", mime_type="image/png"
            )

            # File should exist with .png extension
            assert os.path.exists(file_path)
            assert file_path.endswith(".png")

            # Content should match
            with open(file_path, "rb") as f:
                saved_data = f.read()
            assert saved_data == binary_data

    def test_save_base64_output(self):
        """Test saving base64-encoded output."""
        import base64

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = McpOutputStorage(
                output_dir=os.path.join(tmpdir, "outputs"),
                workspace_root=tmpdir,
            )

            original_data = b"Test binary data"
            base64_data = base64.b64encode(original_data).decode("utf-8")

            file_path, rel_path = storage.save_base64_output(
                base64_data, "server", "tool"
            )

            # File should exist
            assert os.path.exists(file_path)

            # Decoded content should match original
            with open(file_path, "rb") as f:
                saved_data = f.read()
            assert saved_data == original_data

    def test_filename_sanitization(self):
        """Test filename sanitization prevents path traversal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = McpOutputStorage(
                output_dir=os.path.join(tmpdir, "outputs"),
                workspace_root=tmpdir,
            )

            # Try to save with malicious server/tool names
            content = "test"
            file_path, _ = storage.save_text_output(content, "../../../etc", "passwd")

            # Path separators should be sanitized
            assert "../" not in file_path
            assert os.path.dirname(file_path) == storage.output_dir

    def test_generate_file_pointer_message(self):
        """Test file pointer message generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = McpOutputStorage(workspace_root=tmpdir)

            message = storage.generate_file_pointer_message(
                "outputs/test_file.txt",
                1024,
                content_type="output",
                format_description="JSON",
            )

            assert "outputs/test_file.txt" in message
            assert "1.0 KB" in message
            assert "JSON" in message

    def test_cleanup_old_files(self):
        """Test automatic cleanup of old files."""
        import time

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = McpOutputStorage(
                output_dir=os.path.join(tmpdir, "outputs"),
                workspace_root=tmpdir,
            )

            # Create old file
            old_file = os.path.join(storage.output_dir, "old_file.txt")
            with open(old_file, "w") as f:
                f.write("old")

            # Modify file timestamp to be old
            old_time = time.time() - (25 * 3600)  # 25 hours ago
            os.utime(old_file, (old_time, old_time))

            # Create recent file
            storage.save_text_output("recent", "server", "tool")

            # Cleanup files older than 24 hours
            deleted_count = storage.cleanup_old_files(max_age_hours=24)

            # Old file should be deleted
            assert deleted_count == 1
            assert not os.path.exists(old_file)

    def test_mime_to_extension_mapping(self):
        """Test MIME type to extension mapping."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = McpOutputStorage(workspace_root=tmpdir)

            # Test common MIME types
            assert storage._mime_to_extension("image/png") == "png"
            assert storage._mime_to_extension("image/jpeg") == "jpg"
            assert storage._mime_to_extension("application/json") == "json"
            assert storage._mime_to_extension("text/plain") == "txt"
            assert storage._mime_to_extension("application/pdf") == "pdf"
            assert storage._mime_to_extension("unknown/type") == "bin"
