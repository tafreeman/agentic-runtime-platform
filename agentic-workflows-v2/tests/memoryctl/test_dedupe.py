"""Tests for ``agentic_v2.memoryctl.dedupe``."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_v2.memoryctl import dedupe
from agentic_v2.memoryctl._shared import (
    SEVERITY_INFO,
    SEVERITY_WARN,
    MemoryctlConfig,
    serialize_frontmatter,
)


def _write_dedupe_topic(
    memory_dir: Path, name: str, body: str, description: str | None = None
) -> Path:
    """Write a schema-shaped topic file with the given body/description."""
    meta: dict[str, object] = {
        "name": name,
        "description": description if description is not None else f"{name} desc",
        "type": "semantic",
        "created": "2026-07-14",
        "updated": "2026-07-14",
        "status": "active",
    }
    path = memory_dir / f"{name}.md"
    path.write_text(serialize_frontmatter(meta, body), encoding="utf-8")
    return path


@pytest.fixture
def dedupe_memory_dir(tmp_path: Path) -> Path:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    return memory_dir


@pytest.fixture
def dedupe_cfg(dedupe_memory_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(memory_dirs=(dedupe_memory_dir,))


def test_exact_pair_detected_after_normalization(
    dedupe_cfg: MemoryctlConfig, dedupe_memory_dir: Path
) -> None:
    first = _write_dedupe_topic(dedupe_memory_dir, "alpha", "Hello   WORLD\n\ttwice\n")
    second = _write_dedupe_topic(dedupe_memory_dir, "beta", "hello world twice")

    result = dedupe.run(dedupe_cfg)

    assert result.name == "dedupe"
    assert result.changed == ()
    exact = [f for f in result.findings if f.code == "dedupe.exact"]
    assert len(exact) == 1
    assert exact[0].severity == SEVERITY_WARN
    assert exact[0].data == {"a": str(first), "b": str(second)}
    assert "1 exact duplicate pair(s)" in result.summary


def test_triple_yields_one_finding_per_pair(
    dedupe_cfg: MemoryctlConfig, dedupe_memory_dir: Path
) -> None:
    for name in ("alpha", "beta", "gamma"):
        _write_dedupe_topic(dedupe_memory_dir, name, "same body")

    result = dedupe.run(dedupe_cfg)

    exact = [f for f in result.findings if f.code == "dedupe.exact"]
    assert len(exact) == 3
    pairs = {(f.data["a"], f.data["b"]) for f in exact}
    assert len(pairs) == 3


def test_duplicate_descriptions_flagged_info(
    dedupe_cfg: MemoryctlConfig, dedupe_memory_dir: Path
) -> None:
    first = _write_dedupe_topic(
        dedupe_memory_dir, "alpha", "body one", description="Shared  Retrieval SIGNAL"
    )
    second = _write_dedupe_topic(
        dedupe_memory_dir, "beta", "body two", description="shared retrieval signal"
    )

    result = dedupe.run(dedupe_cfg)

    assert [f.code for f in result.findings] == ["dedupe.description"]
    finding = result.findings[0]
    assert finding.severity == SEVERITY_INFO
    assert finding.data == {"a": str(first), "b": str(second)}
    assert "1 duplicate description pair(s)" in result.summary


def test_distinct_files_yield_no_findings(
    dedupe_cfg: MemoryctlConfig, dedupe_memory_dir: Path
) -> None:
    _write_dedupe_topic(dedupe_memory_dir, "alpha", "body one")
    _write_dedupe_topic(dedupe_memory_dir, "beta", "body two")

    result = dedupe.run(dedupe_cfg)

    assert result.findings == ()
    assert "0 exact duplicate pair(s)" in result.summary


def test_duplicates_not_compared_across_memory_dirs(tmp_path: Path) -> None:
    dir_one = tmp_path / "memory-one"
    dir_two = tmp_path / "memory-two"
    dir_one.mkdir()
    dir_two.mkdir()
    _write_dedupe_topic(dir_one, "alpha", "same body", description="same desc one")
    _write_dedupe_topic(dir_two, "beta", "same body", description="same desc two")
    cfg = MemoryctlConfig(memory_dirs=(dir_one, dir_two))

    result = dedupe.run(cfg)

    assert result.findings == ()
    assert "2 dir(s)" in result.summary


def test_index_and_empty_bodies_are_ignored(
    dedupe_cfg: MemoryctlConfig, dedupe_memory_dir: Path
) -> None:
    # Index file matching a topic body must not be compared.
    index = dedupe_memory_dir / dedupe_cfg.index_name
    index.write_text("same body", encoding="utf-8")
    _write_dedupe_topic(dedupe_memory_dir, "alpha", "same body")
    # Two empty bodies are a validate concern, not a duplicate pair.
    _write_dedupe_topic(dedupe_memory_dir, "empty-one", "\n\n")
    _write_dedupe_topic(dedupe_memory_dir, "empty-two", "  \n")

    result = dedupe.run(dedupe_cfg)

    assert [f for f in result.findings if f.code == "dedupe.exact"] == []


def test_dry_run_is_a_no_op_for_read_only_command(
    dedupe_cfg: MemoryctlConfig, dedupe_memory_dir: Path
) -> None:
    _write_dedupe_topic(dedupe_memory_dir, "alpha", "same body")
    _write_dedupe_topic(dedupe_memory_dir, "beta", "same body")
    before = sorted(p.name for p in dedupe_memory_dir.iterdir())

    result = dedupe.run(dedupe_cfg, dry_run=True)

    assert len(result.findings) == 1
    assert result.changed == ()
    assert sorted(p.name for p in dedupe_memory_dir.iterdir()) == before


def test_normalize_text_collapses_case_and_whitespace() -> None:
    assert dedupe.normalize_text("  A\t\nB   c ") == "a b c"
    assert dedupe.normalize_text("") == ""
