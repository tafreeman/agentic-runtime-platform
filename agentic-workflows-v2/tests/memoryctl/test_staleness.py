"""Tests for ``memoryctl staleness`` (memory age, unverifiable facts, doc dates).

``_shared.now_utc`` and ``_shared.git_last_commit_date`` are monkeypatched
(module attribute) — no real git repos and no wall-clock dependence.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentic_v2.memoryctl import _shared, staleness
from agentic_v2.memoryctl._shared import (
    SEVERITY_WARN,
    CommandResult,
    Finding,
    MemoryctlConfig,
)

STALENESS_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
STALENESS_STALE_DAYS = 90


def _by_code(result: CommandResult, code: str) -> list[Finding]:
    return [f for f in result.findings if f.code == code]


def _write_memory(
    path: Path,
    *,
    updated: str,
    type_: str = "semantic",
    verify: str | None = None,
    quote_date: bool = False,
) -> None:
    updated_value = f'"{updated}"' if quote_date else updated
    lines = [
        "---",
        f"name: {path.stem}",
        "description: test fact",
        f"type: {type_}",
        f"updated: {updated_value}",
    ]
    if verify is not None:
        lines.append(f"verify: {verify}")
    lines += ["---", "", "Body of the fact.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def staleness_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(_shared, "now_utc", lambda: STALENESS_NOW)
    return STALENESS_NOW


@pytest.fixture
def staleness_memory_dir(tmp_path: Path) -> Path:
    root = tmp_path / "memory"
    root.mkdir()
    return root


@pytest.fixture
def staleness_docs_dir(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    return root


@pytest.fixture
def staleness_memory_cfg(staleness_memory_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(
        memory_dirs=(staleness_memory_dir,), stale_days=STALENESS_STALE_DAYS
    )


@pytest.fixture
def staleness_docs_cfg(staleness_docs_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(
        memory_dirs=(),
        docs_dirs=(staleness_docs_dir,),
        stale_days=STALENESS_STALE_DAYS,
    )


class TestMemoryStaleness:
    def test_stale_memory_warns_with_age(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        _write_memory(staleness_memory_dir / "old-fact.md", updated="2026-01-01")

        result = staleness.run(staleness_memory_cfg)

        found = _by_code(result, staleness.CODE_MEMORY)
        assert len(found) == 1
        assert found[0].severity == SEVERITY_WARN
        assert found[0].data["age_days"] == 193
        assert found[0].path == staleness_memory_dir / "old-fact.md"

    def test_fresh_memory_is_clean(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        _write_memory(staleness_memory_dir / "fresh.md", updated="2026-07-01")

        result = staleness.run(staleness_memory_cfg)

        assert result.findings == ()

    def test_quoted_date_string_is_parsed(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        _write_memory(
            staleness_memory_dir / "old-str.md",
            updated="2026-01-01",
            quote_date=True,
        )

        result = staleness.run(staleness_memory_cfg)

        assert len(_by_code(result, staleness.CODE_MEMORY)) == 1

    def test_missing_updated_yields_no_finding(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        (staleness_memory_dir / "bare.md").write_text(
            "no frontmatter at all", encoding="utf-8"
        )

        result = staleness.run(staleness_memory_cfg)

        assert result.findings == ()

    def test_stale_manual_semantic_also_flags_unverifiable(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        _write_memory(
            staleness_memory_dir / "manual.md",
            updated="2026-01-01",
            type_="semantic",
            verify="manual",
        )

        result = staleness.run(staleness_memory_cfg)

        unverifiable = _by_code(result, staleness.CODE_UNVERIFIABLE)
        assert len(unverifiable) == 1
        assert unverifiable[0].data["age_days"] == 193
        assert len(_by_code(result, staleness.CODE_MEMORY)) == 1

    def test_stale_command_verified_semantic_is_not_unverifiable(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        _write_memory(
            staleness_memory_dir / "cmd.md",
            updated="2026-01-01",
            type_="semantic",
            verify="npm --version",
        )

        result = staleness.run(staleness_memory_cfg)

        assert _by_code(result, staleness.CODE_UNVERIFIABLE) == []

    def test_stale_manual_episodic_is_not_unverifiable(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        _write_memory(
            staleness_memory_dir / "episode.md",
            updated="2026-01-01",
            type_="episodic",
            verify="manual",
        )

        result = staleness.run(staleness_memory_cfg)

        assert _by_code(result, staleness.CODE_UNVERIFIABLE) == []

    def test_fresh_manual_semantic_is_clean(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        _write_memory(
            staleness_memory_dir / "manual-fresh.md",
            updated="2026-07-01",
            type_="semantic",
            verify="manual",
        )

        result = staleness.run(staleness_memory_cfg)

        assert result.findings == ()


class TestDocStaleness:
    def test_stale_doc_via_git_date(
        self,
        staleness_now: datetime,
        staleness_docs_dir: Path,
        staleness_docs_cfg: MemoryctlConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (staleness_docs_dir / "old.md").write_text("doc", encoding="utf-8")
        monkeypatch.setattr(
            _shared,
            "git_last_commit_date",
            lambda path: STALENESS_NOW - timedelta(days=200),
        )

        result = staleness.run(staleness_docs_cfg)

        found = _by_code(result, staleness.CODE_DOC)
        assert len(found) == 1
        assert found[0].data == {"age_days": 200, "source": "git"}

    def test_stale_doc_falls_back_to_mtime_when_untracked(
        self,
        staleness_now: datetime,
        staleness_docs_dir: Path,
        staleness_docs_cfg: MemoryctlConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        doc_path = staleness_docs_dir / "untracked.md"
        doc_path.write_text("doc", encoding="utf-8")
        old_ts = (STALENESS_NOW - timedelta(days=200)).timestamp()
        os.utime(doc_path, (old_ts, old_ts))
        monkeypatch.setattr(_shared, "git_last_commit_date", lambda path: None)

        result = staleness.run(staleness_docs_cfg)

        found = _by_code(result, staleness.CODE_DOC)
        assert len(found) == 1
        assert found[0].data["source"] == "mtime"
        age_days = found[0].data["age_days"]
        assert isinstance(age_days, int)
        assert 199 <= age_days <= 200

    def test_old_mtime_beats_fresh_import_commit(
        self,
        staleness_now: datetime,
        staleness_docs_dir: Path,
        staleness_docs_cfg: MemoryctlConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An initial tracking commit must not launder a stale mtime."""
        doc_path = staleness_docs_dir / "imported.md"
        doc_path.write_text("doc", encoding="utf-8")
        old_ts = (STALENESS_NOW - timedelta(days=200)).timestamp()
        os.utime(doc_path, (old_ts, old_ts))
        monkeypatch.setattr(
            _shared,
            "git_last_commit_date",
            lambda path: STALENESS_NOW - timedelta(days=1),
        )

        result = staleness.run(staleness_docs_cfg)

        found = _by_code(result, staleness.CODE_DOC)
        assert len(found) == 1
        assert found[0].data["source"] == "mtime"

    def test_fresh_doc_is_clean(
        self,
        staleness_now: datetime,
        staleness_docs_dir: Path,
        staleness_docs_cfg: MemoryctlConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (staleness_docs_dir / "fresh.md").write_text("doc", encoding="utf-8")
        monkeypatch.setattr(
            _shared,
            "git_last_commit_date",
            lambda path: STALENESS_NOW - timedelta(days=1),
        )

        result = staleness.run(staleness_docs_cfg)

        assert result.findings == ()

    def test_docs_scan_is_recursive(
        self,
        staleness_now: datetime,
        staleness_docs_dir: Path,
        staleness_docs_cfg: MemoryctlConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nested = staleness_docs_dir / "adr" / "deep"
        nested.mkdir(parents=True)
        (nested / "nested.md").write_text("doc", encoding="utf-8")
        monkeypatch.setattr(
            _shared,
            "git_last_commit_date",
            lambda path: STALENESS_NOW - timedelta(days=365),
        )

        result = staleness.run(staleness_docs_cfg)

        found = _by_code(result, staleness.CODE_DOC)
        assert [f.path for f in found] == [nested / "nested.md"]

    def test_missing_docs_dir_is_clean(
        self, staleness_now: datetime, tmp_path: Path
    ) -> None:
        cfg = MemoryctlConfig(memory_dirs=(), docs_dirs=(tmp_path / "does-not-exist",))

        result = staleness.run(cfg)

        assert result.findings == ()


class TestSummary:
    def test_summary_lists_the_five_oldest_paths(
        self,
        staleness_now: datetime,
        staleness_docs_dir: Path,
        staleness_docs_cfg: MemoryctlConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ages = {
            "a.md": 400,
            "b.md": 350,
            "c.md": 300,
            "d.md": 250,
            "e.md": 200,
            "youngest.md": 150,
        }
        for name in ages:
            (staleness_docs_dir / name).write_text("doc", encoding="utf-8")
        monkeypatch.setattr(
            _shared,
            "git_last_commit_date",
            lambda path: STALENESS_NOW - timedelta(days=ages[path.name]),
        )

        result = staleness.run(staleness_docs_cfg)

        assert len(_by_code(result, staleness.CODE_DOC)) == 6
        assert "6" in result.summary
        for name in ("a.md", "b.md", "c.md", "d.md", "e.md"):
            assert str(staleness_docs_dir / name) in result.summary
        assert "youngest.md" not in result.summary
        assert "(400d)" in result.summary

    def test_empty_summary_reports_zero(self, staleness_now: datetime) -> None:
        result = staleness.run(MemoryctlConfig(memory_dirs=()))

        assert result.summary == "staleness: 0 stale item(s)"


class TestContract:
    def test_result_shape_and_read_only(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        _write_memory(staleness_memory_dir / "old.md", updated="2026-01-01")
        before = (staleness_memory_dir / "old.md").read_text(encoding="utf-8")

        result = staleness.run(staleness_memory_cfg, dry_run=True)

        assert result.name == "staleness"
        assert result.changed == ()
        assert (staleness_memory_dir / "old.md").read_text(encoding="utf-8") == before

    def test_dry_run_matches_real_run(
        self,
        staleness_now: datetime,
        staleness_memory_dir: Path,
        staleness_memory_cfg: MemoryctlConfig,
    ) -> None:
        _write_memory(staleness_memory_dir / "old.md", updated="2026-01-01")

        dry = staleness.run(staleness_memory_cfg, dry_run=True)
        wet = staleness.run(staleness_memory_cfg, dry_run=False)

        assert dry == wet
