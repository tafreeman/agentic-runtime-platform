"""Tests for ledger.blobs.BlobStore: content addressing, atomic writes,
verify-on-read, and pruning.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ledger.blobs import BlobStore
from ledger.ids import digest_bytes
from ledger.store import BlobCorrupt, BlobMissing


@pytest.fixture
def ledger_blob_store(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobstore")


# ---------------------------------------------------------------------
# path_for / sharding
# ---------------------------------------------------------------------


def test_path_for_shards_on_first_two_hex_chars(ledger_blob_store: BlobStore) -> None:
    digest = digest_bytes(b"hello")
    hex_part = digest.removeprefix("sha256:")
    expected = ledger_blob_store.root / hex_part[:2] / hex_part[2:]
    assert ledger_blob_store.path_for(digest) == expected


def test_path_for_rejects_malformed_digest(ledger_blob_store: BlobStore) -> None:
    with pytest.raises(ValueError, match="unexpected format"):
        ledger_blob_store.path_for("not-a-digest")


# ---------------------------------------------------------------------
# put(): idempotency, content-addressing, atomicity
# ---------------------------------------------------------------------


def test_put_returns_blob_matching_digest_bytes(ledger_blob_store: BlobStore) -> None:
    data = b"the quick brown fox"
    blob = ledger_blob_store.put(data, media_type="text/plain", retention="durable")
    assert blob.digest == digest_bytes(data)
    assert blob.size_bytes == len(data)
    assert blob.media_type == "text/plain"
    assert blob.retention == "durable"


def test_put_writes_bytes_readable_back_via_path_for(
    ledger_blob_store: BlobStore,
) -> None:
    data = b"payload-1"
    blob = ledger_blob_store.put(data, media_type="text/plain", retention="durable")
    on_disk = ledger_blob_store.path_for(blob.digest).read_bytes()
    assert on_disk == data


def test_put_is_idempotent_no_error_no_rewrite(ledger_blob_store: BlobStore) -> None:
    data = b"same bytes twice"
    first = ledger_blob_store.put(data, media_type="text/plain", retention="durable")
    path = ledger_blob_store.path_for(first.digest)
    mtime_before = path.stat().st_mtime_ns

    second = ledger_blob_store.put(data, media_type="text/plain", retention="durable")
    mtime_after = path.stat().st_mtime_ns

    assert first.digest == second.digest
    assert mtime_before == mtime_after, "put() rewrote an already-stored blob"


def test_put_distinct_bytes_land_at_distinct_paths(
    ledger_blob_store: BlobStore,
) -> None:
    blob_a = ledger_blob_store.put(b"aaa", media_type="text/plain", retention="durable")
    blob_b = ledger_blob_store.put(b"bbb", media_type="text/plain", retention="durable")
    assert blob_a.digest != blob_b.digest
    assert ledger_blob_store.path_for(blob_a.digest) != ledger_blob_store.path_for(
        blob_b.digest
    )


def test_put_leaves_no_temp_file_behind(ledger_blob_store: BlobStore) -> None:
    ledger_blob_store.put(b"clean write", media_type="text/plain", retention="durable")
    leftovers = [
        p for p in ledger_blob_store.root.rglob("*") if p.is_file() and ".tmp" in p.name
    ]
    assert leftovers == []


# ---------------------------------------------------------------------
# has() / get()
# ---------------------------------------------------------------------


def test_has_true_after_put_false_before(ledger_blob_store: BlobStore) -> None:
    digest = digest_bytes(b"exists-check")
    assert ledger_blob_store.has(digest) is False
    ledger_blob_store.put(b"exists-check", media_type="text/plain", retention="durable")
    assert ledger_blob_store.has(digest) is True


def test_get_returns_original_bytes(ledger_blob_store: BlobStore) -> None:
    data = b"round trip me"
    blob = ledger_blob_store.put(data, media_type="text/plain", retention="durable")
    assert ledger_blob_store.get(blob.digest) == data


def test_get_raises_blob_missing_when_absent(ledger_blob_store: BlobStore) -> None:
    with pytest.raises(BlobMissing):
        ledger_blob_store.get(digest_bytes(b"never stored"))


def test_get_raises_blob_corrupt_on_tampered_file(
    ledger_blob_store: BlobStore,
) -> None:
    blob = ledger_blob_store.put(
        b"original bytes", media_type="text/plain", retention="durable"
    )
    path = ledger_blob_store.path_for(blob.digest)
    path.write_bytes(b"tampered bytes, wrong hash entirely")

    with pytest.raises(BlobCorrupt):
        ledger_blob_store.get(blob.digest)


# ---------------------------------------------------------------------
# Atomic write: a crash mid-write must not leave a corrupt file at the
# valid digest path.
# ---------------------------------------------------------------------


def test_interrupted_write_leaves_no_file_at_digest_path(
    ledger_blob_store: BlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"never quite makes it to disk"
    digest = digest_bytes(data)
    dest = ledger_blob_store.path_for(digest)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated crash before os.replace")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError, match="simulated crash"):
        ledger_blob_store.put(data, media_type="text/plain", retention="durable")

    assert not dest.exists()
    # No stray temp file left in the shard directory either.
    shard_dir = dest.parent
    leftovers = list(shard_dir.iterdir()) if shard_dir.is_dir() else []
    assert leftovers == []


# ---------------------------------------------------------------------
# prune()
# ---------------------------------------------------------------------


def test_prune_removes_only_named_digests(ledger_blob_store: BlobStore) -> None:
    keep = ledger_blob_store.put(
        b"keep me", media_type="text/plain", retention="durable"
    )
    drop = ledger_blob_store.put(
        b"drop me", media_type="text/plain", retention="prunable"
    )

    removed = ledger_blob_store.prune([drop.digest])

    assert removed == 1
    assert ledger_blob_store.has(keep.digest) is True
    assert ledger_blob_store.has(drop.digest) is False


def test_prune_counts_only_digests_actually_removed(
    ledger_blob_store: BlobStore,
) -> None:
    drop = ledger_blob_store.put(
        b"real blob", media_type="text/plain", retention="prunable"
    )
    never_stored = digest_bytes(b"was never put")

    removed = ledger_blob_store.prune([drop.digest, never_stored])

    assert removed == 1


def test_prune_of_nothing_removes_nothing(ledger_blob_store: BlobStore) -> None:
    ledger_blob_store.put(b"untouched", media_type="text/plain", retention="durable")
    assert ledger_blob_store.prune([]) == 0
