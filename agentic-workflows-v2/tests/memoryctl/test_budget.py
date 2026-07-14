"""Tests for ``memoryctl budget`` (topic line caps, index soft/hard caps)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_v2.memoryctl import budget
from agentic_v2.memoryctl._shared import (
    SEVERITY_ERROR,
    SEVERITY_WARN,
    CommandResult,
    Finding,
    MemoryctlConfig,
)

BUDGET_TOPIC_CAP = 10
BUDGET_INDEX_SOFT_CAP = 20


def _write_lines(path: Path, count: int) -> None:
    path.write_text("\n".join(f"line {i}" for i in range(count)), encoding="utf-8")


def _by_code(result: CommandResult, code: str) -> list[Finding]:
    return [f for f in result.findings if f.code == code]


@pytest.fixture
def budget_memory_dir(tmp_path: Path) -> Path:
    root = tmp_path / "memory"
    root.mkdir()
    return root


@pytest.fixture
def budget_cfg(budget_memory_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(
        memory_dirs=(budget_memory_dir,),
        topic_line_cap=BUDGET_TOPIC_CAP,
        index_soft_cap=BUDGET_INDEX_SOFT_CAP,
    )


class TestTopicCap:
    def test_topic_at_cap_is_clean(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        _write_lines(budget_memory_dir / "topic.md", BUDGET_TOPIC_CAP)

        result = budget.run(budget_cfg)

        assert result.findings == ()

    def test_topic_over_cap_warns_with_line_count(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        _write_lines(budget_memory_dir / "topic.md", BUDGET_TOPIC_CAP + 5)

        result = budget.run(budget_cfg)

        found = _by_code(result, budget.CODE_TOPIC_OVER)
        assert len(found) == 1
        assert found[0].severity == SEVERITY_WARN
        assert found[0].data["lines"] == BUDGET_TOPIC_CAP + 5
        assert found[0].path == budget_memory_dir / "topic.md"

    def test_each_oversized_topic_gets_its_own_finding(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        _write_lines(budget_memory_dir / "a.md", BUDGET_TOPIC_CAP + 1)
        _write_lines(budget_memory_dir / "b.md", BUDGET_TOPIC_CAP + 2)
        _write_lines(budget_memory_dir / "small.md", 1)

        result = budget.run(budget_cfg)

        assert len(_by_code(result, budget.CODE_TOPIC_OVER)) == 2


class TestIndexCaps:
    def test_index_under_soft_cap_is_clean(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        _write_lines(budget_memory_dir / "MEMORY.md", BUDGET_INDEX_SOFT_CAP)

        result = budget.run(budget_cfg)

        assert result.findings == ()

    def test_index_over_soft_cap_warns(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        _write_lines(budget_memory_dir / "MEMORY.md", BUDGET_INDEX_SOFT_CAP + 1)

        result = budget.run(budget_cfg)

        found = _by_code(result, budget.CODE_INDEX_SOFT)
        assert len(found) == 1
        assert found[0].severity == SEVERITY_WARN
        assert found[0].data["lines"] == BUDGET_INDEX_SOFT_CAP + 1

    def test_index_over_hard_line_cap_is_error_and_supersedes_soft(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        _write_lines(budget_memory_dir / "MEMORY.md", budget.INDEX_HARD_LINE_CAP + 1)

        result = budget.run(budget_cfg)

        hard = _by_code(result, budget.CODE_INDEX_HARD)
        assert len(hard) == 1
        assert hard[0].severity == SEVERITY_ERROR
        assert hard[0].data["lines"] == budget.INDEX_HARD_LINE_CAP + 1
        assert _by_code(result, budget.CODE_INDEX_SOFT) == []

    def test_index_over_hard_byte_cap_is_error_even_with_few_lines(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        index_path = budget_memory_dir / "MEMORY.md"
        index_path.write_text("x" * (budget.INDEX_HARD_BYTE_CAP + 1), encoding="utf-8")

        result = budget.run(budget_cfg)

        hard = _by_code(result, budget.CODE_INDEX_HARD)
        assert len(hard) == 1
        assert hard[0].data["bytes"] > budget.INDEX_HARD_BYTE_CAP
        assert hard[0].data["lines"] == 1

    def test_index_is_not_double_counted_as_topic(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        _write_lines(budget_memory_dir / "MEMORY.md", BUDGET_TOPIC_CAP + 5)

        result = budget.run(budget_cfg)

        assert _by_code(result, budget.CODE_TOPIC_OVER) == []

    def test_missing_index_is_clean(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        result = budget.run(budget_cfg)

        assert result.findings == ()

    def test_custom_index_name_is_respected(self, budget_memory_dir: Path) -> None:
        cfg = MemoryctlConfig(
            memory_dirs=(budget_memory_dir,),
            index_name="INDEX.md",
            index_soft_cap=BUDGET_INDEX_SOFT_CAP,
        )
        _write_lines(budget_memory_dir / "INDEX.md", BUDGET_INDEX_SOFT_CAP + 1)

        result = budget.run(cfg)

        assert len(_by_code(result, budget.CODE_INDEX_SOFT)) == 1


class TestContract:
    def test_result_shape_and_read_only(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        _write_lines(budget_memory_dir / "topic.md", BUDGET_TOPIC_CAP + 1)
        before = (budget_memory_dir / "topic.md").read_text(encoding="utf-8")

        result = budget.run(budget_cfg, dry_run=True)

        assert result.name == "budget"
        assert result.changed == ()
        assert "checked" in result.summary
        assert (budget_memory_dir / "topic.md").read_text(encoding="utf-8") == before

    def test_dry_run_matches_real_run(
        self, budget_memory_dir: Path, budget_cfg: MemoryctlConfig
    ) -> None:
        _write_lines(budget_memory_dir / "topic.md", BUDGET_TOPIC_CAP + 1)

        dry = budget.run(budget_cfg, dry_run=True)
        wet = budget.run(budget_cfg, dry_run=False)

        assert dry == wet
