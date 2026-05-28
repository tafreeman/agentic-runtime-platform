"""Typer sub-application for developer-experience commands.

Registered in the main CLI as:  ``agentic devex <command>``
"""

from __future__ import annotations

import typer

from .port_guard import DEFAULT_PORTS, guard_ports
from .workflow_linter import lint_workflow_by_name, lint_workflow_file
from .workspace_test_runner import PACKAGES, run_all

devex_app = typer.Typer(
    name="devex",
    help="Developer experience utilities.",
    add_completion=False,
)


@devex_app.command("port-guard")
def port_guard_cmd(
    backend_port: int = typer.Option(
        DEFAULT_PORTS["backend"],
        "--backend-port",
        help="Backend service port to check.",
    ),
    frontend_port: int = typer.Option(
        DEFAULT_PORTS["frontend"],
        "--frontend-port",
        help="Frontend service port to check.",
    ),
) -> None:
    """Check whether required service ports are available before starting."""
    from rich.console import Console

    console = Console()
    console.print("\n[bold]Port availability check[/bold]")

    ports = {"backend": backend_port, "frontend": frontend_port}
    all_free = guard_ports(ports)

    if all_free:
        console.print(
            f"\n[green]All ports free[/green] "
            f"(checked: {', '.join(str(p) for p in ports.values())})"
        )
        raise typer.Exit(code=0)
    else:
        console.print(
            "\n[red]Port conflict detected.[/red] "
            "Stop the conflicting process before starting services."
        )
        raise typer.Exit(code=1)


_PACKAGE_NAMES = [p["name"] for p in PACKAGES]


@devex_app.command("workspace-test-runner")
def workspace_test_runner_cmd(
    skip_integration: bool = typer.Option(
        True,
        "--skip-integration/--no-skip-integration",
        help="Skip tests marked @pytest.mark.integration (default: True).",
    ),
    coverage: bool = typer.Option(
        False,
        "--coverage/--no-coverage",
        help="Append --cov and --cov-report=term-missing to each pytest run.",
    ),
    package: str = typer.Option(
        "",
        "--package",
        help=f"Run only this package. One of: {', '.join(_PACKAGE_NAMES)}",
    ),
) -> None:
    """Run the full test suite across all workspace packages."""
    if package and package not in _PACKAGE_NAMES:
        typer.echo(
            f"Unknown package '{package}'. Valid options: {', '.join(_PACKAGE_NAMES)}",
            err=True,
        )
        raise typer.Exit(code=1)

    all_passed = run_all(
        skip_integration=skip_integration,
        coverage=coverage,
        package_filter=package or None,
    )
    raise typer.Exit(code=0 if all_passed else 1)


@devex_app.command("workflow-linter")
def workflow_linter_cmd(
    workflow: str = typer.Argument(
        ...,
        help="Workflow name (resolved from definitions/) or path to a .yaml file.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Also report warnings as violations.",
    ),
) -> None:
    """Validate a workflow YAML file for structural correctness."""
    import pathlib

    from rich.console import Console

    console = Console()

    if workflow.endswith((".yaml", ".yml")):
        violations = lint_workflow_file(pathlib.Path(workflow))
    else:
        violations = lint_workflow_by_name(workflow)

    if not strict:
        violations = [v for v in violations if v.severity != "warning"]

    if violations:
        for v in violations:
            console.print(f"  [red]!![/red]  {v}")
        console.print(f"\n[red]{len(violations)} violation(s) found.[/red]")
        raise typer.Exit(code=1)

    step_count = ""
    console.print(f"  [green]OK[/green]  {workflow} is valid{step_count}")
    raise typer.Exit(code=0)
