from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_v2.server.routes.model_finder import (
    SystemProfile,
    get_system_profile,
    score_model,
    sorted_candidates,
)


def _profile(ram_gb: float) -> SystemProfile:
    return SystemProfile(
        os="test",
        architecture="x86_64",
        cpu_name="Test CPU",
        cpu_cores_logical=8,
        cpu_max_mhz=3200,
        ram_gb=ram_gb,
        estimated_cinebench_r23_multi=15000,
        estimated_tokens_per_second_7b_q4=8.0,
        performance_tier="mainstream",
        notes=[],
    )


def test_sorted_candidates_defaults_to_downloads_then_metadata() -> None:
    models = sorted_candidates(_profile(32), "swe", "downloads")

    assert models[0].downloads >= models[1].downloads
    assert all("swe" in model.categories for model in models)


def test_fit_score_marks_underpowered_profile_as_not_runnable() -> None:
    model = sorted_candidates(_profile(4), "biomed", "downloads")[0]
    fit_score, runnable, reason = score_model(model, _profile(4))

    assert fit_score < 60
    assert runnable is False
    assert "below minimum" in reason


def test_fit_sort_promotes_best_local_fit() -> None:
    models = sorted_candidates(_profile(8), "all", "fit")

    assert models[0].fit_score >= models[-1].fit_score


class TestHardwareOverrideParsing:
    """Malformed hardware-override values must degrade, never crash the probe."""

    @pytest.fixture(autouse=True)
    def _fresh_profile_cache(self):
        """get_system_profile is lru_cache(maxsize=1)-d; isolate every test."""
        get_system_profile.cache_clear()
        yield
        get_system_profile.cache_clear()

    @staticmethod
    def _install_override(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
    ) -> None:
        override = tmp_path / "hardware_override.yaml"
        override.write_text(body, encoding="utf-8")
        monkeypatch.setenv("HARDWARE_OVERRIDE_PATH", str(override))

    def test_malformed_system_tops_falls_back_to_accelerator_total(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._install_override(
            tmp_path,
            monkeypatch,
            """
cpu_cores_logical: 8
ram_gb: 32
accelerators:
  - kind: gpu
    name: Test GPU
    tops: 40
    memory_gb: 16
system_tops: not-a-number
""",
        )

        profile = get_system_profile()

        # ValueError path: the unparseable override is ignored and the
        # computed accelerator total wins.
        assert profile.system_tops == 40.0

    def test_mapping_system_tops_without_accelerators_yields_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A YAML mapping raises TypeError in float(); with no accelerators
        # (explicit empty list keeps the test off the live hardware probes)
        # there is no computed total either, so the field stays None.
        self._install_override(
            tmp_path,
            monkeypatch,
            """
cpu_cores_logical: 8
ram_gb: 32
accelerators: []
system_tops:
  nested: true
""",
        )

        profile = get_system_profile()

        assert profile.system_tops is None

    def test_numeric_string_system_tops_is_honored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._install_override(
            tmp_path,
            monkeypatch,
            """
cpu_cores_logical: 8
ram_gb: 32
accelerators: []
system_tops: "45.5"
""",
        )

        profile = get_system_profile()

        assert profile.system_tops == 45.5

    def test_recommendations_route_degrades_on_malformed_override(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The route serves recommendations instead of 500ing on bad config."""
        self._install_override(
            tmp_path,
            monkeypatch,
            """
cpu_cores_logical: 8
ram_gb: 32
accelerators: []
system_tops: definitely-not-a-number
""",
        )

        response = client.get("/api/model-finder/recommendations")

        assert response.status_code == 200
        payload = response.json()
        assert payload["profile"]["system_tops"] is None
        assert payload["models"]
