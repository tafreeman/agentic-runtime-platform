"""Tests for ``agentic_v2.memoryctl.index_cmd`` (harvest-then-regenerate)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_v2.memoryctl import index_cmd
from agentic_v2.memoryctl._shared import (
    SEVERITY_WARN,
    MemoryctlConfig,
    parse_frontmatter,
)

FROZEN_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
FROZEN_DAY = "20260714"
FROZEN_ISO = "2026-07-14"


def _topic_text(name: str, description: str, updated: str = "2026-07-10") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "type: semantic\n"
        "subtype: project\n"
        "created: 2026-07-01\n"
        f"updated: {updated}\n"
        "status: active\n"
        "verify: manual\n"
        "---\n"
        "\n"
        "body\n"
    )


def _write(directory: Path, file_name: str, text: str) -> Path:
    path = directory / file_name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def index_cmd_memory_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "memory"
    directory.mkdir()
    return directory


@pytest.fixture
def index_cmd_cfg(index_cmd_memory_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(memory_dirs=(index_cmd_memory_dir,))


@pytest.fixture
def index_cmd_frozen_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(index_cmd, "now_utc", lambda: FROZEN_NOW)
    return FROZEN_NOW


def test_index_cmd_regenerates_sorted_index_from_frontmatter(
    index_cmd_cfg: MemoryctlConfig, index_cmd_memory_dir: Path
) -> None:
    _write(index_cmd_memory_dir, "beta.md", _topic_text("beta", "second fact"))
    _write(
        index_cmd_memory_dir,
        "alpha.md",
        _topic_text("alpha", "first fact", updated="2026-07-12"),
    )

    result = index_cmd.run(index_cmd_cfg)

    index_path = index_cmd_memory_dir / "MEMORY.md"
    assert index_path in result.changed
    assert index_path.read_text(encoding="utf-8") == (
        "# Memory Index\n"
        "\n"
        "- [alpha](alpha.md) — first fact (updated 2026-07-12)\n"
        "- [beta](beta.md) — second fact (updated 2026-07-10)\n"
    )
    assert result.name == "index"
    assert result.summary == "1 dirs, 2 entries, 0 harvested"


def test_index_cmd_formats_date_object_frontmatter(
    index_cmd_cfg: MemoryctlConfig, index_cmd_memory_dir: Path
) -> None:
    # Bare YAML dates load as datetime.date objects, not strings.
    _write(index_cmd_memory_dir, "dated.md", _topic_text("dated", "has bare dates"))

    index_cmd.run(index_cmd_cfg)

    content = (index_cmd_memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "- [dated](dated.md) — has bare dates (updated 2026-07-10)\n" in content


def test_index_cmd_harvests_handwritten_and_dangling_lines(
    index_cmd_cfg: MemoryctlConfig,
    index_cmd_memory_dir: Path,
    index_cmd_frozen_now: datetime,
) -> None:
    _write(index_cmd_memory_dir, "alpha.md", _topic_text("alpha", "first fact"))
    _write(
        index_cmd_memory_dir,
        "MEMORY.md",
        "# Memory Index\n"
        "\n"
        "- [alpha](alpha.md) — first fact (updated 2026-07-10)\n"
        "remember: use npm not npx on this machine\n"
        "- [ghost](ghost.md) — target no longer exists\n",
    )

    result = index_cmd.run(index_cmd_cfg)

    harvest_file = index_cmd_memory_dir / f"harvested-{FROZEN_DAY}.md"
    meta, body = parse_frontmatter(harvest_file.read_text(encoding="utf-8"))
    assert meta["name"] == f"harvested-{FROZEN_DAY}"
    assert str(meta["description"]).startswith(
        f"Unindexed MEMORY.md content harvested {FROZEN_ISO} (2 line(s))"
    )
    assert meta["type"] == "semantic"
    assert meta["subtype"] == "project"
    assert str(meta["created"]) == FROZEN_ISO
    assert str(meta["updated"]) == FROZEN_ISO
    assert meta["status"] == "active"
    assert meta["verify"] == "manual"
    # BOTH unindexed lines land in the ONE harvest file, in order.
    assert "remember: use npm not npx on this machine" in body
    assert "- [ghost](ghost.md) — target no longer exists" in body
    assert "**Why:** harvested from MEMORY.md by memoryctl index" in body

    content = (index_cmd_memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert f"- [harvested-{FROZEN_DAY}](harvested-{FROZEN_DAY}.md)" in content
    harvest_findings = [f for f in result.findings if f.code == "index.harvested"]
    assert len(harvest_findings) == 1
    assert harvest_findings[0].data["lines"] == [
        "remember: use npm not npx on this machine",
        "- [ghost](ghost.md) — target no longer exists",
    ]
    assert result.summary == "1 dirs, 2 entries, 2 harvested"
    assert set(result.changed) == {
        harvest_file,
        index_cmd_memory_dir / "MEMORY.md",
    }


def test_index_cmd_harvest_numbering_skips_existing_files(
    index_cmd_cfg: MemoryctlConfig,
    index_cmd_memory_dir: Path,
    index_cmd_frozen_now: datetime,
) -> None:
    taken_name = f"harvested-{FROZEN_DAY}"
    _write(
        index_cmd_memory_dir,
        f"{taken_name}.md",
        _topic_text(taken_name, "already harvested earlier today"),
    )
    _write(index_cmd_memory_dir, "MEMORY.md", "a stray unindexed note\n")

    index_cmd.run(index_cmd_cfg)

    assert (index_cmd_memory_dir / f"harvested-{FROZEN_DAY}-2.md").is_file()


def test_index_cmd_dry_run_computes_but_writes_nothing(
    index_cmd_cfg: MemoryctlConfig,
    index_cmd_memory_dir: Path,
    index_cmd_frozen_now: datetime,
) -> None:
    _write(index_cmd_memory_dir, "alpha.md", _topic_text("alpha", "first fact"))
    original = "# Memory Index\n\nsomething a session wrote\n"
    index_path = _write(index_cmd_memory_dir, "MEMORY.md", original)

    result = index_cmd.run(index_cmd_cfg, dry_run=True)

    assert result.changed == ()
    assert index_path.read_text(encoding="utf-8") == original
    assert not (index_cmd_memory_dir / f"harvested-{FROZEN_DAY}.md").exists()
    dry_findings = [f for f in result.findings if f.code == "index.dry-run"]
    assert len(dry_findings) == 1
    would_write = dry_findings[0].data["would_write"]
    assert str(index_path) in would_write
    assert str(index_cmd_memory_dir / f"harvested-{FROZEN_DAY}.md") in would_write
    assert result.summary == "1 dirs, 2 entries, 1 harvested"


def test_index_cmd_warns_over_soft_cap_but_writes_all_entries(
    index_cmd_memory_dir: Path,
) -> None:
    cfg = MemoryctlConfig(memory_dirs=(index_cmd_memory_dir,), index_soft_cap=2)
    for name in ("one", "two", "three"):
        _write(index_cmd_memory_dir, f"{name}.md", _topic_text(name, f"fact {name}"))

    result = index_cmd.run(cfg)

    cap_findings = [f for f in result.findings if f.code == "index.over-soft-cap"]
    assert len(cap_findings) == 1
    assert cap_findings[0].severity == SEVERITY_WARN
    assert cap_findings[0].data == {"entries": 3, "soft_cap": 2}
    content = (index_cmd_memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    entry_lines = [ln for ln in content.splitlines() if ln.startswith("- [")]
    assert len(entry_lines) == 3


def test_index_cmd_is_idempotent_on_second_run(
    index_cmd_cfg: MemoryctlConfig,
    index_cmd_memory_dir: Path,
    index_cmd_frozen_now: datetime,
) -> None:
    _write(index_cmd_memory_dir, "alpha.md", _topic_text("alpha", "first fact"))
    _write(index_cmd_memory_dir, "MEMORY.md", "a stray unindexed note\n")

    index_cmd.run(index_cmd_cfg)
    first_content = (index_cmd_memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    second = index_cmd.run(index_cmd_cfg)

    assert (index_cmd_memory_dir / "MEMORY.md").read_text(encoding="utf-8") == (
        first_content
    )
    assert second.summary == "1 dirs, 2 entries, 0 harvested"


def test_index_cmd_missing_dir_warns_without_crashing(tmp_path: Path) -> None:
    cfg = MemoryctlConfig(memory_dirs=(tmp_path / "does-not-exist",))

    result = index_cmd.run(cfg)

    assert [f.code for f in result.findings] == ["index.missing-dir"]
    assert result.findings[0].severity == SEVERITY_WARN
    assert result.changed == ()
