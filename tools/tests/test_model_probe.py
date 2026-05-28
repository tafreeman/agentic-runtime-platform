"""Tests for model_probe -- ModelProbe class, provider detection, caching, and
convenience functions.

Covers:
- Provider detection from model name strings (get_provider)
- ModelProbe initialization with/without cache
- Cache validity checking (TTL-based)
- check_model with session cache, persistent cache, and fresh probes
- filter_runnable filtering logic
- get_probe_report structure
- clear_cache for single model and all models
- get_cache_summary statistics
- Convenience functions: is_model_usable, filter_usable_models, get_model_error
- Singleton get_probe behavior
- ProbeResult dataclass
- Cache key generation
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tools.core.errors import ErrorCode
from tools.llm.model_probe import (
    ModelProbe,
    filter_usable_models,
    get_model_error,
    get_probe,
    is_model_usable,
)
from tools.llm.probe_config import CACHE_VERSION, ProbeResult, cache_key
from tools.llm.probe_providers import get_provider

# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------


class TestGetProvider:
    """Tests for provider detection from model identifier strings."""

    @pytest.mark.parametrize(
        "model,expected",
        [
            ("local:phi4", "local"),
            ("gh:openai/gpt-4o-mini", "github"),
            ("github:openai/gpt-4o", "github"),
            ("openai:gpt-4o", "openai"),
            ("gpt-4o", "openai"),
            ("azure-foundry:default", "azure_foundry"),
            ("azure-openai:default", "azure_openai"),
            ("ollama:llama3", "ollama"),
            ("gemini:gemini-2.0-flash", "gemini"),
            ("claude:claude-3-opus", "claude"),
            ("aitk:phi4", "ai_toolkit"),
            ("ai-toolkit:phi4", "ai_toolkit"),
            ("windows-ai:phi-silica", "windows_ai"),
            ("lmstudio:model", "lmstudio"),
            ("lm-studio:model", "lmstudio"),
            ("local-api:model", "local_api"),
        ],
    )
    def test_known_providers(self, model: str, expected: str):
        """Each known prefix maps to the correct provider name."""
        assert get_provider(model) == expected

    def test_unknown_provider_returns_unknown(self):
        """Unrecognized model strings return 'unknown'."""
        assert get_provider("foobar:model") == "unknown"

    def test_empty_string_returns_unknown(self):
        """Empty string returns 'unknown'."""
        assert get_provider("") == "unknown"


# ---------------------------------------------------------------------------
# ProbeResult
# ---------------------------------------------------------------------------


class TestProbeResult:
    """Tests for the ProbeResult dataclass."""

    def test_to_dict_round_trip(self):
        """to_dict produces a complete dict with all fields."""
        result = ProbeResult(
            model="gh:gpt-4o-mini",
            provider="github",
            usable=True,
            probe_time=datetime.now().isoformat(),
        )
        d = result.to_dict()
        assert d["model"] == "gh:gpt-4o-mini"
        assert d["usable"] is True
        assert d["provider"] == "github"

    def test_default_values(self):
        """Default fields have expected values."""
        result = ProbeResult(model="test", provider="test", usable=False)
        assert result.error_code is None
        assert result.cached is False
        assert result.should_retry is False
        assert result.duration_ms == 0


# ---------------------------------------------------------------------------
# cache_key
# ---------------------------------------------------------------------------


class TestCacheKey:
    """Tests for cache key generation."""

    def test_deterministic(self):
        """Same model string always produces the same cache key."""
        k1 = cache_key("gh:gpt-4o-mini")
        k2 = cache_key("gh:gpt-4o-mini")
        assert k1 == k2

    def test_different_models_different_keys(self):
        """Different model strings produce different cache keys."""
        k1 = cache_key("gh:gpt-4o-mini")
        k2 = cache_key("gh:gpt-4o")
        assert k1 != k2

    def test_key_is_string(self):
        """Cache key is a hex string."""
        k = cache_key("test:model")
        assert isinstance(k, str)
        assert len(k) == 12  # CACHE_KEY_MD5_LENGTH


# ---------------------------------------------------------------------------
# ModelProbe
# ---------------------------------------------------------------------------


class TestModelProbe:
    """Tests for the ModelProbe class."""

    def _make_probe(self, **kwargs) -> ModelProbe:
        """Create a ModelProbe with cache disabled to avoid disk I/O."""
        kwargs.setdefault("use_cache", False)
        return ModelProbe(**kwargs)

    def test_init_no_cache(self):
        """ModelProbe initializes with empty cache when use_cache=False."""
        probe = self._make_probe()
        assert probe.use_cache is False
        assert probe._cache["version"] == CACHE_VERSION

    @patch("tools.llm.model_probe.load_cache")
    def test_init_with_cache(self, mock_load):
        """ModelProbe loads persistent cache when use_cache=True."""
        mock_load.return_value = {"version": CACHE_VERSION, "probes": {"k": {}}}
        ModelProbe(use_cache=True)
        mock_load.assert_called_once()

    def test_cache_key_delegates(self):
        """_cache_key method delegates to the module-level cache_key function."""
        probe = self._make_probe()
        assert probe._cache_key("gh:gpt-4o") == cache_key("gh:gpt-4o")

    def test_get_provider_delegates(self):
        """_get_provider method delegates to get_provider."""
        probe = self._make_probe()
        assert probe._get_provider("gh:model") == "github"


class TestModelProbeCacheValidity:
    """Tests for cache TTL-based validity checking."""

    def _make_probe(self) -> ModelProbe:
        return ModelProbe(use_cache=False)

    def test_no_probe_time_is_invalid(self):
        """Cached entry without probe_time is invalid."""
        probe = self._make_probe()
        assert probe._is_cache_valid({}) is False

    def test_success_within_ttl(self):
        """Successful probe within 1 hour is valid."""
        probe = self._make_probe()
        cached = {
            "probe_time": datetime.now().isoformat(),
            "error_code": None,
        }
        assert probe._is_cache_valid(cached) is True

    def test_success_expired(self):
        """Successful probe older than 1 hour is invalid."""
        probe = self._make_probe()
        cached = {
            "probe_time": (datetime.now() - timedelta(hours=2)).isoformat(),
            "error_code": None,
        }
        assert probe._is_cache_valid(cached) is False

    def test_permanent_error_within_ttl(self):
        """Permanent error within 24 hours is still valid."""
        probe = self._make_probe()
        cached = {
            "probe_time": (datetime.now() - timedelta(hours=12)).isoformat(),
            "error_code": ErrorCode.PERMISSION_DENIED.value,
        }
        assert probe._is_cache_valid(cached) is True

    def test_permanent_error_expired(self):
        """Permanent error older than 24 hours is invalid."""
        probe = self._make_probe()
        cached = {
            "probe_time": (datetime.now() - timedelta(hours=25)).isoformat(),
            "error_code": ErrorCode.PERMISSION_DENIED.value,
        }
        assert probe._is_cache_valid(cached) is False

    def test_transient_error_within_ttl(self):
        """Transient error within 5 minutes is valid."""
        probe = self._make_probe()
        cached = {
            "probe_time": (datetime.now() - timedelta(minutes=3)).isoformat(),
            "error_code": ErrorCode.RATE_LIMITED.value,
        }
        assert probe._is_cache_valid(cached) is True

    def test_transient_error_expired(self):
        """Transient error older than 5 minutes is invalid."""
        probe = self._make_probe()
        cached = {
            "probe_time": (datetime.now() - timedelta(minutes=10)).isoformat(),
            "error_code": ErrorCode.RATE_LIMITED.value,
        }
        assert probe._is_cache_valid(cached) is False

    def test_bad_probe_time_is_invalid(self):
        """Malformed probe_time is treated as invalid."""
        probe = self._make_probe()
        cached = {"probe_time": "not-a-date"}
        assert probe._is_cache_valid(cached) is False


class TestModelProbeCheckModel:
    """Tests for check_model method."""

    def _usable_result(self, model: str = "gh:gpt-4o-mini") -> ProbeResult:
        return ProbeResult(
            model=model,
            provider="github",
            usable=True,
            probe_time=datetime.now().isoformat(),
        )

    def _unusable_result(self, model: str = "gh:gpt-4o-mini") -> ProbeResult:
        return ProbeResult(
            model=model,
            provider="github",
            usable=False,
            error_code=ErrorCode.UNAVAILABLE_MODEL.value,
            error_message="Model not found",
            probe_time=datetime.now().isoformat(),
        )

    @patch("tools.llm.model_probe.probe_model")
    def test_fresh_probe(self, mock_probe):
        """When no cache, probe is called and result cached in session."""
        mock_probe.return_value = self._usable_result()
        probe = ModelProbe(use_cache=False)
        result = probe.check_model("gh:gpt-4o-mini")
        assert result.usable is True
        mock_probe.assert_called_once()

    @patch("tools.llm.model_probe.probe_model")
    def test_session_cache_hit(self, mock_probe):
        """Second call for same model uses session cache."""
        mock_probe.return_value = self._usable_result()
        probe = ModelProbe(use_cache=False)
        probe.check_model("gh:gpt-4o-mini")
        result2 = probe.check_model("gh:gpt-4o-mini")
        assert result2.cached is True
        assert mock_probe.call_count == 1  # Only one actual probe

    @patch("tools.llm.model_probe.probe_model")
    def test_force_probe_bypasses_cache(self, mock_probe):
        """force_probe=True skips session and persistent caches."""
        mock_probe.return_value = self._usable_result()
        probe = ModelProbe(use_cache=False)
        probe.check_model("gh:gpt-4o-mini")
        probe.check_model("gh:gpt-4o-mini", force_probe=True)
        assert mock_probe.call_count == 2


class TestModelProbeFilterRunnable:
    """Tests for filter_runnable method."""

    @patch("tools.llm.model_probe.probe_model")
    def test_filters_unusable_models(self, mock_probe):
        """filter_runnable removes models that probe as unusable."""

        def side_effect(model, log=None):
            if model == "gh:gpt-4o-mini":
                return ProbeResult(
                    model=model,
                    provider="github",
                    usable=True,
                    probe_time=datetime.now().isoformat(),
                )
            return ProbeResult(
                model=model,
                provider="local",
                usable=False,
                error_code=ErrorCode.UNAVAILABLE_MODEL.value,
                probe_time=datetime.now().isoformat(),
            )

        mock_probe.side_effect = side_effect
        probe = ModelProbe(use_cache=False)
        result = probe.filter_runnable(["gh:gpt-4o-mini", "local:missing"])
        assert result == ["gh:gpt-4o-mini"]

    @patch("tools.llm.model_probe.probe_model")
    def test_empty_list_returns_empty(self, mock_probe):
        """Empty input list returns empty output."""
        probe = ModelProbe(use_cache=False)
        assert probe.filter_runnable([]) == []


class TestModelProbeGetProbeReport:
    """Tests for get_probe_report method."""

    @patch("tools.llm.model_probe.probe_model")
    def test_report_structure(self, mock_probe):
        """Report contains expected keys and correct counts."""
        mock_probe.return_value = ProbeResult(
            model="gh:gpt-4o-mini",
            provider="github",
            usable=True,
            probe_time=datetime.now().isoformat(),
        )
        probe = ModelProbe(use_cache=False)
        report = probe.get_probe_report(["gh:gpt-4o-mini"])

        assert report["total"] == 1
        assert report["usable_count"] == 1
        assert report["unusable_count"] == 0
        assert "gh:gpt-4o-mini" in report["usable"]
        assert "details" in report
        assert "timestamp" in report


class TestModelProbeClearCache:
    """Tests for clear_cache method."""

    @patch("tools.llm.model_probe.probe_model")
    def test_clear_single_model(self, mock_probe):
        """Clearing cache for one model removes it from session cache."""
        mock_probe.return_value = ProbeResult(
            model="gh:gpt-4o-mini",
            provider="github",
            usable=True,
            probe_time=datetime.now().isoformat(),
        )
        probe = ModelProbe(use_cache=False)
        probe.check_model("gh:gpt-4o-mini")
        probe.clear_cache("gh:gpt-4o-mini")
        # Next call should probe again
        probe.check_model("gh:gpt-4o-mini")
        assert mock_probe.call_count == 2

    @patch("tools.llm.model_probe.probe_model")
    def test_clear_all(self, mock_probe):
        """Clearing all cache empties session probes."""
        mock_probe.return_value = ProbeResult(
            model="test",
            provider="test",
            usable=True,
            probe_time=datetime.now().isoformat(),
        )
        probe = ModelProbe(use_cache=False)
        probe.check_model("gh:gpt-4o-mini")
        probe.clear_cache()
        assert len(probe._session_probes) == 0


class TestModelProbeGetCacheSummary:
    """Tests for get_cache_summary method."""

    def test_empty_cache_summary(self):
        """Empty cache produces zeroed summary."""
        probe = ModelProbe(use_cache=False)
        summary = probe.get_cache_summary()
        assert summary["total_entries"] == 0
        assert summary["valid_entries"] == 0
        assert summary["expired_entries"] == 0


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @patch("tools.llm.model_probe._DEFAULT_PROBE", None)
    @patch("tools.llm.model_probe.load_cache")
    @patch("tools.llm.model_probe.probe_model")
    def test_is_model_usable(self, mock_probe, mock_cache):
        """is_model_usable returns bool based on probe result."""
        mock_cache.return_value = {"version": CACHE_VERSION, "probes": {}}
        mock_probe.return_value = ProbeResult(
            model="test",
            provider="test",
            usable=True,
            probe_time=datetime.now().isoformat(),
        )
        # Reset singleton for test isolation
        import tools.llm.model_probe as mod

        mod._DEFAULT_PROBE = None
        assert is_model_usable("test") is True

    @patch("tools.llm.model_probe._DEFAULT_PROBE", None)
    @patch("tools.llm.model_probe.load_cache")
    @patch("tools.llm.model_probe.probe_model")
    def test_get_model_error_usable(self, mock_probe, mock_cache):
        """get_model_error returns None for usable models."""
        mock_cache.return_value = {"version": CACHE_VERSION, "probes": {}}
        mock_probe.return_value = ProbeResult(
            model="test",
            provider="test",
            usable=True,
            probe_time=datetime.now().isoformat(),
        )
        import tools.llm.model_probe as mod

        mod._DEFAULT_PROBE = None
        assert get_model_error("test") is None


# ---------------------------------------------------------------------------
# get_probe singleton
# ---------------------------------------------------------------------------


class TestGetProbe:
    """Tests for the singleton get_probe function."""

    def test_returns_same_instance(self):
        """get_probe returns the same instance on repeated calls."""
        import tools.llm.model_probe as mod

        mod._DEFAULT_PROBE = None  # Reset

        with patch("tools.llm.model_probe.load_cache") as mock_cache:
            mock_cache.return_value = {"version": CACHE_VERSION, "probes": {}}
            p1 = get_probe()
            p2 = get_probe()
            assert p1 is p2

        mod._DEFAULT_PROBE = None  # Cleanup
