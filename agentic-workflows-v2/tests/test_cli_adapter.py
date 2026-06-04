"""Tests for CLI adapter-related commands.

Covers:
- ``agentic compare`` — run workflow through multiple adapters and compare.
- ``agentic rag ingest`` — ingest files into RAG pipeline.
- ``agentic rag search`` — search the RAG index.
- ``agentic list adapters`` — list registered adapters via CLI.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from agentic_v2.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Compare command
# ---------------------------------------------------------------------------


class TestCompareCommand:
    """Tests for the ``agentic compare`` CLI command."""

    def test_compare_help(self):
        """Compare command shows help text."""
        result = runner.invoke(app, ["compare", "--help"])
        assert result.exit_code == 0
        assert "compare" in result.stdout.lower()
        assert "adapters" in result.stdout.lower()

    def test_compare_requires_workflow_argument(self):
        """Compare fails without a workflow argument."""
        result = runner.invoke(app, ["compare"])
        # Typer returns exit code 2 for missing required argument
        assert result.exit_code == 2

    def test_compare_requires_input_file(self):
        """Compare fails without --input option."""
        result = runner.invoke(app, ["compare", "code_review"])
        # Should fail because --input is required
        assert result.exit_code != 0

    @patch("agentic_v2.cli.main.load_workflow_config")
    @patch("agentic_v2.cli.main._run_adapter")
    def test_compare_parses_comma_separated_adapters(
        self, mock_run_adapter, mock_load_config
    ):
        """Compare correctly parses comma-separated adapter names."""
        mock_load_config.return_value = MagicMock(
            name="test_workflow", description="Test"
        )
        mock_run_adapter.return_value = {
            "status": "success",
            "step_count": 3,
            "elapsed": 1.5,
        }

        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            input_path.write_text('{"key": "value"}')

            result = runner.invoke(
                app,
                [
                    "compare",
                    "test_workflow",
                    "--input",
                    str(input_path),
                    "--adapters",
                    "native,langchain",
                ],
            )
            assert result.exit_code == 0
            # Should have called _run_adapter twice (once per adapter)
            assert mock_run_adapter.call_count == 2

    @patch("agentic_v2.cli.main.load_workflow_config")
    @patch("agentic_v2.cli.main._run_adapter")
    def test_compare_prints_comparison_table(self, mock_run_adapter, mock_load_config):
        """Compare prints a comparison table with adapter results."""
        mock_load_config.return_value = MagicMock(
            name="test_workflow", description="Test"
        )
        mock_run_adapter.return_value = {
            "status": "success",
            "step_count": 3,
            "elapsed": 1.5,
        }

        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            input_path.write_text('{"key": "value"}')

            result = runner.invoke(
                app,
                [
                    "compare",
                    "test_workflow",
                    "--input",
                    str(input_path),
                ],
            )
            assert result.exit_code == 0
            # Table header columns should appear
            assert "Adapter" in result.stdout
            assert "Status" in result.stdout

    @patch("agentic_v2.cli.main.load_workflow_config")
    @patch("agentic_v2.cli.main._run_adapter")
    def test_compare_default_adapters(self, mock_run_adapter, mock_load_config):
        """Compare uses 'native,langchain' as default adapters."""
        mock_load_config.return_value = MagicMock(
            name="test_workflow", description="Test"
        )
        mock_run_adapter.return_value = {
            "status": "success",
            "step_count": 2,
            "elapsed": 0.8,
        }

        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            input_path.write_text('{"key": "value"}')

            result = runner.invoke(
                app,
                [
                    "compare",
                    "test_workflow",
                    "--input",
                    str(input_path),
                ],
            )
            assert result.exit_code == 0
            # Default is native,langchain — two adapters
            assert mock_run_adapter.call_count == 2
            # Both adapter names should appear in the call args
            call_adapter_names = [
                call.args[0] for call in mock_run_adapter.call_args_list
            ]
            assert "native" in call_adapter_names
            assert "langchain" in call_adapter_names

    @patch("agentic_v2.cli.main.load_workflow_config")
    @patch("agentic_v2.cli.main._run_adapter")
    def test_compare_handles_adapter_failure(self, mock_run_adapter, mock_load_config):
        """Compare reports failure status when an adapter raises."""
        mock_load_config.return_value = MagicMock(
            name="test_workflow", description="Test"
        )
        mock_run_adapter.side_effect = [
            {"status": "success", "step_count": 3, "elapsed": 1.0},
            {"status": "failed", "step_count": 0, "elapsed": 0.1},
        ]

        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            input_path.write_text('{"key": "value"}')

            result = runner.invoke(
                app,
                [
                    "compare",
                    "test_workflow",
                    "--input",
                    str(input_path),
                ],
            )
            assert result.exit_code == 0
            # Should still complete and show results for both
            assert (
                "success" in result.stdout.lower() or "failed" in result.stdout.lower()
            )

    def test_compare_nonexistent_input_file(self):
        """Compare fails when input file does not exist."""
        result = runner.invoke(
            app,
            [
                "compare",
                "test_workflow",
                "--input",
                "/nonexistent/path/input.json",
            ],
        )
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()


# ---------------------------------------------------------------------------
# RAG CLI subcommands
# ---------------------------------------------------------------------------


class TestRagCLI:
    """Tests for the ``agentic rag`` CLI subcommands."""

    def test_rag_ingest_help(self):
        """RAG ingest subcommand shows help."""
        result = runner.invoke(app, ["rag", "ingest", "--help"])
        assert result.exit_code == 0
        assert "source" in result.stdout.lower()

    def test_rag_search_help(self):
        """RAG search subcommand shows help."""
        result = runner.invoke(app, ["rag", "search", "--help"])
        assert result.exit_code == 0
        assert "query" in result.stdout.lower() or "top" in result.stdout.lower()

    @patch("agentic_v2.cli.main._rag_ingest_impl")
    def test_rag_ingest_reports_chunk_count(self, mock_ingest):
        """RAG ingest reports the number of chunks ingested."""
        mock_ingest.return_value = 5

        with TemporaryDirectory() as tmpdir:
            # Create a markdown file to ingest
            md_path = Path(tmpdir) / "test.md"
            md_path.write_text("# Test\n\nSome content for testing.")

            result = runner.invoke(
                app,
                ["rag", "ingest", "--source", str(md_path)],
            )
            assert result.exit_code == 0
            assert "5" in result.stdout
            assert "chunk" in result.stdout.lower()

    @patch("agentic_v2.cli.main._rag_search_impl")
    def test_rag_search_returns_results(self, mock_search):
        """RAG search returns and displays results."""
        mock_search.return_value = [
            {"content": "DAG executor uses Kahn's algorithm", "score": 0.95},
            {"content": "Pipeline executor runs steps sequentially", "score": 0.82},
        ]

        result = runner.invoke(
            app,
            ["rag", "search", "how does the DAG executor work?"],
        )
        assert result.exit_code == 0
        assert "Kahn" in result.stdout or "result" in result.stdout.lower()

    @patch("agentic_v2.cli.main._rag_search_impl")
    def test_rag_search_with_top_k(self, mock_search):
        """RAG search respects --top-k parameter."""
        mock_search.return_value = [
            {"content": "Result 1", "score": 0.9},
        ]

        result = runner.invoke(
            app,
            ["rag", "search", "query", "--top-k", "3"],
        )
        assert result.exit_code == 0
        # Verify top_k was passed through
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs[0][1] == 3  # top_k positional arg

    @patch("agentic_v2.cli.main._rag_search_impl")
    def test_rag_search_no_results(self, mock_search):
        """RAG search handles empty results gracefully."""
        mock_search.return_value = []

        result = runner.invoke(
            app,
            ["rag", "search", "nonexistent topic"],
        )
        assert result.exit_code == 0
        assert "no result" in result.stdout.lower() or "0" in result.stdout

    def test_rag_ingest_nonexistent_source(self):
        """RAG ingest fails for nonexistent source path."""
        result = runner.invoke(
            app,
            ["rag", "ingest", "--source", "/nonexistent/path/docs.md"],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# List adapters (CLI)
# ---------------------------------------------------------------------------


class TestListAdaptersCLI:
    """Tests for ``agentic list adapters`` via CLI."""

    def test_list_adapters_returns_both(self):
        """List adapters shows native and langchain."""
        result = runner.invoke(app, ["list", "adapters"])
        assert result.exit_code == 0
        assert "native" in result.stdout
        assert "langchain" in result.stdout

    def test_list_adapters_shows_table(self):
        """List adapters displays a formatted table."""
        result = runner.invoke(app, ["list", "adapters"])
        assert result.exit_code == 0
        assert "Adapter" in result.stdout or "Name" in result.stdout
