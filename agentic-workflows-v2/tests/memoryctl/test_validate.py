"""Tests for ``agentic_v2.memoryctl.validate`` (schema lint, read-only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_v2.memoryctl import validate
from agentic_v2.memoryctl._shared import (
    SEVERITY_ERROR,
    SEVERITY_WARN,
    CommandResult,
    MemoryctlConfig,
)


def _valid_topic_text(name: str) -> str:
    """A topic file that satisfies every schema rule."""
    return (
        "---\n"
        f"name: {name}\n"
        "description: a useful machine fact\n"
        "type: semantic\n"
        "subtype: project\n"
        "created: 2026-07-10\n"
        "updated: 2026-07-12\n"
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


def _codes(result: CommandResult) -> list[str]:
    return [f.code for f in result.findings]


@pytest.fixture
def validate_memory_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "memory"
    directory.mkdir()
    return directory


@pytest.fixture
def validate_cfg(validate_memory_dir: Path) -> MemoryctlConfig:
    return MemoryctlConfig(memory_dirs=(validate_memory_dir,))


def test_validate_happy_path_no_findings(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    _write(validate_memory_dir, "good-fact.md", _valid_topic_text("good-fact"))

    result = validate.run(validate_cfg)

    assert result.name == "validate"
    assert result.findings == ()
    assert result.changed == ()
    assert result.summary == "1 files, 0 errors, 0 warnings"


def test_validate_accepts_date_objects_and_strings(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    # Bare YAML dates load as datetime.date; quoted ones load as str.
    text = _valid_topic_text("mixed-dates").replace(
        "created: 2026-07-10", "created: '2026-07-10'"
    )
    _write(validate_memory_dir, "mixed-dates.md", text)

    result = validate.run(validate_cfg)

    assert _codes(result) == []


def test_validate_missing_frontmatter_is_error(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    path = _write(validate_memory_dir, "no-meta.md", "just some text\n")

    result = validate.run(validate_cfg)

    assert _codes(result) == ["schema.missing-frontmatter"]
    assert result.findings[0].severity == SEVERITY_ERROR
    assert result.findings[0].path == path
    assert result.summary == "1 files, 1 errors, 0 warnings"


def test_validate_missing_required_keys_listed_in_data(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    _write(validate_memory_dir, "sparse.md", "---\nname: sparse\n---\nbody\n")

    result = validate.run(validate_cfg)

    missing_findings = [f for f in result.findings if f.code == "schema.missing-keys"]
    assert len(missing_findings) == 1
    assert missing_findings[0].data["missing"] == [
        "description",
        "type",
        "created",
        "updated",
        "status",
    ]


def test_validate_invalid_type_is_error(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    text = _valid_topic_text("bad-type").replace("type: semantic", "type: bogus")
    _write(validate_memory_dir, "bad-type.md", text)

    result = validate.run(validate_cfg)

    assert "schema.invalid-type" in _codes(result)


def test_validate_semantic_requires_valid_subtype(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    missing = _valid_topic_text("no-subtype").replace("subtype: project\n", "")
    _write(validate_memory_dir, "no-subtype.md", missing)
    wrong = _valid_topic_text("bad-subtype").replace(
        "subtype: project", "subtype: bogus"
    )
    _write(validate_memory_dir, "bad-subtype.md", wrong)

    result = validate.run(validate_cfg)

    subtype_errors = [f for f in result.findings if f.code == "schema.invalid-subtype"]
    assert len(subtype_errors) == 2
    assert all(f.severity == SEVERITY_ERROR for f in subtype_errors)


def test_validate_unparseable_date_is_error(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    text = _valid_topic_text("bad-date").replace(
        "created: 2026-07-10", "created: not-a-date"
    )
    _write(validate_memory_dir, "bad-date.md", text)

    result = validate.run(validate_cfg)

    date_errors = [f for f in result.findings if f.code == "schema.invalid-date"]
    assert len(date_errors) == 1
    assert date_errors[0].data["key"] == "created"


def test_validate_status_active_and_superseded_ok_others_error(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    superseded = _valid_topic_text("old-fact").replace(
        "status: active", "status: 'superseded-by:[[new-fact]]'"
    )
    _write(validate_memory_dir, "old-fact.md", superseded)
    retired = _valid_topic_text("retired-fact").replace(
        "status: active", "status: retired"
    )
    _write(validate_memory_dir, "retired-fact.md", retired)

    result = validate.run(validate_cfg)

    status_errors = [f for f in result.findings if f.code == "schema.invalid-status"]
    assert len(status_errors) == 1
    assert status_errors[0].path == validate_memory_dir / "retired-fact.md"


def test_validate_warns_on_name_mismatch_description_and_no_verify(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    text = _valid_topic_text("other-name").replace(
        "description: a useful machine fact",
        f"description: {'x' * 201}",
    )
    text = text.replace("verify: manual\n", "")
    _write(validate_memory_dir, "actual-file.md", text)

    result = validate.run(validate_cfg)

    codes = _codes(result)
    assert codes.count("schema.name-mismatch") == 1
    assert codes.count("schema.description-length") == 1
    assert codes.count("schema.no-verify") == 1
    assert all(f.severity == SEVERITY_WARN for f in result.findings)
    assert result.summary == "1 files, 0 errors, 3 warnings"


def test_validate_skips_index_file_and_never_mutates(
    validate_cfg: MemoryctlConfig, validate_memory_dir: Path
) -> None:
    _write(validate_memory_dir, "MEMORY.md", "# Memory Index\n\nnot frontmatter\n")
    topic = _write(validate_memory_dir, "no-meta.md", "raw text, no frontmatter\n")
    before = topic.read_text(encoding="utf-8")

    result = validate.run(validate_cfg, dry_run=True)

    assert result.summary == "1 files, 1 errors, 0 warnings"
    assert topic.read_text(encoding="utf-8") == before
    index_path = validate_memory_dir / "MEMORY.md"
    assert (
        index_path.read_text(encoding="utf-8") == "# Memory Index\n\nnot frontmatter\n"
    )
