"""Tests for the McNemar band selector.

Run from the kit: ``uv run python -m pytest tools -q``. Lives next to the script
for the same sys.path reason as ``test_wave_guards.py``.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import band_cases
import pytest


def _case(sid: str, band: object) -> dict:
    return {"sample_id": sid, "input": {}, "metadata": {"difficulty_score": band}}


def _write_cases(path: Path, cases: list[dict]) -> None:
    path.write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")


def _sample(sid: str, band: object, status: str) -> dict:
    return {
        "execution": {"sample_id": sid},
        "grade": {"status": status},
        "sample": {"metadata": {"difficulty_score": band}},
    }


def _write_report(path: Path, samples: list[dict]) -> None:
    path.write_text(json.dumps({"samples": samples}), encoding="utf-8")


def _run_main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["band_cases.py", *argv])
    return band_cases.main()


# --- statistics helpers ---------------------------------------------------


def test_wilson_empty_sample_is_uninformative() -> None:
    assert band_cases.wilson(0, 0) == (0.0, 1.0)


@pytest.mark.parametrize(("k", "n"), [(0, 10), (3, 10), (10, 10), (47, 100)])
def test_wilson_interval_brackets_point_estimate(k: int, n: int) -> None:
    lo, hi = band_cases.wilson(k, n)
    assert 0.0 <= lo <= k / n <= hi <= 1.0


def test_wilson_narrows_as_n_grows() -> None:
    lo_small, hi_small = band_cases.wilson(5, 10)
    lo_big, hi_big = band_cases.wilson(500, 1000)
    assert hi_big - lo_big < hi_small - lo_small


def test_discordant_pairs_needed_is_infinite_at_the_null() -> None:
    assert math.isinf(band_cases.discordant_pairs_needed(0.5))


def test_larger_effects_need_fewer_discordant_pairs() -> None:
    moderate = band_cases.discordant_pairs_needed(0.65)
    large = band_cases.discordant_pairs_needed(0.75)
    assert 0 < large < moderate


def test_expected_discordance_peaks_at_half_and_vanishes_at_extremes() -> None:
    kappa = band_cases.DEFAULT_KAPPA
    peak = band_cases.expected_discordance(0.5, kappa)
    assert band_cases.expected_discordance(0.0, kappa) == 0.0
    assert band_cases.expected_discordance(1.0, kappa) == 0.0
    for p in (0.1, 0.3, 0.7, 0.9):
        assert band_cases.expected_discordance(p, kappa) < peak
    # Symmetric about 0.5: too easy and too hard waste power equally.
    assert band_cases.expected_discordance(0.2, kappa) == pytest.approx(
        band_cases.expected_discordance(0.8, kappa)
    )


def test_cases_needed_is_infinite_without_discordance() -> None:
    assert math.isinf(band_cases.cases_needed(0.0, 0.65))
    assert band_cases.cases_needed(0.2, 0.65) == pytest.approx(
        band_cases.discordant_pairs_needed(0.65) / 0.2
    )


# --- loading ----------------------------------------------------------------


def test_load_cases_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text('{"sample_id": "a"}\n\n   \n{"sample_id": "b"}\n', encoding="utf-8")
    assert [c["sample_id"] for c in band_cases.load_cases(path)] == ["a", "b"]


def test_band_of_defaults_missing_values_to_unknown() -> None:
    assert band_cases.band_of({}, "difficulty_score") == "unknown"
    assert band_cases.band_of(None, "difficulty_score") == "unknown"  # type: ignore[arg-type]
    assert band_cases.band_of({"difficulty_score": 2}, "difficulty_score") == 2


def test_load_probe_tallies_only_task_outcomes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "report.json"
    _write_report(
        report,
        [
            _sample("a", 1, "PASS"),
            _sample("b", 1, "fail"),
            _sample("c", 2, "pass"),
            _sample("d", 2, "error"),
            {"grade": None, "sample": None},
        ],
    )
    assert band_cases.load_probe(report, "difficulty_score") == {1: (1, 2), 2: (1, 1)}
    assert "excluded 2 non-pass/fail samples" in capsys.readouterr().out


def test_load_probe_rejects_a_non_report(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"rows": []}), encoding="utf-8")
    with pytest.raises(SystemExit, match="no `samples` list"):
        band_cases.load_probe(report, "difficulty_score")


# --- analysis and selection -------------------------------------------------


def test_summarise_orders_by_discordance_and_flags_small_bands() -> None:
    rows = band_cases.summarise(
        {"easy": (19, 20), "mid": (10, 20), "tiny": (1, 2)}, 0.49, 15
    )
    assert [r["band"] for r in rows][0] == "mid"
    discordances = [r["discordance"] for r in rows]
    assert discordances == sorted(discordances, reverse=True)
    by_band = {r["band"]: r for r in rows}
    assert by_band["tiny"]["reliable"] is False
    assert by_band["mid"]["reliable"] is True
    # Planning uses the worst case across the CI, never more than the point estimate.
    for r in rows:
        assert r["discordance_worst"] <= r["discordance"] + 1e-12


def test_summarise_handles_an_empty_band() -> None:
    (row,) = band_cases.summarise({"empty": (0, 0)}, 0.49, 1)
    assert row["pass_rate"] == 0.0
    assert row["reliable"] is False


def test_select_fills_from_best_reliable_bands_and_skips_exclusions() -> None:
    cases = [_case(f"m{i}", "mid") for i in range(3)] + [
        _case(f"e{i}", "easy") for i in range(3)
    ]
    cases.append(_case("u0", "unreliable"))
    rows = [
        {"band": "unreliable", "reliable": False, "pass_rate": 0.5, "discordance": 0.3},
        {"band": "mid", "reliable": True, "pass_rate": 0.5, "discordance": 0.2},
        {"band": "missing", "reliable": True, "pass_rate": 0.5, "discordance": 0.15},
        {"band": "easy", "reliable": True, "pass_rate": 0.9, "discordance": 0.1},
    ]
    chosen, used = band_cases.select(cases, rows, "difficulty_score", 4, {"m0"})
    assert [c["sample_id"] for c in chosen] == ["m1", "m2", "e0", "e1"]
    assert [u[:2] for u in used] == [("mid", 2), ("easy", 2)]


def test_select_stops_once_target_is_met() -> None:
    cases = [_case("a", "x"), _case("b", "y")]
    rows = [
        {"band": "x", "reliable": True, "pass_rate": 0.5, "discordance": 0.2},
        {"band": "y", "reliable": True, "pass_rate": 0.5, "discordance": 0.1},
    ]
    chosen, used = band_cases.select(cases, rows, "difficulty_score", 1, set())
    assert [c["sample_id"] for c in chosen] == ["a"]
    assert len(used) == 1


def test_emit_probe_stratifies_and_tops_up(tmp_path: Path) -> None:
    cases = [_case(f"a{i}", 1) for i in range(5)] + [_case("b0", 2)]
    out = tmp_path / "probe" / "probe.jsonl"
    assert band_cases.emit_probe(cases, "difficulty_score", 4, out) == 0
    written = band_cases.load_cases(out)
    assert len(written) == 4
    assert {c["sample_id"] for c in written} >= {"a0", "a1", "b0"}


# --- CLI -------------------------------------------------------------------


def test_main_emit_probe_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, [_case("a", 1), _case("b", 2)])
    out = tmp_path / "probe.jsonl"
    rc = _run_main(
        monkeypatch, "--cases", str(cases_path), "--emit-probe", "2", "--out", str(out)
    )
    assert rc == 0
    assert len(band_cases.load_cases(out)) == 2


def test_main_requires_a_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, [_case("a", 1)])
    with pytest.raises(SystemExit, match="--emit-probe N or --probe-report"):
        _run_main(monkeypatch, "--cases", str(cases_path), "--out", str(tmp_path / "o"))


def test_main_rejects_a_probe_without_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, [_case("a", 1)])
    report = tmp_path / "report.json"
    _write_report(report, [_sample("a", 1, "error")])
    with pytest.raises(SystemExit, match="no pass/fail samples"):
        _run_main(
            monkeypatch,
            "--cases",
            str(cases_path),
            "--probe-report",
            str(report),
            "--out",
            str(tmp_path / "o"),
        )


def _probe_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Band 1 measured at 50%, band 2 at 100%, band 3 too small to trust."""
    cases = [_case(f"c1-{i}", 1) for i in range(30)] + [
        _case(f"c2-{i}", 2) for i in range(30)
    ]
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, cases)
    samples = [_sample(f"c1-{i}", 1, "pass" if i % 2 else "fail") for i in range(4)]
    samples += [_sample(f"c2-{i}", 2, "pass") for i in range(4)]
    samples += [_sample("c3-0", 3, "pass")]
    report = tmp_path / "report.json"
    _write_report(report, samples)
    return cases_path, report


