"""Tests for CLI interface.

Covers:
- Command execution
- Help output
- Workflow listing and validation
- Error handling
"""

# ADR-008 cleanup: fixed 2 broken tests (see docs/adr/ADR-008-testing-approach-overhaul.md)

from pathlib import Path
from tempfile import TemporaryDirectory

from agentic_v2.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


class TestCLIHelp:
    """Tests for help output."""

    def test_main_help(self):
        """Main command shows help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Agentic Workflows V2" in result.stdout

    def test_run_help(self):
        """Run command shows help."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "Execute a workflow" in result.stdout

    def test_list_help(self):
        """List command shows help."""
        result = runner.invoke(app, ["list", "--help"])
        assert result.exit_code == 0
        assert "workflows" in result.stdout.lower()

    def test_validate_help(self):
        """Validate command shows help."""
        result = runner.invoke(app, ["validate", "--help"])
        assert result.exit_code == 0
        assert "Validate" in result.stdout

    def test_orchestrate_help(self):
        """Orchestrate command shows help."""
        result = runner.invoke(app, ["orchestrate", "--help"])
        assert result.exit_code == 0
        assert "Dynamic" in result.stdout or "task" in result.stdout.lower()

    def test_version(self):
        """Version command works."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "agentic-workflows-v2" in result.stdout


class TestCLIList:
    """Tests for list commands."""

    def test_list_workflows(self):
        """List workflows shows available workflows."""
        result = runner.invoke(app, ["list", "workflows"])
        assert result.exit_code == 0
        assert "code_review" in result.stdout
        assert "fullstack_generation" in result.stdout

    def test_list_agents(self):
        """List agents shows available tier-based agents."""
        result = runner.invoke(app, ["list", "agents"])
        assert result.exit_code == 0
        assert "Tier 1" in result.stdout
        assert "Tier 2" in result.stdout
        assert "Tier 3" in result.stdout
        assert "tier" in result.stdout.lower()

    def test_list_tools(self):
        """List tools shows message when no tools registered."""
        result = runner.invoke(app, ["list", "tools"])
        assert result.exit_code == 0
        # Either shows tools or message about no tools
        assert "tools" in result.stdout.lower() or "No tools" in result.stdout

    def test_list_invalid_type(self):
        """List with invalid type shows error."""
        result = runner.invoke(app, ["list", "invalid"])
        assert result.exit_code == 1
        assert "Unknown component type" in result.stdout


class TestCLIValidate:
    """Tests for validate command."""

    def test_validate_code_review(self):
        """Validate code_review workflow succeeds."""
        result = runner.invoke(app, ["validate", "code_review"])
        assert result.exit_code == 0
        assert "valid" in result.stdout

    def test_validate_fullstack_generation(self):
        """Validate fullstack_generation workflow succeeds."""
        result = runner.invoke(app, ["validate", "fullstack_generation"])
        assert result.exit_code == 0
        assert "valid" in result.stdout

    def test_validate_verbose(self):
        """Validate with verbose shows details."""
        result = runner.invoke(app, ["validate", "code_review", "--verbose"])
        assert result.exit_code == 0
        assert "Steps:" in result.stdout
        assert "Inputs:" in result.stdout

    def test_validate_nonexistent(self):
        """Validate nonexistent workflow fails."""
        result = runner.invoke(app, ["validate", "nonexistent_workflow"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_validate_file_path(self):
        """Validate can load from file path."""
        with TemporaryDirectory() as tmpdir:
            workflow_path = Path(tmpdir) / "test.yaml"
            workflow_path.write_text("""
name: test_workflow
steps:
  - name: step1
    description: Test step
    agent: tier2_coder
""")
            result = runner.invoke(app, ["validate", str(workflow_path)])
            assert result.exit_code == 0
            assert "valid" in result.stdout


class TestCLIRun:
    """Tests for run command."""

    def test_run_nonexistent_workflow(self):
        """Running nonexistent workflow fails."""
        result = runner.invoke(app, ["run", "nonexistent_workflow"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_run_dry_run(self):
        """Dry run shows plan without executing."""
        result = runner.invoke(app, ["run", "code_review", "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.stdout
        assert "Execution Plan" in result.stdout

    def test_run_missing_input_file(self):
        """Running with missing input file fails."""
        result = runner.invoke(
            app, ["run", "code_review", "--input", "nonexistent.json"]
        )
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_run_with_input_file(self):
        """Running with input file works (dry run)."""
        with TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.json"
            input_path.write_text('{"code_file": "test.py", "review_depth": "quick"}')

            result = runner.invoke(
                app, ["run", "code_review", "--input", str(input_path), "--dry-run"]
            )
            assert result.exit_code == 0
            assert "code_review" in result.stdout


class TestCLIOrchestrate:
    """Tests for orchestrate command."""

    def test_orchestrate_shows_note(self):
        """Orchestrate shows LLM configuration note or orchestration output."""
        result = runner.invoke(app, ["orchestrate", "Test task"])
        assert len(result.stdout) > 0
        lower_out = result.stdout.lower()
        # Must reference LLM setup or orchestration — not generic words
        assert any(kw in lower_out for kw in ("llm", "orchestrat"))


class TestServerApp:
    """Tests for server app startup."""

    def test_server_app_imports_cleanly(self):
        """Server app module imports without errors."""
        from agentic_v2.server.app import create_app

        app = create_app()
        assert app is not None
        assert app.title == "Agentic Workflows V2 API"

    def test_server_api_routes_registered(self):
        """All expected API routes are registered."""
        from agentic_v2.server.app import create_app

        app = create_app()
        paths = [r.path for r in app.routes]
        assert "/api/health" in paths
        assert "/api/workflows" in paths
        assert "/api/agents" in paths


class TestCLIEdgeCases:
    """Edge case tests."""

    def test_no_arguments(self):
        """Running without arguments shows usage error."""
        result = runner.invoke(app, [])
        assert result.exit_code == 2

    def test_invalid_workflow_yaml_syntax(self):
        """Invalid YAML syntax in workflow file is caught."""
        with TemporaryDirectory() as tmpdir:
            bad_yaml = Path(tmpdir) / "bad.yaml"
            bad_yaml.write_text("{ invalid yaml [")

            result = runner.invoke(app, ["validate", str(bad_yaml)])
            assert result.exit_code == 1
            assert (
                "invalid" in result.stdout.lower() or "error" in result.stdout.lower()
            )
