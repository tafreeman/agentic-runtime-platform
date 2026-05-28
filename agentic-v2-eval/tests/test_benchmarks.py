"""Tests for benchmark datasets, loader, and registry.

These tests cover the benchmark infrastructure in
tools/agents/benchmarks/ to ensure reliable dataset loading for workflow
evaluations.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add tools to path for imports
sys.path.insert(0, str(Path(__file__).parents[2]))

from tools.agents.benchmarks.datasets import (
    BENCHMARK_DEFINITIONS,
    BenchmarkType,
    DataSource,
    get_benchmark,
    list_benchmarks,
)
from tools.agents.benchmarks.loader import (
    BenchmarkTask,
    get_cache_key,
    is_cache_valid,
    load_from_cache,
    save_to_cache,
)
from tools.agents.benchmarks.registry import (
    PRESET_CONFIGS,
    BenchmarkConfig,
    BenchmarkRegistry,
)

# =============================================================================
# DATASET DEFINITION TESTS
# =============================================================================


class TestBenchmarkDefinitions:
    """Tests for benchmark dataset definitions."""

    def test_all_benchmarks_have_required_fields(self):
        """Every benchmark must have id, name, source, etc."""
        for bid, bdef in BENCHMARK_DEFINITIONS.items():
            assert bdef.id == bid, f"{bid}: id mismatch"
            assert bdef.name, f"{bid}: missing name"
            assert bdef.description, f"{bid}: missing description"
            assert isinstance(bdef.benchmark_type, BenchmarkType)
            assert isinstance(bdef.source, DataSource)
            assert bdef.size > 0, f"{bid}: size must be positive"

    def test_swe_bench_exists(self):
        """SWE-bench should be defined."""
        assert "swe-bench" in BENCHMARK_DEFINITIONS
        swe = BENCHMARK_DEFINITIONS["swe-bench"]
        assert swe.benchmark_type == BenchmarkType.SOFTWARE_ENGINEERING
        assert swe.source == DataSource.HUGGINGFACE

    def test_humaneval_exists(self):
        """HumanEval should be defined."""
        assert "humaneval" in BENCHMARK_DEFINITIONS
        he = BENCHMARK_DEFINITIONS["humaneval"]
        assert he.benchmark_type == BenchmarkType.FUNCTION_LEVEL
        assert "python" in he.languages

    def test_mbpp_exists(self):
        """MBPP should be defined."""
        assert "mbpp" in BENCHMARK_DEFINITIONS
        mbpp = BENCHMARK_DEFINITIONS["mbpp"]
        assert mbpp.benchmark_type == BenchmarkType.BASIC_PROGRAMMING

    def test_custom_local_exists(self):
        """Custom local benchmark should be defined."""
        assert "custom-local" in BENCHMARK_DEFINITIONS
        custom = BENCHMARK_DEFINITIONS["custom-local"]
        assert custom.source == DataSource.LOCAL

    def test_get_benchmark(self):
        """get_benchmark should return definition or None."""
        assert get_benchmark("humaneval") is not None
        assert get_benchmark("nonexistent") is None

    def test_list_benchmarks_no_filter(self):
        """list_benchmarks with no filter returns all."""
        all_benchmarks = list_benchmarks()
        assert len(all_benchmarks) >= 5  # At least our core benchmarks

    def test_list_benchmarks_by_type(self):
        """list_benchmarks filters by type."""
        swe_benchmarks = list_benchmarks(
            benchmark_type=BenchmarkType.SOFTWARE_ENGINEERING
        )
        assert all(
            b.benchmark_type == BenchmarkType.SOFTWARE_ENGINEERING
            for b in swe_benchmarks.values()
        )

    def test_list_benchmarks_by_language(self):
        """list_benchmarks filters by language."""
        python_benchmarks = list_benchmarks(language="python")
        assert all("python" in b.languages for b in python_benchmarks.values())


# =============================================================================
# BENCHMARK TASK TESTS
# =============================================================================


class TestBenchmarkTask:
    """Tests for BenchmarkTask dataclass."""

    def test_minimal_task(self):
        """Task with only required fields."""
        task = BenchmarkTask(
            task_id="test-1",
            benchmark_id="custom",
            prompt="Write a function",
        )
        assert task.task_id == "test-1"
        assert task.language == "python"  # default

    def test_full_task(self):
        """Task with all fields populated."""
        task = BenchmarkTask(
            task_id="swe-123",
            benchmark_id="swe-bench",
            prompt="Fix the bug",
            instruction="Modify the repository",
            repo="django/django",
            base_commit="abc123",
            issue_text="Error occurs when...",
            hints="Check the views.py",
            golden_patch="diff --git a/...",
            test_cases=[{"test_patch": "..."}],
            difficulty="medium",
            tags=["django", "orm"],
            language="python",
        )
        assert task.repo == "django/django"
        assert "django" in task.tags

    def test_to_dict(self):
        """to_dict should serialize task."""
        task = BenchmarkTask(
            task_id="test-1",
            benchmark_id="custom",
            prompt="Test prompt",
        )
        d = task.to_dict()
        assert d["task_id"] == "test-1"
        assert "prompt" in d


# =============================================================================
# CACHE TESTS
# =============================================================================


class TestCacheManagement:
    """Tests for benchmark caching."""

    def test_get_cache_key_deterministic(self):
        """Same inputs produce same key."""
        key1 = get_cache_key("humaneval")
        key2 = get_cache_key("humaneval")
        assert key1 == key2

    def test_get_cache_key_different_benchmarks(self):
        """Different benchmarks get different keys."""
        key1 = get_cache_key("humaneval")
        key2 = get_cache_key("mbpp")
        assert key1 != key2

    def test_get_cache_key_with_task_id(self):
        """Task ID changes the key."""
        key1 = get_cache_key("humaneval")
        key2 = get_cache_key("humaneval", "task-1")
        assert key1 != key2

    def test_save_and_load_cache(self, tmp_path: Path, monkeypatch):
        """Save and load roundtrip."""
        # Monkeypatch CACHE_DIR
        import tools.agents.benchmarks.loader as loader_module

        monkeypatch.setattr(loader_module, "CACHE_DIR", tmp_path)

        data = [{"task_id": "t1", "prompt": "test"}]
        save_to_cache(data, "test-bench")

        loaded = load_from_cache("test-bench")
        assert loaded == data

    def test_load_cache_missing(self, tmp_path: Path, monkeypatch):
        """load_from_cache returns None if missing."""
        import tools.agents.benchmarks.loader as loader_module

        monkeypatch.setattr(loader_module, "CACHE_DIR", tmp_path)

        result = load_from_cache("nonexistent")
        assert result is None

    def test_is_cache_valid_fresh(self, tmp_path: Path):
        """Fresh cache is valid."""
        cache_file = tmp_path / "test.json"
        cache_file.write_text("{}")
        assert is_cache_valid(cache_file, ttl_hours=1) is True

    def test_is_cache_valid_expired(self, tmp_path: Path):
        """Expired cache is invalid."""
        cache_file = tmp_path / "test.json"
        cache_file.write_text("{}")

        # Set mtime to 2 hours ago
        import os

        old_time = datetime.now() - timedelta(hours=2)
        os.utime(cache_file, (old_time.timestamp(), old_time.timestamp()))

        assert is_cache_valid(cache_file, ttl_hours=1) is False


# =============================================================================
# REGISTRY TESTS
# =============================================================================


class TestBenchmarkConfig:
    """Tests for BenchmarkConfig."""

    def test_default_config(self):
        """Default config has sensible values."""
        config = BenchmarkConfig()
        assert config.benchmark_id == "custom-local"
        assert config.model == "gh:gpt-4o-mini"
        assert config.timeout_seconds == 300

    def test_config_to_dict(self):
        """Config serializes to dict."""
        config = BenchmarkConfig(benchmark_id="humaneval", limit=10)
        d = config.to_dict()
        assert d["benchmark_id"] == "humaneval"
        assert d["limit"] == 10

    def test_config_from_dict(self):
        """Config deserializes from dict."""
        d = {"benchmark_id": "mbpp", "model": "local:phi4", "limit": 5}
        config = BenchmarkConfig.from_dict(d)
        assert config.benchmark_id == "mbpp"
        assert config.model == "local:phi4"
        assert config.limit == 5

    def test_config_save_load(self, tmp_path: Path):
        """Config saves and loads from file."""
        config = BenchmarkConfig(benchmark_id="humaneval", limit=20)
        config_path = tmp_path / "config.json"
        config.save(config_path)

        loaded = BenchmarkConfig.load(config_path)
        assert loaded.benchmark_id == "humaneval"
        assert loaded.limit == 20


class TestBenchmarkRegistry:
    """Tests for BenchmarkRegistry."""

    def test_list_benchmarks(self):
        """Registry can list benchmarks."""
        benchmarks = BenchmarkRegistry.list_benchmarks()
        assert "humaneval" in benchmarks
        assert "name" in benchmarks["humaneval"]

    def test_list_benchmarks_verbose(self):
        """Verbose listing includes extra fields."""
        benchmarks = BenchmarkRegistry.list_benchmarks(verbose=True)
        assert "paper_url" in benchmarks.get("humaneval", {})

    def test_get_benchmark_info(self):
        """get_benchmark_info returns definition."""
        info = BenchmarkRegistry.get_benchmark_info("swe-bench")
        assert info is not None
        assert info.name == "SWE-bench"

    def test_create_config(self):
        """create_config builds config."""
        config = BenchmarkRegistry.create_config(
            benchmark_id="humaneval",
            model="local:phi4",
            limit=10,
        )
        assert config.benchmark_id == "humaneval"
        assert config.model == "local:phi4"
        assert config.limit == 10

    def test_validate_config_valid(self):
        """Valid config has no errors."""
        config = BenchmarkConfig(benchmark_id="humaneval", model="gh:gpt-4o-mini")
        errors = BenchmarkRegistry.validate_config(config)
        assert len(errors) == 0

    def test_validate_config_bad_benchmark(self):
        """Invalid benchmark ID produces error."""
        config = BenchmarkConfig(benchmark_id="nonexistent", model="gh:gpt-4o-mini")
        errors = BenchmarkRegistry.validate_config(config)
        assert any("Unknown benchmark" in e for e in errors)

    def test_validate_config_bad_model(self):
        """Invalid model prefix produces error."""
        config = BenchmarkConfig(benchmark_id="humaneval", model="bad:model")
        errors = BenchmarkRegistry.validate_config(config)
        assert any("Model should start with" in e for e in errors)


class TestPresetConfigs:
    """Tests for preset configurations."""

    def test_quick_test_preset(self):
        """Quick-test preset exists and is valid."""
        assert "quick-test" in PRESET_CONFIGS
        config = PRESET_CONFIGS["quick-test"]
        assert config.limit is not None
        assert config.limit <= 10  # Should be quick

    def test_all_presets_valid(self):
        """All presets pass validation."""
        for name, config in PRESET_CONFIGS.items():
            errors = BenchmarkRegistry.validate_config(config)
            assert len(errors) == 0, f"Preset {name} has errors: {errors}"
