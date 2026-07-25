"""CLI interface for agentic workflows v2.

Commands:
- agentic run <workflow> --input <file.json>  - Run a named YAML workflow via the default LangGraph adapter
- agentic compare <workflow> --input <file>   - Compare adapters side by side
- agentic list workflows|agents|tools         - List available components
- agentic validate <workflow>                 - Validate a workflow definition
- agentic rag ingest --source <path>          - Ingest documents into RAG
- agentic rag search <query>                  - Search the RAG index
- agentic serve                               - Start the dashboard server
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import time
from pathlib import Path
from typing import Any

# Load .env before the settings singleton initialises
try:
    from dotenv import load_dotenv

    for _parent in Path(__file__).resolve().parents:
        _env_path = _parent / ".env"
        if _env_path.is_file():
            load_dotenv(_env_path, override=False)
            break
except ImportError:
    pass

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..devex.cli import devex_app
from ..integrations.otel import create_trace_adapter, shutdown_tracing
from .display import (
    _list_adapters,
    _list_agents,
    _list_tools,
    _list_workflows,
    _show_execution_plan,
    _show_results,
)
from .helpers import (
    _normalize_result,
    _rag_ingest_impl,  # noqa: F401 — patched by tests via agentic_v2.cli.main._rag_ingest_impl
    _rag_search_impl,  # noqa: F401 — patched by tests via agentic_v2.cli.main._rag_search_impl
    _run_adapter,
    _run_via_adapter,
)
from .rag_commands import rag_group

logger = logging.getLogger(__name__)

YAML_EXTENSION = ".yaml"

# LangChain imports — deferred so the CLI module loads even when
# langchain extras are not installed.  Commands that need LangChain
# call _get_runner() and catch the error at that point.
try:
    from ..langchain import WorkflowRunner, load_workflow_config
    from ..langchain.graph import compile_workflow

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False

# Create CLI app
app = typer.Typer(
    name="agentic",
    help="Agentic Workflows V2 - YAML workflows default to LangGraph; pass --adapter native for the native DAG engine",
    add_completion=False,
)

console = Console()

# Initialize tracing adapter (respects AGENTIC_TRACING env var)
_trace_adapter = create_trace_adapter()
_runner = None  # lazily initialized by _get_runner()

# Register shutdown hook for tracing cleanup
atexit.register(shutdown_tracing)

# Register RAG subcommand group
app.add_typer(rag_group, name="rag")

# Register DevEx subcommand group
app.add_typer(devex_app, name="devex")


def _require_langchain() -> None:
    """Raise a clear error if langchain extras are not installed."""
    if not _LANGCHAIN_AVAILABLE:
        console.print(
            "[red]LangChain extras not installed.[/red]\n"
            "Install with: pip install -e '.[langchain]'"
        )
        raise typer.Exit(code=1)


def _get_runner():
    """Lazily initialize the WorkflowRunner."""
    global _runner
    _require_langchain()
    if _runner is None:
        _runner = WorkflowRunner(trace_adapter=_trace_adapter)
    return _runner


def _resolve_workflow_source(workflow: str) -> tuple[str, Path | None]:
    """Resolve a workflow argument into ``(workflow_name, definitions_dir)``.

    Exits with an error if a ``.yaml``/``.yml`` path is given but missing.
    """
    if workflow.endswith((YAML_EXTENSION, ".yml")):
        workflow_path = Path(workflow)
        if not workflow_path.exists():
            console.print(f"[red]Error:[/red] Workflow file not found: {workflow}")
            raise typer.Exit(1)
        return workflow_path.stem, workflow_path.parent
    return workflow, None


def _load_run_input(input_file: Path | None) -> dict:
    """Load and parse the JSON input file, or return an empty dict."""
    if not input_file:
        return {}
    if not input_file.exists():
        console.print(f"[red]Error:[/red] Input file not found: {input_file}")
        raise typer.Exit(1)
    return json.loads(input_file.read_text())


def _execute_run(
    adapter: str,
    workflow_name: str,
    workflow_def: Any,
    definitions_dir: Path | None,
    input_data: dict,
) -> Any:
    """Execute the workflow under a progress spinner and return the result."""
    with Progress(
        SpinnerColumn(spinner_name="line"),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Executing {workflow_def.name}...", total=None)
        start_time = time.perf_counter()
        if adapter == "langchain":
            # TODO(ADR-001): The LangChain path uses a separate
            # WorkflowRunner (from ..langchain) that compiles workflows
            # into LangGraph state machines via compile_workflow().  It
            # relies on load_workflow_config() (not the native YAML
            # loader) and produces a different result shape.  Unifying
            # both paths through the AdapterRegistry requires the
            # LangChain adapter to accept the same workflow-loading
            # interface as the native path — tracked for Phase 2.
            runner = WorkflowRunner(definitions_dir=definitions_dir)
            raw_result = asyncio.run(
                runner.run(
                    workflow_name,
                    thread_id=workflow_name,
                    **input_data,
                )
            )
            wall_clock = time.perf_counter() - start_time
            result = _normalize_result(workflow_name, raw_result, wall_clock)
        else:
            # Non-langchain path: dispatch through the adapter registry
            result = _run_via_adapter(adapter, workflow_name, input_data)
        progress.update(task, completed=True)
    return result


def _write_run_output(result: Any, output_file: Path) -> None:
    """Serialize *result* to *output_file* as JSON."""
    output_data = {
        "workflow_name": result.workflow_name,
        "status": result.status,
        "outputs": result.outputs,
        "steps": result.steps,
        "errors": result.errors,
        "elapsed_seconds": result.elapsed_seconds,
    }
    output_file.write_text(json.dumps(output_data, indent=2, default=str))
    console.print(f"\n[green]Results written to:[/green] {output_file}")


def _report_run_error(e: Exception) -> None:
    """Print a user-friendly error panel/message for a failed run."""
    from ..core.errors import NoProviderConfiguredError

    if isinstance(e, NoProviderConfiguredError):
        console.print(
            Panel(
                str(e),
                title="[bold red]⚠ Configuration Error[/bold red]",
                border_style="red",
                padding=(1, 2),
            )
        )
    else:
        console.print(f"[red]Error:[/red] {e}")


@app.command()
def run(
    workflow: str = typer.Argument(
        ...,
        help="Workflow name (e.g., 'code_review') or path to YAML file",
    ),
    input_file: Path | None = typer.Option(
        None,
        "--input",
        "-i",
        help="JSON file with input variables",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write results to JSON file",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and show execution plan without running",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed execution info",
    ),
    adapter: str = typer.Option(
        "langchain",
        "--adapter",
        "-a",
        help="Execution adapter: 'langchain' (default for named YAML workflows) or 'native' (dependency-light DAG/Pipeline path)",
    ),
):
    """Execute a workflow from a YAML definition.

    Examples:
        agentic run code_review --input review_input.json
        agentic run ./my_workflow.yaml --dry-run
        agentic run code_review --adapter native --input review_input.json
    """
    if adapter == "langchain":
        _require_langchain()
    try:
        # Resolve name from file path
        workflow_name, definitions_dir = _resolve_workflow_source(workflow)

        try:
            workflow_def = load_workflow_config(workflow_name, definitions_dir)
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from e

        # Load input variables
        input_data = _load_run_input(input_file)

        # Display workflow info
        console.print(
            Panel(
                f"[bold]{workflow_def.name}[/bold]\n{workflow_def.description or 'No description'}",
                title="Workflow",
                border_style="blue",
            )
        )

        # Show execution plan
        if verbose or dry_run:
            _show_execution_plan(workflow_def)

        if dry_run:
            console.print("\n[yellow]Dry run - skipping execution[/yellow]")
            return

        result = _execute_run(
            adapter, workflow_name, workflow_def, definitions_dir, input_data
        )

        # Display results
        _show_results(result, verbose)

        # Write output if requested
        if output_file:
            _write_run_output(result, output_file)

        if result.status == "failed":
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        _report_run_error(e)
        raise typer.Exit(1) from e


@app.command()
def compare(
    workflow: str = typer.Argument(
        ...,
        help="Workflow name (e.g., 'code_review')",
    ),
    input_file: Path = typer.Option(
        ...,
        "--input",
        "-i",
        help="JSON file with input variables",
    ),
    adapters: str = typer.Option(
        "native,langchain",
        "--adapters",
        help="Comma-separated adapter names to compare",
    ),
):
    """Run a workflow through multiple adapters and compare results.

    Executes the same workflow with the same inputs through each specified
    adapter, then prints a comparison table showing status, step count,
    and elapsed time.

    Exits non-zero if any adapter failed — a run where one side never
    executed is not a valid comparison.

    Examples:
        agentic compare code_review --input review_input.json
        agentic compare code_review -i input.json --adapters native,langchain
    """
    from rich.table import Table

    try:
        if not input_file.exists():
            console.print(f"[red]Error:[/red] Input file not found: {input_file}")
            raise typer.Exit(1)

        input_data = json.loads(input_file.read_text())
        workflow_def = load_workflow_config(workflow)

        adapter_names = [a.strip() for a in adapters.split(",") if a.strip()]

        console.print(
            Panel(
                f"[bold]{workflow_def.name}[/bold] - Adapter Comparison",
                title="Compare",
                border_style="blue",
            )
        )

        table = Table(title="Adapter Comparison Results")
        table.add_column("Adapter", style="cyan")
        table.add_column("Status")
        table.add_column("Steps", justify="right")
        table.add_column("Elapsed (s)", justify="right")

        failed_adapters: list[str] = []

        for adapter_name in adapter_names:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress:
                progress.add_task(f"Running {adapter_name}...", total=None)
                summary = _run_adapter(adapter_name, workflow, input_data)

            if summary["status"] == "failed":
                failed_adapters.append(adapter_name)

            status_display = (
                f"[green]{summary['status']}[/green]"
                if "success" in summary["status"].lower()
                else f"[red]{summary['status']}[/red]"
            )
            table.add_row(
                adapter_name,
                status_display,
                str(summary["step_count"]),
                str(summary["elapsed"]),
            )

        console.print(table)

        # The table is printed first so the user still sees every row, but a
        # comparison in which an adapter never ran is not a valid comparison —
        # exit non-zero so scripts and CI do not read it as agreement.
        if failed_adapters:
            console.print(
                f"[red]Error:[/red] adapter(s) failed: {', '.join(failed_adapters)}"
            )
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from e


@app.command()
def orchestrate(
    task: str = typer.Argument(
        ...,
        help="Natural language description of the task to accomplish",
    ),
    max_parallel: int = typer.Option(
        3,
        "--max-parallel",
        "--max-steps",
        help="Maximum number of steps to run in parallel",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed execution info",
    ),
):
    """Dynamically generate and execute a workflow from a task description.

    Note: Dynamic orchestration is not exposed through the default LangGraph
    workflow path yet. Use 'agentic run <workflow>' for YAML-defined workflows.
    """
    console.print(
        "[yellow]Dynamic orchestration is not exposed through the default LangGraph workflow path yet.[/yellow]"
    )
    console.print(
        "Use [bold]agentic run <workflow>[/bold] to run a YAML-defined workflow "
        "(no LLM configuration required for this command path)."
    )
    raise typer.Exit(1)


@app.command()
def resume(
    name: str = typer.Argument(
        ...,
        help="Checkpoint name to rehydrate (the file stem under --checkpoint-dir)",
    ),
    checkpoint_dir: Path = typer.Option(
        Path(".agentic_checkpoints"),
        "--checkpoint-dir",
        help="Directory holding checkpoint JSON files",
    ),
    fork: str | None = typer.Option(
        None,
        "--fork",
        help="After rehydrating, branch a divergent run with this fork name",
    ),
):
    """Rehydrate a named ExecutionContext checkpoint and report file changes.

    Loads ``<checkpoint-dir>/<name>.json`` into a fresh ``ExecutionContext``,
    diffs any files tracked at save time, and prints the "these files changed"
    notice for the operator to prepend to a resumed prompt. With ``--fork`` it
    then branches a divergent run off the rehydrated baseline via
    ``fork_session``.

    See ADR-026 for why a fresh session seeded with a structured summary often
    beats ``--resume`` with stale tool results.

    Examples:
        agentic resume my_run
        agentic resume my_run --checkpoint-dir ./ckpts --fork experiment_a
    """
    from ..engine import ExecutionContext

    checkpoint_path = checkpoint_dir / f"{name}.json"
    if not checkpoint_path.exists():
        console.print(f"[red]Error:[/red] Checkpoint not found: {checkpoint_path}")
        raise typer.Exit(1)

    ctx = ExecutionContext(checkpoint_dir=checkpoint_dir)
    try:
        asyncio.run(ctx.restore_checkpoint(checkpoint_path))
    except (ValueError, FileNotFoundError) as e:
        console.print(f"[red]Error:[/red] Failed to restore checkpoint: {e}")
        raise typer.Exit(1) from e

    console.print(
        Panel(
            f"[bold]{name}[/bold]\n"
            f"workflow={ctx.workflow_id}\n"
            f"completed steps: {len(ctx.completed_steps)} | "
            f"failed steps: {len(ctx.failed_steps)}",
            title="Resumed Checkpoint",
            border_style="green",
        )
    )

    changed = ExecutionContext.detect_changed_files(checkpoint_path)
    notice = ExecutionContext.build_changed_files_notice(changed)
    if notice:
        console.print(notice)
    else:
        console.print("[dim]No tracked files changed since the checkpoint.[/dim]")

    if fork:
        forked = ctx.fork_session(fork)
        console.print(
            f"[cyan]Forked[/cyan] '[bold]{fork}[/bold]' "
            f"(run_id={forked.run_id}) off baseline run {ctx.run_id}"
        )


@app.command("list")
def list_components(
    component_type: str = typer.Argument(
        "workflows",
        help="Type of component to list: workflows, agents, tools, or adapters",
    ),
):
    """List available workflows, agents, tools, or adapters.

    Examples:
        agentic list workflows
        agentic list agents
        agentic list tools
        agentic list adapters
    """
    component_type = component_type.lower()

    if component_type == "workflows":
        _list_workflows()
    elif component_type == "agents":
        _list_agents()
    elif component_type == "tools":
        _list_tools()
    elif component_type == "adapters":
        _list_adapters()
    else:
        console.print(f"[red]Unknown component type:[/red] {component_type}")
        console.print("Available types: workflows, agents, tools, adapters")
        raise typer.Exit(1)


@app.command()
def validate(
    workflow: str = typer.Argument(
        ...,
        help="Workflow name or path to YAML file to validate",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed validation info",
    ),
):
    """Validate a workflow definition without executing it.

    Checks:
    - YAML syntax and schema
    - Step dependencies (no cycles, no missing deps)
    - Graph compilation via LangGraph

    Examples:
        agentic validate code_review
        agentic validate ./custom_workflow.yaml --verbose
    """
    from ..devex.workflow_linter import lint_workflow_by_name, lint_workflow_file

    # Tier 1: fast structural lint (no extras required)
    if workflow.endswith((YAML_EXTENSION, ".yml")):
        lint_violations = lint_workflow_file(Path(workflow))
    else:
        lint_violations = lint_workflow_by_name(workflow)

    if lint_violations:
        for v in lint_violations:
            console.print(f"  [red]!![/red]  {v}")
        console.print(
            f"\n[red]{len(lint_violations)} lint violation(s) -- fix before validating.[/red]"
        )
        raise typer.Exit(1)

    # Tier 2: deep LangGraph compilation check (requires langchain extra)
    _require_langchain()
    try:
        definitions_dir: Path | None = None
        workflow_name = workflow
        if workflow.endswith((YAML_EXTENSION, ".yml")):
            workflow_path = Path(workflow)
            if not workflow_path.exists():
                console.print(f"[red]Error:[/red] File not found: {workflow}")
                raise typer.Exit(1)
            workflow_name = workflow_path.stem
            definitions_dir = workflow_path.parent

        workflow_def = load_workflow_config(workflow_name, definitions_dir)

        # Compile through LangGraph to catch graph-level errors without
        # requiring provider API keys during static validation.
        compile_workflow(workflow_def, validate_only=True)

        console.print(
            f"\n[green]OK[/green] Workflow '[bold]{workflow_def.name}[/bold]' is valid!"
        )

        if verbose:
            console.print("\n[bold]Details:[/bold]")
            console.print(f"  Version: {workflow_def.version}")
            console.print(f"  Steps: {len(workflow_def.steps)}")
            console.print(f"  Inputs: {len(workflow_def.inputs)}")
            console.print(f"  Outputs: {len(workflow_def.outputs)}")
            _show_execution_plan(workflow_def)

    except FileNotFoundError as e:
        console.print(f"[red]FAIL[/red] Workflow not found: {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]FAIL[/red] Validation error: {e}")
        raise typer.Exit(1) from e


@app.command()
def serve(
    port: int = typer.Option(8000, "--port", "-p", help="Port to serve on"),
    dev: bool = typer.Option(False, "--dev", help="Run with auto-reload"),
    no_open: bool = typer.Option(False, "--no-open", help="Don't open browser"),
):
    """Start the workflow dashboard server.

    In dev mode, run `npm run dev` in the ui/ directory for the frontend dev server.

    Examples:
        agentic serve
        agentic serve --port 9000 --dev
    """
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Error:[/red] uvicorn not installed. Run: pip install uvicorn"
        )
        raise typer.Exit(1) from None

    if not no_open:
        import webbrowser

        webbrowser.open(f"http://localhost:{port}")

    console.print(f"[bold blue]Starting dashboard server on port {port}[/bold blue]")
    if dev:
        console.print("[dim]Dev mode: auto-reload enabled[/dim]")

    uvicorn.run(
        "agentic_v2.server.app:create_app",
        host="127.0.0.1",
        port=port,
        reload=dev,
        factory=True,
    )


@app.command()
def version():
    """Show version information."""
    try:
        from .. import __version__

        ver = __version__
    except ImportError:
        ver = "0.1.0"

    console.print(f"[bold]agentic-workflows-v2[/bold] version {ver}")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
