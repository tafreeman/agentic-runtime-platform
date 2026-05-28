"""Tests for path safety helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentic_v2.utils.path_safety import ensure_within_base, is_within_base


class TestIsWithinBase:
    """Tests for is_within_base."""

    def test_child_path_is_within_base(self, tmp_path: Path) -> None:
        """A child file resolves as within the base directory."""
        child = tmp_path / "subdir" / "file.txt"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()
        assert is_within_base(child, tmp_path) is True

    def test_exact_base_path_is_within(self, tmp_path: Path) -> None:
        """The base directory itself is within itself."""
        assert is_within_base(tmp_path, tmp_path) is True

    def test_parent_traversal_rejected(self, tmp_path: Path) -> None:
        """../../etc/passwd is NOT within the base."""
        malicious = tmp_path / ".." / ".." / "etc" / "passwd"
        assert is_within_base(malicious, tmp_path) is False

    def test_relative_path_within_base(self, tmp_path: Path) -> None:
        """Relative path ./subdir/file.txt resolves correctly."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        target = subdir / "file.txt"
        target.touch()
        # Use a path that includes a redundant "./" segment
        relative = tmp_path / "." / "subdir" / "file.txt"
        assert is_within_base(relative, tmp_path) is True

    def test_deeply_nested_traversal_rejected(self, tmp_path: Path) -> None:
        """./a/../../b/../../../etc is rejected."""
        nested = tmp_path / "a" / ".." / ".." / "b" / ".." / ".." / ".." / "etc"
        assert is_within_base(nested, tmp_path) is False

    def test_symlink_traversal_rejected(self, tmp_path: Path) -> None:
        """Symlink that escapes base is rejected (after resolve())."""
        # Create a target outside the base
        outside = tmp_path.parent / "outside_target"
        outside.mkdir(exist_ok=True)
        outside_file = outside / "secret.txt"
        outside_file.write_text("secret")

        # Create a symlink inside base pointing outside
        link = tmp_path / "escape_link"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("Cannot create symlinks on this platform")

        secret_via_link = link / "secret.txt"
        assert is_within_base(secret_via_link, tmp_path) is False

        # Cleanup
        outside_file.unlink(missing_ok=True)
        outside.rmdir()

    def test_sibling_directory_rejected(self, tmp_path: Path) -> None:
        """A sibling directory is not within the base."""
        base = tmp_path / "project"
        base.mkdir()
        sibling = tmp_path / "other" / "file.txt"
        assert is_within_base(sibling, base) is False


class TestEnsureWithinBase:
    """Tests for ensure_within_base."""

    def test_valid_path_returns_resolved(self, tmp_path: Path) -> None:
        """Valid path returns a resolved Path object."""
        child = tmp_path / "sub" / "file.txt"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()

        result = ensure_within_base(child, tmp_path)
        assert isinstance(result, Path)
        assert result.is_absolute()
        assert result == child.resolve()

    def test_traversal_raises_value_error(self, tmp_path: Path) -> None:
        """Path traversal raises ValueError with descriptive message."""
        malicious = tmp_path / ".." / ".." / "etc" / "passwd"
        with pytest.raises(ValueError, match="Path escapes base directory"):
            ensure_within_base(malicious, tmp_path)

    def test_error_message_includes_original_path(self, tmp_path: Path) -> None:
        """The ValueError message includes the offending path."""
        bad_path = tmp_path / ".." / ".." / "secret"
        with pytest.raises(ValueError) as exc_info:
            ensure_within_base(bad_path, tmp_path)
        assert "secret" in str(exc_info.value)
