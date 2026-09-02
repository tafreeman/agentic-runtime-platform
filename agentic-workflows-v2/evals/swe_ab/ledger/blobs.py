"""Content-addressed on-disk store for large ledger payloads (transcripts,
patches, problem statements, error dumps).

A blob's location is derived entirely from its content: `put()` hashes the
bytes with `ledger.ids.digest_bytes` and writes them under a two-level
sharded path (`root/<first 2 hex chars>/<rest>`), so identical bytes always
land at the same path and are written at most once. Writes are atomic
(temp file + fsync + `os.replace`) and reads are verified against the
digest, so a crash mid-write or bit-rot on disk surfaces as a clear
exception rather than silently returning corrupt bytes.

Standard library only.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .ids import digest_bytes
from .models import Blob
from .store import BlobCorrupt, BlobMissing

__all__ = ["BlobStore", "BlobMissing", "BlobCorrupt"]


def _hex_part(digest: str) -> str:
    """Return the hex half of a `sha256:<hex>`-style digest string."""
    _, sep, hex_part = digest.rpartition(":")
    if not sep or not hex_part:
        raise ValueError(f"digest has unexpected format (want 'algo:hex'): {digest!r}")
    return hex_part


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(dest: Path, data: bytes) -> None:
    """Write `data` to `dest` atomically: temp file in the same directory,
    fsync, then `os.replace`. If anything fails before the replace, the
    temp file is removed and `dest` is left untouched — never partially
    written.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, dest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            # Already replaced or removed by another writer racing us onto
            # the same digest path; nothing left to clean up.
            pass
        raise


def _prune_empty_shard_dir(shard_dir: Path) -> None:
    try:
        shard_dir.rmdir()
    except OSError:
        # Non-empty (other blobs still shard into this prefix) or already
        # gone; either way there is nothing left to clean up.
        pass


class BlobStore:
    """A content-addressed file store rooted at `root`."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, digest: str) -> Path:
        """Return the on-disk path a blob with `digest` would live at,
        whether or not it currently exists."""
        hex_part = _hex_part(digest)
        return self._root / hex_part[:2] / hex_part[2:]

    def has(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def put(self, data: bytes, *, media_type: str, retention: str) -> Blob:
        """Store `data`, keyed by its own digest, and return the `Blob`
        row for it. Idempotent: writing the same bytes twice performs the
        write once — the second call finds the path already occupied and
        returns without touching disk again.
        """
        digest = digest_bytes(data)
        dest = self.path_for(digest)
        if not dest.is_file():
            _atomic_write(dest, data)
        return Blob(
            digest=digest,
            media_type=media_type,
            size_bytes=len(data),
            retention=retention,
            stored_at=_utc_now_iso(),
        )

    def get(self, digest: str) -> bytes:
        """Return the bytes stored for `digest`.

        Raises `BlobMissing` if no file exists at that digest's path, and
        `BlobCorrupt` if the bytes found there do not hash back to
        `digest` — verified on every read so bit-rot or a partial write
        that slipped past `put()`'s atomicity is never handed back to a
        caller as if it were valid.
        """
        path = self.path_for(digest)
        if not path.is_file():
            raise BlobMissing(f"no blob stored for digest {digest!r}")
        data = path.read_bytes()
        actual = digest_bytes(data)
        if actual != digest:
            raise BlobCorrupt(
                f"blob at {path} does not match digest {digest!r} "
                f"(bytes on disk hash to {actual!r})"
            )
        return data

    def prune(self, digests: Iterable[str]) -> int:
        """Delete the named blobs from disk and return the count actually
        removed (a digest with no file on disk is skipped, not an error).

        Callers are responsible for only passing digests whose `blob` row
        has `retention='prunable'` in the ledger database — `BlobStore`
        has no database handle and no way to check that itself, so
        pruning a `retention='durable'` digest is a caller bug this
        method cannot detect or prevent.
        """
        removed = 0
        for digest in digests:
            path = self.path_for(digest)
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            removed += 1
            _prune_empty_shard_dir(path.parent)
        return removed
