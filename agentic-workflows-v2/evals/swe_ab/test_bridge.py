"""Unit tests for bridge.py's cost-lane preflight.

Run from the kit under **ARP's** venv, not EvalKit's -- ``bridge.py`` imports
``agentic_v2``, which EvalKit is forbidden to do (ADR-0001), so this cannot
share a pytest run with ``test_run_ab.py``:

    ../../../.venv/Scripts/python.exe -m pytest test_bridge.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

KIT_ROOT = Path(__file__).resolve().parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

import bridge

#: Curated ``cost_lane: free`` in model_registry.yaml, verified twice on
#: 2026-09-07 by live completions returning ``usage.cost == 0``. Deliberately
#: not a minimax ":free" id: both of those went from serving at zero cost to
#: delisted within ninety minutes that same day, which is why this constant
#: names a model and not just any id the provider advertises as free.
CURATED_FREE = "openrouter:cohere/north-mini-code:free"

#: The campaign's own model. Ollama Cloud is metered (ollama.com/pricing), so
#: this is curated ``paid`` and the ceiling must refuse it -- the single most
#: important case here, because the whole campaign ran on it believing
#: otherwise.
CAMPAIGN_MODEL = "ollama:deepseek-v4-flash:0731-cloud"


def test_curated_free_model_passes_under_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_MAX_COST_LANE", "free")

    bridge._require_model_within_cost_lane(CURATED_FREE)  # must not raise


def test_uncurated_model_is_refused_before_the_run_starts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """cost_lane_for fails closed, so an uncurated id would be filtered out.

    The filter does not raise on its own -- the registry's local Ollama
    tail survives it -- so without this check the wave would run to
    completion on a different model and be rejected sample by sample
    afterwards.
    """
    monkeypatch.setenv("AGENTIC_MAX_COST_LANE", "free")

    with pytest.raises(SystemExit) as excinfo:
        bridge._require_model_within_cost_lane("ollama:not-curated:cloud")

    assert excinfo.value.code == 6
    message = capsys.readouterr().err
    assert "ollama:not-curated:cloud" in message
    assert "model_registry.yaml" in message


def test_paid_model_is_refused_under_a_free_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_MAX_COST_LANE", "free")

    with pytest.raises(SystemExit) as excinfo:
        bridge._require_model_within_cost_lane("anthropic:claude-haiku-4-5-20251001")

    assert excinfo.value.code == 6


def test_ollama_cloud_is_refused_because_it_is_metered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama Cloud bills per token; the ``-cloud`` suffix is not a free tier.

    This is the case the ceiling exists for and the one the campaign got
    wrong. It also cannot be caught by ``PAID_CREDENTIALS``: auth for this
    path lives in the local ollama daemon, not the environment, so blanking
    ``OLLAMA_API_KEY`` leaves it fully reachable.
    """
    monkeypatch.setenv("AGENTIC_MAX_COST_LANE", "free")

    with pytest.raises(SystemExit) as excinfo:
        bridge._require_model_within_cost_lane(CAMPAIGN_MODEL)

    assert excinfo.value.code == 6


def test_no_ceiling_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset must behave exactly as it did before the ceiling existed."""
    monkeypatch.delenv("AGENTIC_MAX_COST_LANE", raising=False)

    bridge._require_model_within_cost_lane("anthropic:claude-haiku-4-5-20251001")


def test_preflight_mode_refuses_without_reading_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit 6, not exit 1: an empty stdin would fail with 1 if it were read."""
    monkeypatch.setenv("AGENTIC_MAX_COST_LANE", "free")
    monkeypatch.setenv("AB_MODEL", CAMPAIGN_MODEL)
    monkeypatch.setattr(sys, "argv", ["bridge.py", bridge.PREFLIGHT_FLAG])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    with pytest.raises(SystemExit) as excinfo:
        bridge.main()

    assert excinfo.value.code == 6


def test_preflight_mode_passes_a_curated_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_MAX_COST_LANE", "free")
    monkeypatch.setenv("AB_MODEL", CURATED_FREE)
    monkeypatch.setattr(sys, "argv", ["bridge.py", bridge.PREFLIGHT_FLAG])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    assert bridge.main() == 0
