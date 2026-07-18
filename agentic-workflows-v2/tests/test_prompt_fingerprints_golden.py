"""Golden fingerprint test for the prompt-versioning registry (ADR-056).

Asserts that every registered prompt's fingerprint (declared version +
content hash) matches a committed golden file, so an unreviewed content
change to any of the 7 role personas or the inline judge prompt is caught
as an explicit test failure rather than silently drifting.

To update the golden file after an *intentional* prompt content change:
    1. Delete tests/golden/prompt_fingerprints.json
    2. Run: pytest tests/test_prompt_fingerprints_golden.py
       (it regenerates the file and skips with an instruction to review)
    3. Review the diff, then re-run the test to verify it passes
    4. Commit the updated golden file

The golden file itself is never hand-edited: every hash in it is produced
by :func:`_current_fingerprints`, which calls the same
``compute_content_hash`` / registry machinery the production code uses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.prompts.registry import PromptRecord, default_registry
from agentic_v2.scoring.judge import _JUDGE_PROMPT_RECORD

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_PATH = GOLDEN_DIR / "prompt_fingerprints.json"


def _record_fingerprint(record: PromptRecord) -> dict[str, Any]:
    """Serialize a single PromptRecord's fingerprint fields for the golden file."""
    return {
        "declared_version": record.declared_version,
        "content_sha256": record.content_sha256,
        "short_hash": record.short_hash,
        "qualified_version": record.qualified_version,
        "source": record.source,
    }


def _current_fingerprints() -> dict[str, Any]:
    """Compute the current fingerprint for every registered prompt.

    Includes the 7 role personas from :func:`default_registry` plus the
    inline judge prompt registered in
    :mod:`agentic_v2.scoring.judge` -- every prompt this slice fingerprints.
    """
    fingerprints = {
        record.name: _record_fingerprint(record)
        for record in default_registry().records()
    }
    fingerprints["judge"] = _record_fingerprint(_JUDGE_PROMPT_RECORD)
    return fingerprints


def test_prompt_fingerprints_match_golden():
    """Registered prompt fingerprints must match the committed golden file."""
    current = _current_fingerprints()

    if not GOLDEN_PATH.exists():
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(
            json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        pytest.skip(
            f"Golden file created at {GOLDEN_PATH}. "
            "Review it, then re-run the test to verify."
        )

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    assert set(current.keys()) == set(golden.keys()), (
        "Registered prompt names drifted from the golden file.\n"
        f"  Golden:  {sorted(golden.keys())}\n"
        f"  Current: {sorted(current.keys())}\n"
        f"Update golden: delete {GOLDEN_PATH} and re-run."
    )

    for name, golden_fingerprint in golden.items():
        assert current[name] == golden_fingerprint, (
            f"Fingerprint for prompt '{name}' drifted.\n"
            f"  Golden:  {golden_fingerprint!r}\n"
            f"  Current: {current[name]!r}\n"
            f"Update golden: delete {GOLDEN_PATH} and re-run."
        )


def test_golden_file_has_8_entries():
    """Golden file covers the 7 role personas plus the inline judge prompt."""
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert len(golden) == 8
    assert "judge" in golden
