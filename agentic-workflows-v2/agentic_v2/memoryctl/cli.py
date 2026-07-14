"""memoryctl CLI — deterministic maintenance for the agent context system.

Commands (design doc §6):

- memoryctl validate    - Frontmatter schema lint on memory/playbook files
- memoryctl index       - Regenerate the MEMORY.md index from frontmatter
- memoryctl links       - Check [[name]]/path references resolve
- memoryctl budget      - Enforce line/byte caps
- memoryctl staleness   - Report stale docs, facts, and unverified memories
- memoryctl verify      - Execute every verify: command; record pass/fail
- memoryctl dedupe      - Exact/normalized duplicate detection
- memoryctl archive     - Tombstone moves; reduced-run rotation
- memoryctl stats       - Reduce episodes.jsonl into registry/stats.json
- memoryctl report      - Emit the findings queue for the weekly LLM pass
- memoryctl maintain    - The nightly set, in order, then the report

Exit codes: 0 = no error-severity findings, 1 = at least one error
finding, 2 = usage/config problem.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import typer
from rich.console import Console
from rich.markup import escape

from agentic_v2.memoryctl import archive as archive_mod
from agentic_v2.memoryctl import budget as budget_mod
from agentic_v2.memoryctl import dedupe as dedupe_mod
from agentic_v2.memoryctl import index_cmd as index_mod
from agentic_v2.memoryctl import links as links_mod
from agentic_v2.memoryctl import report as report_mod
from agentic_v2.memoryctl import staleness as staleness_mod
from agentic_v2.memoryctl import stats as stats_mod
from agentic_v2.memoryctl import validate as validate_mod
from agentic_v2.memoryctl import verify_cmd as verify_mod
from agentic_v2.memoryctl._shared import (
    SEVERITY_ERROR,
    SEVERITY_WARN,
    CommandResult,
    MemoryctlConfig,
    findings_to_jsonl,
)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
DEFAULT_MEMORY_DIR_NAME = "memory"

app = typer.Typer(
    name="memoryctl",
    help="Deterministic (TIER_0) maintenance core for the agent context system",
    add_completion=False,
)
console = Console()


class _CommandRunner(Protocol):
    """The uniform ``run`` callable every command module exposes."""

    def __call__(
        self, cfg: MemoryctlConfig, *, dry_run: bool = False
    ) -> CommandResult: ...


@dataclass(frozen=True)
class CliState:
    """Resolved configuration shared by all subcommands."""

    cfg: MemoryctlConfig
    dry_run: bool
    json_output: bool


def _require_existing(paths: Sequence[Path], label: str) -> None:
    """Exit with the usage code when an explicitly-given dir is missing."""
    for path in paths:
        if not path.is_dir():
            console.print(f"[red]Error:[/red] {label} not found: {path}")
            raise typer.Exit(EXIT_USAGE)


def _resolve_memory_dirs(explicit: list[Path] | None) -> tuple[Path, ...]:
    """Explicit dirs, or ``./memory`` when present, or nothing."""
    if explicit:
        _require_existing(explicit, "--memory-dir")
        return tuple(explicit)
    default = Path(DEFAULT_MEMORY_DIR_NAME)
    return (default,) if default.is_dir() else ()


@app.callback()
def configure(
    ctx: typer.Context,
    memory_dir: list[Path] | None = typer.Option(
        None,
        "--memory-dir",
        help="Memory directory (repeatable; defaults to ./memory when present).",
    ),
    docs_dir: list[Path] | None = typer.Option(
        None, "--docs-dir", help="Docs directory to scan (repeatable)."
    ),
    fleet_dir: Path | None = typer.Option(
        None, "--fleet-dir", help="Fleet directory (registry, playbooks, runs)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would change; write nothing."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit findings as JSONL on stdout."
    ),
) -> None:
    """Shared options for every memoryctl subcommand."""
    docs_dirs = tuple(docs_dir) if docs_dir else ()
    _require_existing(docs_dirs, "--docs-dir")
    if fleet_dir is not None:
        _require_existing((fleet_dir,), "--fleet-dir")
    cfg = MemoryctlConfig(
        memory_dirs=_resolve_memory_dirs(memory_dir),
        docs_dirs=docs_dirs,
        fleet_dir=fleet_dir,
    )
    ctx.obj = CliState(cfg=cfg, dry_run=dry_run, json_output=json_output)


def _state(ctx: typer.Context) -> CliState:
    state = ctx.obj
    if not isinstance(state, CliState):  # pragma: no cover — typer wires ctx.obj
        raise typer.Exit(EXIT_USAGE)
    return state


def _exit_code(results: Sequence[CommandResult]) -> int:
    has_error = any(f.severity == SEVERITY_ERROR for r in results for f in r.findings)
    return EXIT_FINDINGS if has_error else EXIT_OK


def _print_result(result: CommandResult) -> None:
    console.print(f"[bold]{escape(result.name)}[/bold] — {escape(result.summary)}")
    for f in result.findings:
        style = {SEVERITY_ERROR: "red", SEVERITY_WARN: "yellow"}.get(f.severity, "dim")
        location = f" ({f.path})" if f.path is not None else ""
        console.print(
            f"  [{style}]{f.severity}[/{style}] "
            f"{escape(f.code)}: {escape(f.message)}{escape(location)}"
        )


def _finish(state: CliState, results: Sequence[CommandResult]) -> None:
    """Emit output for ``results`` and exit with the aggregate code."""
    if state.json_output:
        payload = findings_to_jsonl([f for r in results for f in r.findings])
        typer.echo(payload, nl=False)
    else:
        for result in results:
            _print_result(result)
    raise typer.Exit(_exit_code(results))


def _run_single(ctx: typer.Context, run_fn: _CommandRunner) -> None:
    state = _state(ctx)
    _finish(state, [run_fn(state.cfg, dry_run=state.dry_run)])


@app.command()
def validate(ctx: typer.Context) -> None:
    """Frontmatter schema lint on all memory/playbook files."""
    _run_single(ctx, validate_mod.run)


@app.command()
def index(ctx: typer.Context) -> None:
    """Regenerate the MEMORY.md index from topic-file frontmatter."""
    _run_single(ctx, index_mod.run)


@app.command()
def links(ctx: typer.Context) -> None:
    """Check that wiki-style name references and path links resolve."""
    _run_single(ctx, links_mod.run)


@app.command()
def budget(ctx: typer.Context) -> None:
    """Enforce line/byte caps; emit split/merge candidates."""
    _run_single(ctx, budget_mod.run)


@app.command()
def staleness(ctx: typer.Context) -> None:
    """Report stale docs, aged facts, and long-unverified memories."""
    _run_single(ctx, staleness_mod.run)


@app.command()
def verify(ctx: typer.Context) -> None:
    """Execute every verify: command and record pass/fail."""
    _run_single(ctx, verify_mod.run)


@app.command()
def dedupe(ctx: typer.Context) -> None:
    """Detect exact/normalized-text duplicate memories."""
    _run_single(ctx, dedupe_mod.run)


@app.command()
def archive(ctx: typer.Context) -> None:
    """Move superseded topic files to archive/; rotate reduced runs."""
    _run_single(ctx, archive_mod.run)


@app.command()
def stats(ctx: typer.Context) -> None:
    """Reduce episode records into cumulative registry/stats.json."""
    _run_single(ctx, stats_mod.run)


@app.command()
def report(ctx: typer.Context) -> None:
    """Emit the findings queue (JSONL) for the weekly LLM pass."""
    _run_single(ctx, report_mod.run)


MAINTAIN_SEQUENCE: tuple[_CommandRunner, ...] = (
    validate_mod.run,
    index_mod.run,
    links_mod.run,
    budget_mod.run,
    staleness_mod.run,
    verify_mod.run,
    dedupe_mod.run,
    archive_mod.run,
    stats_mod.run,
)


@app.command()
def maintain(ctx: typer.Context) -> None:
    """Run the nightly set in order, then write the maintenance report."""
    state = _state(ctx)
    results = [run_fn(state.cfg, dry_run=state.dry_run) for run_fn in MAINTAIN_SEQUENCE]
    report_result = report_mod.write_report(
        state.cfg, list(results), dry_run=state.dry_run
    )
    _finish(state, [*results, report_result])


def main() -> None:
    """Console-script entry point (``memoryctl = ...cli:main``)."""
    app()
