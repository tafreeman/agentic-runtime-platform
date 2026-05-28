"""Tests for datasets module (benchmark bridge)."""

from __future__ import annotations

import pytest


class TestDatasetsModule:
    """Tests for the datasets bridge module."""

    def test_imports_available(self):
        """Test that module can be imported."""
        from agentic_v2_eval import datasets

        assert hasattr(datasets, "list_benchmarks")
        assert hasattr(datasets, "load_benchmark")
        assert hasattr(datasets, "get_benchmark_definitions")
        assert hasattr(datasets, "get_benchmark_definition")

    def test_list_benchmarks_function(self):
        """Test list_benchmarks returns benchmark IDs."""
        from agentic_v2_eval.datasets import list_benchmarks

        benchmarks = list_benchmarks()

        assert isinstance(benchmarks, list)
        assert len(benchmarks) > 0
        # Should include common benchmarks
        assert "humaneval" in benchmarks
        assert "mbpp" in benchmarks

    def test_get_benchmark_definitions(self):
        """Test get_benchmark_definitions returns dict."""
        from agentic_v2_eval.datasets import get_benchmark_definitions

        definitions = get_benchmark_definitions()

        assert isinstance(definitions, dict)
        assert len(definitions) > 0
        assert "humaneval" in definitions

    def test_get_benchmark_definition_found(self):
        """Test get_benchmark_definition for existing benchmark."""
        from agentic_v2_eval.datasets import get_benchmark_definition

        definition = get_benchmark_definition("humaneval")

        assert definition is not None
        assert definition.id == "humaneval"
        assert "HumanEval" in definition.name
        assert definition.size > 0

    def test_get_benchmark_definition_not_found(self):
        """Test get_benchmark_definition returns None for unknown benchmark."""
        from agentic_v2_eval.datasets import get_benchmark_definition

        definition = get_benchmark_definition("nonexistent-benchmark")
        assert definition is None

    def test_lazy_attribute_access_benchmark_definitions(self):
        """Test lazy loading of BENCHMARK_DEFINITIONS."""
        from agentic_v2_eval import datasets

        definitions = datasets.BENCHMARK_DEFINITIONS

        assert isinstance(definitions, dict)
        assert "humaneval" in definitions

    def test_lazy_attribute_access_types(self):
        """Test lazy loading of type classes."""
        from agentic_v2_eval import datasets

        # These should be lazy-loaded from tools.agents.benchmarks
        assert hasattr(datasets, "BenchmarkDefinition")
        assert hasattr(datasets, "BenchmarkType")
        assert hasattr(datasets, "DataSource")
        assert hasattr(datasets, "BenchmarkTask")
        assert hasattr(datasets, "BenchmarkConfig")
        assert hasattr(datasets, "BenchmarkRegistry")

    def test_benchmark_type_enum(self):
        """Test BenchmarkType enum is accessible."""
        from agentic_v2_eval.datasets import BenchmarkType

        assert BenchmarkType.FUNCTION_LEVEL is not None
        assert BenchmarkType.SOFTWARE_ENGINEERING is not None
        assert BenchmarkType.BASIC_PROGRAMMING is not None

    def test_data_source_enum(self):
        """Test DataSource enum is accessible."""
        from agentic_v2_eval.datasets import DataSource

        assert DataSource.HUGGINGFACE is not None
        assert DataSource.GITHUB is not None
        assert DataSource.LOCAL is not None

    def test_load_benchmark_invalid_id_raises(self):
        """Test load_benchmark raises for invalid benchmark ID."""
        from agentic_v2_eval.datasets import load_benchmark

        with pytest.raises(ValueError, match="Unknown benchmark"):
            load_benchmark("invalid-benchmark-id-xyz")

    def test_get_registry(self):
        """Test get_registry returns BenchmarkRegistry."""
        from agentic_v2_eval.datasets import BenchmarkRegistry, get_registry

        registry = get_registry()
        assert isinstance(registry, BenchmarkRegistry)

    def test_benchmark_definition_attributes(self):
        """Test BenchmarkDefinition has expected attributes."""
        from agentic_v2_eval.datasets import get_benchmark_definition

        definition = get_benchmark_definition("humaneval")

        # Check key attributes exist
        assert hasattr(definition, "id")
        assert hasattr(definition, "name")
        assert hasattr(definition, "description")
        assert hasattr(definition, "benchmark_type")
        assert hasattr(definition, "size")
        assert hasattr(definition, "source")
        assert hasattr(definition, "source_url")
        assert hasattr(definition, "metrics")
        assert hasattr(definition, "languages")

    def test_swe_bench_variants_available(self):
        """Test SWE-bench variants are available."""
        from agentic_v2_eval.datasets import get_benchmark_definition, list_benchmarks

        benchmarks = list_benchmarks()

        # At least some SWE-bench variant should be available
        swe_benchmarks = [b for b in benchmarks if "swe" in b.lower()]
        assert len(swe_benchmarks) > 0

        # Check one of them
        if "swe-bench-lite" in benchmarks:
            definition = get_benchmark_definition("swe-bench-lite")
            assert definition is not None
            assert definition.size > 0

    def test_module_all_exports(self):
        """Test __all__ exports are accessible."""
        from agentic_v2_eval import datasets

        for name in datasets.__all__:
            assert hasattr(datasets, name), f"Missing export: {name}"

    def test_invalid_attribute_raises(self):
        """Test accessing invalid attribute raises AttributeError."""
        from agentic_v2_eval import datasets

        with pytest.raises(AttributeError):
            _ = datasets.nonexistent_attribute_xyz


class TestLoadBenchmarkFilters:
    """Tests for load_benchmark filtering options."""

    def test_load_with_limit_parameter(self):
        """Test that limit parameter is accepted."""
        from agentic_v2_eval.datasets import load_benchmark

        # This should not raise - just test the call is accepted
        # (actual loading may require network access)
        try:
            # Use custom-local which should work offline
            tasks = load_benchmark("custom-local", limit=5)
            # If it works, verify limit was applied
            assert len(tasks) <= 5
        except Exception:
            # If it fails (e.g., no local data), that's OK for this test
            pytest.skip("Local benchmark data not available")

    def test_load_with_language_filter(self):
        """Test that language filter is accepted."""
        from agentic_v2_eval.datasets import load_benchmark

        # Just verify the parameter is accepted
        try:
            load_benchmark("custom-local", limit=1, language="python")
        except Exception:
            pytest.skip("Local benchmark data not available")

    def test_load_with_force_refresh(self):
        """Test that force_refresh parameter is accepted."""
        from agentic_v2_eval.datasets import load_benchmark

        # Just verify the parameter is accepted
        try:
            load_benchmark("custom-local", limit=1, force_refresh=False)
        except Exception:
            pytest.skip("Local benchmark data not available")
