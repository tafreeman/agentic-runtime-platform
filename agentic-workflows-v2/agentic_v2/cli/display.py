"""Display and formatting helpers for the agentic CLI.

All terminal-output logic -- tables, trees, coloured status lines -- lives
here so that ``main.py`` stays focused on Typer command declarations.

Public API
----------
_show_execution_plan  -- render a workflow's DAG as a Rich Tree
_show_results         -- render a WorkflowResult summary
_list_workflows       -- print available workflow table
_list_agents          -- print agent-tier table
_list_tools           -- print LangChain tools table
_list_adapters        -- print registered-adapter table
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

console = Console()

# ---------------------------------------------------------------------------
# Execution-plan helpers
# ---------------------------------------------------------------------------

_STATUS_STYLE: dict[str, str] = {
    "success": "[green]\u2713[/green] success",
    "failed": "[red]\u2717[/red] failed",
    "skipped": "[yellow]\u2298[/yellow] skipped",
}


def _step_label(step) -> str:
    """Return a Rich-markup label string for a single workflow step."""
    label = f"[yellow]{step.name}[/yellow]"
    if step.agent:
        label += f" [dim]({step.agent})[/dim]"
    if step.depends_on:
        label += f" <- {step.depends_on}"
    return label


def _compute_step_levels(workflow_def) -> dict[int, list]:
    """Compute parallel execution levels (depth in the DAG) for each step.

    Args:
        workflow_def: A ``WorkflowConfig`` instance whose ``.steps`` list
            contains objects with ``.name`` and ``.depends_on`` attributes.

    Returns:
        Dict mapping level index (0 = root) to the list of steps at that level.
    """
    step_index = {s.name: s for s in workflow_def.steps}
    step_levels: dict[str, int] = {}

    def _depth(name: str, visited: set) -> int:
        if name in step_levels:
            return step_levels[name]
        if name in visited:
            return 0
        visited.add(name)
        step = step_index.get(name)
        d = (
            0
            if (not step or not step.depends_on)
            else max(_depth(dep, visited) for dep in step.depends_on) + 1
        )
        step_levels[name] = d
        return d

    for step in workflow_def.steps:
        _depth(step.name, set())

    levels: dict[int, list] = {}
    for step in workflow_def.steps:
        levels.setdefault(step_levels.get(step.name, 0), []).append(step)
    return levels


def _show_execution_plan(workflow_def) -> None:
    """Render the workflow execution plan as a Rich Tree.

    Args:
        workflow_def: A ``WorkflowConfig`` instance.
    """
    tree = Tree(f"[bold blue]{workflow_def.name}[/bold blue] - Execution Plan")
    for lvl, lvl_steps in sorted(_compute_step_levels(workflow_def).items()):
        if len(lvl_steps) > 1:
            node = tree.add(f"[cyan]Level {lvl}[/cyan] (parallel)")
            for s in lvl_steps:
                node.add(_step_label(s))
        else:
            tree.add(f"[cyan]Level {lvl}:[/cyan] {_step_label(lvl_steps[0])}")
    console.print("\n")
    console.print(tree)


# ---------------------------------------------------------------------------
# Result display helpers
# ---------------------------------------------------------------------------


def _step_info(step_data: dict) -> str:
    """Return a brief Rich-markup info string for a step result dict."""
    if step_data.get("error"):
        return f"[red]{step_data['error']}[/red]"
    if step_data.get("outputs"):
        return "outputs: " + ", ".join(step_data["outputs"])
    return ""


def _show_results(result, verbose: bool) -> None:
    """Render a workflow result to the console.

    Args:
        result: A ``WorkflowResult`` (or any object with ``.status``,
            ``.elapsed_seconds``, ``.errors``, ``.steps``, ``.outputs``).
        verbose: When *True*, always show the step table regardless of status.
    """
    status_color = "green" if result.status == "success" else "red"
    console.print(
        f"\n[bold {status_color}]Status: {result.status.upper()}[/bold {status_color}]"
    )
    console.print(f"[dim]Elapsed: {result.elapsed_seconds:.1f}s[/dim]")

    for err in result.errors:
        console.print(f"[red]Error:[/red] {err}")

    if verbose or result.status != "success":
        table = Table(title="Step Results")
        table.add_column("Step", style="cyan")
        table.add_column("Status")
        table.add_column("Info")
        for step_name, step_data in result.steps.items():
            status = step_data.get("status", "unknown")
            table.add_row(
                step_name,
                _STATUS_STYLE.get(status, status),
                _step_info(step_data),
            )
        console.print(table)

    if result.outputs:
        console.print("\n[bold]Outputs:[/bold]")
        for key, value in result.outputs.items():
            preview = str(value)
            if len(preview) > 120:
                preview = preview[:117] + "..."
            console.print(f"  [cyan]{key}:[/cyan] {preview}")


# ---------------------------------------------------------------------------
# List-command display helpers
# ---------------------------------------------------------------------------


def _list_workflows() -> None:
    """Print a table of available workflows using the LangChain config loader."""
    import typer

    try:
        from ..langchain import list_workflows as lc_list_workflows
        from ..langchain import load_workflow_config
    except ImportError:
        console.print(
            "[red]LangChain extras not installed.[/red]\n"
            "Install with: pip install -e '.[langchain]'"
        )
        raise typer.Exit(code=1)

    workflows = lc_list_workflows()

    if not workflows:
        console.print("[yellow]No workflows found in definitions directory.[/yellow]")
        return

    table = Table(title="Available Workflows")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Steps", justify="right")

    for name in workflows:
        try:
            wf = load_workflow_config(name)
            table.add_row(name, wf.description or "-", str(len(wf.steps)))
        except Exception:
            table.add_row(name, "[red]Error loading[/red]", "-")

    console.print(table)


def _list_agents() -> None:
    """Print a table of tier-based agent roles used by the LangChain engine."""
    agents = [
        ("tier1_*", "Tier 1", "Fast/cheap model (e.g. gpt-4o-mini, gemini-flash-lite)"),
        ("tier2_*", "Tier 2", "Standard model (e.g. gpt-4o, gemini-flash)"),
        ("tier3_*", "Tier 3", "Powerful model (e.g. o3-mini, gemini-2.5-pro)"),
        ("tier0_*", "Tier 0", "Deterministic/no-LLM step"),
    ]

    table = Table(title="Agent Tiers (LangChain Engine)")
    table.add_column("Pattern", style="cyan")
    table.add_column("Tier")
    table.add_column("Description")

    for pattern, tier, desc in agents:
        table.add_row(pattern, tier, desc)

    console.print(table)
    console.print(
        "\n[dim]Agent names in YAML follow the pattern tier{N}_{role} "
        "(e.g. tier2_reviewer, tier1_analyst)[/dim]"
    )


def _list_tools() -> None:
    """Print a table of LangChain tools registered in the engine."""
    try:
        from ..langchain.tools import get_tools_for_tier

        tools = get_tools_for_tier(tier=2)  # tier 2 has the broadest set
    except Exception:
        tools = []

    if not tools:
        console.print("[yellow]No LangChain tools available.[/yellow]")
        return

    table = Table(title="Available LangChain Tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Description")

    for tool in tools:
        table.add_row(tool.name, getattr(tool, "description", "-") or "-")

    console.print(table)


def _list_adapters() -> None:
    """Print a table of registered execution engine adapters."""
    from ..adapters import get_registry

    reg = get_registry()
    names = reg.list_adapters()

    if not names:
        console.print("[yellow]No adapters registered.[/yellow]")
        return

    table = Table(title="Available Execution Adapters")
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    descriptions = {
        "native": "Built-in DAG/Pipeline executor (no external dependencies)",
        "langchain": "LangGraph state-machine executor",
    }
    for name in names:
        table.add_row(name, descriptions.get(name, "-"))

    console.print(table)
    console.print(
        "\n[dim]Use --adapter <name> with 'agentic run' to select an adapter[/dim]"
    )
