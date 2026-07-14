"""Tests for ``agentic_v2.memoryctl.archive`` (tombstones + run rotation)."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from agentic_v2.memoryctl import archive, index_cmd
from agentic_v2.memoryctl._shared import MemoryctlConfig, now_utc

OLD_AGE_DAYS = 200


def _write_topic(path: Path, name: str, status: str = "active") -> None:
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: test fact {name}\n"
        "type: semantic\n"
        "subtype: project\n"
        "created: 2026-07-01\n"
        "updated: 2026-07-01\n"
        f'status: "{status}"\n'
        "verify: manual\n"
        "---\n"
        f"Body of {name}.\n",
        encoding="utf-8",
    )


def _age_dir(path: Path, days: int) -> None:
    stamp = (now_utc() - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))


@pytest.fixture
def archive_memory_dir(tmp_path: Path) -> Path:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_topic(memory_dir / "active-fact.md", "active-fact")
    _write_topic(
        memory_dir / "old-fact.md", "old-fact", status="superseded-by:[[new-fact]]"
    )
    return memory_dir


@pytest.fixture
def archive_cfg(archive_memory_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(memory_dirs=(archive_memory_dir,))


@pytest.fixture
def archive_fleet_dir(tmp_path: Path) -> Path:
    fleet = tmp_path / "fleet"
    for run_id in ("run-reduced", "run-unreduced", "run-fresh"):
        (fleet / "runs" / run_id).mkdir(parents=True)
    (fleet / "registry").mkdir()
    (fleet / "registry" / "stats.json").write_text(
        json.dumps(
            {
                "run_ids": ["run-reduced"],
                "playbooks": {},
                "models": {},
                "updated": "2026-07-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    _age_dir(fleet / "runs" / "run-reduced", OLD_AGE_DAYS)
    _age_dir(fleet / "runs" / "run-unreduced", OLD_AGE_DAYS)
    return fleet


def test_superseded_file_moves_to_archive(
    archive_cfg: MemoryctlConfig, archive_memory_dir: Path
) -> None:
    result = archive.run(archive_cfg)

    assert not (archive_memory_dir / "old-fact.md").exists()
    dest = archive_memory_dir / "archive" / "old-fact.md"
    assert dest.is_file()
    assert (archive_memory_dir / "active-fact.md").is_file()
    assert dest in result.changed
    assert [f.code for f in result.findings] == [
        "archive.superseded",
        "archive.index-regenerated",
    ]


def test_collision_appends_numeric_suffix(
    archive_cfg: MemoryctlConfig, archive_memory_dir: Path
) -> None:
    collision_dir = archive_memory_dir / "archive"
    collision_dir.mkdir()
    (collision_dir / "old-fact.md").write_text("occupied\n", encoding="utf-8")

    archive.run(archive_cfg)

    assert (collision_dir / "old-fact-1.md").is_file()
    assert (collision_dir / "old-fact.md").read_text(encoding="utf-8") == "occupied\n"


def test_dry_run_moves_nothing_and_reports(
    archive_cfg: MemoryctlConfig, archive_memory_dir: Path
) -> None:
    result = archive.run(archive_cfg, dry_run=True)

    assert (archive_memory_dir / "old-fact.md").is_file()
    assert not (archive_memory_dir / "archive").exists()
    assert result.changed == ()
    assert [f.code for f in result.findings] == ["archive.superseded"]
    assert "would move" in result.findings[0].message


def test_expired_reduced_run_rotates(archive_fleet_dir: Path) -> None:
    cfg = MemoryctlConfig(memory_dirs=(), fleet_dir=archive_fleet_dir)

    result = archive.run(cfg)

    rotated = archive_fleet_dir / "runs" / "archive" / "run-reduced"
    assert rotated.is_dir()
    assert not (archive_fleet_dir / "runs" / "run-reduced").exists()
    assert rotated in result.changed


def test_expired_unreduced_run_warns_and_stays(archive_fleet_dir: Path) -> None:
    cfg = MemoryctlConfig(memory_dirs=(), fleet_dir=archive_fleet_dir)

    result = archive.run(cfg)

    assert (archive_fleet_dir / "runs" / "run-unreduced").is_dir()
    warns = [f for f in result.findings if f.code == "archive.unreduced-run"]
    assert len(warns) == 1
    assert warns[0].severity == "warn"
    assert warns[0].data["run_id"] == "run-unreduced"


def test_fresh_run_not_rotated(archive_fleet_dir: Path) -> None:
    cfg = MemoryctlConfig(memory_dirs=(), fleet_dir=archive_fleet_dir)

    result = archive.run(cfg)

    assert (archive_fleet_dir / "runs" / "run-fresh").is_dir()
    codes = [f.code for f in result.findings]
    assert codes.count("archive.rotated") == 1  # only run-reduced


def test_rotation_dry_run_moves_nothing(archive_fleet_dir: Path) -> None:
    cfg = MemoryctlConfig(memory_dirs=(), fleet_dir=archive_fleet_dir)

    result = archive.run(cfg, dry_run=True)

    assert (archive_fleet_dir / "runs" / "run-reduced").is_dir()
    assert not (archive_fleet_dir / "runs" / "archive").exists()
    assert result.changed == ()


def test_missing_stats_file_treats_all_expired_as_unreduced(tmp_path: Path) -> None:
    fleet = tmp_path / "fleet"
    (fleet / "runs" / "run-old").mkdir(parents=True)
    _age_dir(fleet / "runs" / "run-old", OLD_AGE_DAYS)
    cfg = MemoryctlConfig(memory_dirs=(), fleet_dir=fleet)

    result = archive.run(cfg)

    assert (fleet / "runs" / "run-old").is_dir()
    assert [f.code for f in result.findings] == ["archive.unreduced-run"]


def test_archive_regenerates_index_after_tombstone(
    archive_cfg: MemoryctlConfig, archive_memory_dir: Path
) -> None:
    """Tombstone moves must not leave dangling index lines (PR #205 review)."""
    index_cmd.run(archive_cfg)
    before = (archive_memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "old-fact" in before

    result = archive.run(archive_cfg)

    after = (archive_memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "old-fact" not in after
    assert "active-fact" in after
    assert archive_memory_dir / "MEMORY.md" in result.changed
    assert any(f.code == "archive.index-regenerated" for f in result.findings)
    follow_up = index_cmd.run(archive_cfg)
    assert not any(f.code == "index.harvested" for f in follow_up.findings)
