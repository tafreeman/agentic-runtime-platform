"""Tests for ``memoryctl links`` (wiki-links, markdown links, playbook entries)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_v2.memoryctl import links
from agentic_v2.memoryctl._shared import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    CommandResult,
    Finding,
    MemoryctlConfig,
)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _by_code(result: CommandResult, code: str) -> list[Finding]:
    return [f for f in result.findings if f.code == code]


@pytest.fixture
def links_memory_dir(tmp_path: Path) -> Path:
    root = tmp_path / "memory"
    root.mkdir()
    return root


@pytest.fixture
def links_cfg(links_memory_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(memory_dirs=(links_memory_dir,))


@pytest.fixture
def links_fleet_dir(tmp_path: Path) -> Path:
    fleet = tmp_path / "fleet"
    (fleet / "playbooks").mkdir(parents=True)
    return fleet


class TestWikiLinks:
    def test_resolved_wiki_link_is_clean(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(links_memory_dir / "npm-over-npx.md", "Use npm.")
        _write(links_memory_dir / "other.md", "See [[npm-over-npx]] for detail.")

        result = links.run(links_cfg)

        assert _by_code(result, links.CODE_WIKI_UNRESOLVED) == []

    def test_unresolved_wiki_link_warns_per_miss(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(
            links_memory_dir / "topic.md",
            "See [[missing-one]] and [[missing-two]].",
        )

        result = links.run(links_cfg)

        found = _by_code(result, links.CODE_WIKI_UNRESOLVED)
        assert len(found) == 2
        assert all(f.severity == SEVERITY_WARN for f in found)
        assert {f.data["target"] for f in found} == {"missing-one", "missing-two"}
        assert all(f.path == links_memory_dir / "topic.md" for f in found)

    def test_index_body_is_scanned_too(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(links_memory_dir / "MEMORY.md", "- [[nowhere]] pointer")

        result = links.run(links_cfg)

        found = _by_code(result, links.CODE_WIKI_UNRESOLVED)
        assert len(found) == 1
        assert found[0].data["target"] == "nowhere"

    def test_wiki_link_in_frontmatter_is_ignored(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(
            links_memory_dir / "topic.md",
            "---\nstatus: superseded-by:[[gone]]\n---\nBody without links.\n",
        )

        result = links.run(links_cfg)

        assert _by_code(result, links.CODE_WIKI_UNRESOLVED) == []


class TestMarkdownLinks:
    def test_dead_relative_link_is_error(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(links_memory_dir / "topic.md", "See [gone](missing.md).")

        result = links.run(links_cfg)

        found = _by_code(result, links.CODE_DEAD)
        assert len(found) == 1
        assert found[0].severity == SEVERITY_ERROR
        assert found[0].data["target"] == "missing.md"

    def test_resolving_relative_link_is_clean(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(links_memory_dir / "target.md", "content")
        _write(links_memory_dir / "topic.md", "See [there](target.md).")

        result = links.run(links_cfg)

        assert _by_code(result, links.CODE_DEAD) == []

    def test_relative_link_resolves_from_containing_file(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig, tmp_path: Path
    ) -> None:
        _write(tmp_path / "sibling.md", "outside the memory dir")
        _write(links_memory_dir / "topic.md", "See [up](../sibling.md).")

        result = links.run(links_cfg)

        assert _by_code(result, links.CODE_DEAD) == []

    def test_external_and_anchor_targets_are_skipped(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(
            links_memory_dir / "topic.md",
            "[web](https://example.com/x) [plain](http://example.com) "
            "[mail](mailto:a@b.c) [anchor](#section)",
        )

        result = links.run(links_cfg)

        assert _by_code(result, links.CODE_DEAD) == []

    def test_fragment_is_stripped_before_resolving(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(links_memory_dir / "target.md", "content")
        _write(links_memory_dir / "topic.md", "See [t](target.md#part).")

        result = links.run(links_cfg)

        assert _by_code(result, links.CODE_DEAD) == []


class TestPlaybooks:
    def test_missing_entry_is_error(
        self, links_fleet_dir: Path, links_memory_dir: Path
    ) -> None:
        _write(
            links_fleet_dir / "playbooks" / "fix-it.md",
            "---\nname: fix-it\nentry: scripts/fix-it.ps1\n---\nSteps.\n",
        )
        cfg = MemoryctlConfig(
            memory_dirs=(links_memory_dir,), fleet_dir=links_fleet_dir
        )

        result = links.run(cfg)

        found = _by_code(result, links.CODE_ENTRY_MISSING)
        assert len(found) == 1
        assert found[0].severity == SEVERITY_ERROR
        assert found[0].data["entry"] == "scripts/fix-it.ps1"

    def test_existing_entry_is_clean(
        self, links_fleet_dir: Path, links_memory_dir: Path
    ) -> None:
        scripts = links_fleet_dir / "scripts"
        scripts.mkdir()
        _write(scripts / "fix-it.ps1", "# script")
        _write(
            links_fleet_dir / "playbooks" / "fix-it.md",
            "---\nname: fix-it\nentry: scripts/fix-it.ps1\n---\nSteps.\n",
        )
        cfg = MemoryctlConfig(
            memory_dirs=(links_memory_dir,), fleet_dir=links_fleet_dir
        )

        result = links.run(cfg)

        assert _by_code(result, links.CODE_ENTRY_MISSING) == []

    def test_playbook_wiki_links_resolve_against_playbook_stems(
        self, links_fleet_dir: Path, links_memory_dir: Path
    ) -> None:
        _write(links_fleet_dir / "playbooks" / "one.md", "See [[two]] and [[nope]].")
        _write(links_fleet_dir / "playbooks" / "two.md", "content")
        cfg = MemoryctlConfig(
            memory_dirs=(links_memory_dir,), fleet_dir=links_fleet_dir
        )

        result = links.run(cfg)

        found = _by_code(result, links.CODE_WIKI_UNRESOLVED)
        assert [f.data["target"] for f in found] == ["nope"]

    def test_no_fleet_dir_skips_playbooks(self, links_cfg: MemoryctlConfig) -> None:
        result = links.run(links_cfg)

        assert _by_code(result, links.CODE_ENTRY_MISSING) == []


class TestExternalCount:
    def test_external_urls_counted_never_fetched(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(
            links_memory_dir / "topic.md",
            "See https://example.com/a and http://example.org/b.\n",
        )

        result = links.run(links_cfg)

        found = _by_code(result, links.CODE_EXTERNAL_COUNT)
        assert len(found) == 1
        assert found[0].severity == SEVERITY_INFO
        assert found[0].data["count"] == 2

    def test_external_count_zero_when_no_urls(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(links_memory_dir / "topic.md", "no urls here")

        result = links.run(links_cfg)

        found = _by_code(result, links.CODE_EXTERNAL_COUNT)
        assert len(found) == 1
        assert found[0].data["count"] == 0


class TestContract:
    def test_result_shape_and_read_only(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(links_memory_dir / "topic.md", "See [[missing]].")
        before = (links_memory_dir / "topic.md").read_text(encoding="utf-8")

        result = links.run(links_cfg, dry_run=True)

        assert result.name == "links"
        assert result.changed == ()
        assert "checked" in result.summary
        assert (links_memory_dir / "topic.md").read_text(encoding="utf-8") == before

    def test_dry_run_matches_real_run(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig
    ) -> None:
        _write(links_memory_dir / "topic.md", "See [[missing]] and [gone](x.md).")

        dry = links.run(links_cfg, dry_run=True)
        wet = links.run(links_cfg, dry_run=False)

        assert dry == wet


class TestAbsoluteTargets:
    def test_absolute_target_that_exists_is_clean(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig, tmp_path: Path
    ) -> None:
        pointer_target = tmp_path / "design-doc.md"
        pointer_target.write_text("design", encoding="utf-8")
        _write(
            links_memory_dir / "pointer.md",
            f"See [design]({pointer_target.as_posix()}) for detail.",
        )

        result = links.run(links_cfg)

        assert _by_code(result, links.CODE_DEAD) == []

    def test_absolute_target_that_is_missing_is_dead(
        self, links_memory_dir: Path, links_cfg: MemoryctlConfig, tmp_path: Path
    ) -> None:
        missing = tmp_path / "gone" / "doc.md"
        _write(
            links_memory_dir / "pointer.md",
            f"See [design]({missing.as_posix()}) for detail.",
        )

        result = links.run(links_cfg)

        dead = _by_code(result, links.CODE_DEAD)
        assert len(dead) == 1
        assert dead[0].data["target"] == missing.as_posix()
