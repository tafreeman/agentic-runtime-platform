from agentic_v2.server.routes.model_finder import (
    SystemProfile,
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