def test_main_selects_a_wave_and_reports_power(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cases_path, report = _probe_fixture(tmp_path)
    out = tmp_path / "wave.jsonl"
    rc = _run_main(
        monkeypatch,
        "--cases",
        str(cases_path),
        "--probe-report",
        str(report),
        "--min-probe-n",
        "2",
        "--target-n",
        "100",
        "--out",
        str(out),
    )
    assert rc == 0
    chosen = band_cases.load_cases(out)
    ids = {c["sample_id"] for c in chosen}
    # Probe instances are excluded by default; the unreliable band never contributes.
    assert not ids & {"c1-0", "c1-1", "c1-2", "c1-3", "c2-0"}
    assert all(c["metadata"]["difficulty_score"] in (1, 2) for c in chosen)
    text = capsys.readouterr().out
    assert "excluding 9 already-measured probe instances" in text
    assert "1 band(s) below --min-probe-n=2" in text
    assert "UNDERPOWERED" in text
    assert "NOTE: asked for 100" in text


def test_main_can_reuse_probe_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases_path, report = _probe_fixture(tmp_path)
    out = tmp_path / "wave.jsonl"
    _run_main(
        monkeypatch,
        "--cases",
        str(cases_path),
        "--probe-report",
        str(report),
        "--min-probe-n",
        "2",
        "--target-n",
        "5",
        "--reuse-probe-cases",
        "--out",
        str(out),
    )
    assert "c1-0" in {c["sample_id"] for c in band_cases.load_cases(out)}


def test_main_reports_powered_when_discordance_suffices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cases_path, report = _probe_fixture(tmp_path)
    # Pad band 1 so even the moderate effect is powered at kappa=1.
    extra = [_case(f"x{i}", 1) for i in range(2000)]
    _write_cases(cases_path, band_cases.load_cases(cases_path) + extra)
    _run_main(
        monkeypatch,
        "--cases",
        str(cases_path),
        "--probe-report",
        str(report),
        "--min-probe-n",
        "2",
        "--kappa",
        "1.0",
        "--target-n",
        "2000",
        "--out",
        str(tmp_path / "wave.jsonl"),
    )
    assert "-> POWERED" in capsys.readouterr().out


def test_main_fails_when_every_reliable_band_is_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_cases(cases_path, [_case("a", 1)])
    report = tmp_path / "report.json"
    _write_report(report, [_sample("a", 1, "pass"), _sample("a", 1, "fail")])
    with pytest.raises(SystemExit, match="no cases selected"):
        _run_main(
            monkeypatch,
            "--cases",
            str(cases_path),
            "--probe-report",
            str(report),
            "--min-probe-n",
            "1",
            "--out",
            str(tmp_path / "o"),
        )
