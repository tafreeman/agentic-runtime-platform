"""Regression tests for deterministic load-report generation."""

from __future__ import annotations

import json

from scripts.build_load_report import build_report


def test_report_timestamp_comes_from_committed_probe(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "cas_consistency.json").write_text(
        json.dumps(
            {
                "schema": "arp.load.cas_consistency/v1",
                "generated_at": "2026-06-14T03:48:16.016554+00:00",
            }
        ),
        encoding="utf-8",
    )

    first = build_report(str(results))
    second = build_report(str(results))

    assert first == second
    assert "Evidence captured **2026-06-14 03:48 UTC**." in first


def test_report_without_probe_timestamp_is_still_deterministic(tmp_path):
    results = tmp_path / "results"
    results.mkdir()

    first = build_report(str(results))
    second = build_report(str(results))

    assert first == second
    assert "Evidence captured" not in first
