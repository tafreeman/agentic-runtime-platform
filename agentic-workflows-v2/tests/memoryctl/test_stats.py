"""Tests for ``agentic_v2.memoryctl.stats`` (episode reduction)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_v2.memoryctl import stats
from agentic_v2.memoryctl._shared import MemoryctlConfig

TS_EARLY = "2026-07-10T00:00:00Z"
TS_LATE = "2026-07-12T09:30:00Z"


def _episode(
    playbook: str | None = "pb-a",
    outcome: str = "success",
    model: str | None = None,
    *,
    degraded: bool = False,
    ts: str = TS_EARLY,
) -> str:
    return json.dumps(
        {
            "ts": ts,
            "repo": "tafreeman/agentic-runtime-platform",
            "playbook": playbook,
            "model": model,
            "degraded": degraded,
            "outcome": outcome,
            "tier_used": 0,
        }
    )


def _write_episodes(run_dir: Path, lines: list[str]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "episodes.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def stats_fleet_dir(tmp_path: Path) -> Path:
    fleet = tmp_path / "fleet"
    _write_episodes(
        fleet / "runs" / "run-1",
        [
            _episode("pb-a", "success", "model-x"),
            _episode("pb-a", "failure", "model-x", degraded=True),
        ],
    )
    _write_episodes(
        fleet / "runs" / "run-2",
        [
            _episode("pb-a", "success", "model-y", ts=TS_LATE),
            _episode("pb-b", "success", None),
        ],
    )
    # Already-archived runs must never be reduced.
    _write_episodes(
        fleet / "runs" / "archive" / "run-old",
        [_episode("pb-never-seen", "success", "model-never-seen")],
    )
    return fleet


@pytest.fixture
def stats_cfg(stats_fleet_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(memory_dirs=(), fleet_dir=stats_fleet_dir)


def _load_stats(fleet_dir: Path) -> dict[str, object]:
    path = fleet_dir / "registry" / "stats.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_reduce_creates_cumulative_stats(
    stats_cfg: MemoryctlConfig, stats_fleet_dir: Path
) -> None:
    result = stats.run(stats_cfg)

    data = _load_stats(stats_fleet_dir)
    assert data["run_ids"] == ["run-1", "run-2"]
    playbooks = data["playbooks"]
    assert isinstance(playbooks, dict)
    assert playbooks["pb-a"] == {
        "applied": 3,
        "succeeded": 2,
        "last_applied": TS_LATE,
    }
    assert playbooks["pb-b"] == {
        "applied": 1,
        "succeeded": 1,
        "last_applied": TS_EARLY,
    }
    models = data["models"]
    assert isinstance(models, dict)
    assert models["model-x"] == {"uses": 2, "degraded": 1}
    assert models["model-y"] == {"uses": 1, "degraded": 0}
    assert "pb-never-seen" not in playbooks
    assert (stats_fleet_dir / "registry" / "stats.json") in result.changed


def test_idempotent_by_run_id(
    stats_cfg: MemoryctlConfig, stats_fleet_dir: Path
) -> None:
    stats.run(stats_cfg)
    first = _load_stats(stats_fleet_dir)

    second_result = stats.run(stats_cfg)
    second = _load_stats(stats_fleet_dir)

    assert second_result.changed == ()
    assert second == first
    assert not [f for f in second_result.findings if f.code == "stats.reduced"]


def test_merges_into_existing_stats(
    stats_cfg: MemoryctlConfig, stats_fleet_dir: Path
) -> None:
    registry = stats_fleet_dir / "registry"
    registry.mkdir()
    (registry / "stats.json").write_text(
        json.dumps(
            {
                "run_ids": ["run-1"],
                "playbooks": {
                    "pb-a": {"applied": 5, "succeeded": 5, "last_applied": TS_EARLY}
                },
                "models": {"model-x": {"uses": 5, "degraded": 0}},
                "updated": "2026-07-11T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    stats.run(stats_cfg)

    data = _load_stats(stats_fleet_dir)
    assert data["run_ids"] == ["run-1", "run-2"]
    playbooks = data["playbooks"]
    assert isinstance(playbooks, dict)
    # run-1 skipped (already reduced); only run-2's pb-a episode merges in.
    assert playbooks["pb-a"] == {
        "applied": 6,
        "succeeded": 6,
        "last_applied": TS_LATE,
    }
    models = data["models"]
    assert isinstance(models, dict)
    assert models["model-x"] == {"uses": 5, "degraded": 0}
    assert models["model-y"] == {"uses": 1, "degraded": 0}


def test_bad_line_warned_and_skipped(
    stats_cfg: MemoryctlConfig, stats_fleet_dir: Path
) -> None:
    episodes = stats_fleet_dir / "runs" / "run-1" / "episodes.jsonl"
    original = episodes.read_text(encoding="utf-8")
    episodes.write_text("{not valid json\n" + original, encoding="utf-8")

    result = stats.run(stats_cfg)

    warns = [f for f in result.findings if f.code == "stats.bad-line"]
    assert len(warns) == 1
    assert warns[0].severity == "warn"
    assert warns[0].data["line"] == 1
    data = _load_stats(stats_fleet_dir)
    playbooks = data["playbooks"]
    assert isinstance(playbooks, dict)
    applied = playbooks["pb-a"]
    assert isinstance(applied, dict)
    assert applied["applied"] == 3  # valid lines still reduced
    assert data["run_ids"] == ["run-1", "run-2"]


def test_no_fleet_dir_reports_info(tmp_path: Path) -> None:
    cfg = MemoryctlConfig(memory_dirs=(tmp_path,), fleet_dir=None)

    result = stats.run(cfg)

    assert result.changed == ()
    assert [f.code for f in result.findings] == ["stats.no-fleet"]
    assert result.findings[0].severity == "info"


def test_dry_run_writes_nothing(
    stats_cfg: MemoryctlConfig, stats_fleet_dir: Path
) -> None:
    result = stats.run(stats_cfg, dry_run=True)

    assert not (stats_fleet_dir / "registry" / "stats.json").exists()
    assert result.changed == ()
    reduced = [f for f in result.findings if f.code == "stats.reduced"]
    assert [str(f.data["run_id"]) for f in reduced] == ["run-1", "run-2"]
    assert all("would reduce" in f.message for f in reduced)


def test_corrupt_stats_file_errors_without_overwrite(
    stats_cfg: MemoryctlConfig, stats_fleet_dir: Path
) -> None:
    registry = stats_fleet_dir / "registry"
    registry.mkdir()
    (registry / "stats.json").write_text("{corrupt", encoding="utf-8")

    result = stats.run(stats_cfg)

    assert [f.code for f in result.findings] == ["stats.corrupt"]
    assert result.findings[0].severity == "error"
    assert result.changed == ()
    text = (registry / "stats.json").read_text(encoding="utf-8")
    assert text == "{corrupt"  # never overwritten
