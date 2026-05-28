"""Workspace-wide test runner for all monorepo packages.

Runs pytest sequentially across all three packages and reports per-package
pass/fail with a final summary.  Sequential execution keeps output readable
and avoids resource contention on low-RAM dev machines.
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Optional

_REPO_ROOT = pathlib.Path(__file__).parents[4]

PACKAGES: list[dict] = [
    {
        "name": "agentic-workflows-v2",
        "path": str(_REPO_ROOT / "agentic-workflows-v2"),
        "src": "agentic_v2",
        "test_dir": "tests",
    },
    {
        "name": "agentic-v2-eval",
        "path": str(_REPO_ROOT / "agentic-v2-eval"),
        "src": "agentic_v2_eval",
        "test_dir": "tests",
    },
    {
        "name": "tools",
        "path": str(_REPO_ROOT / "tools"),
        "src": "tools",
        "test_dir": "tests",
    },
]


def run_package_tests(
    package: dict,
    *,
    extra_args: list[str] | None = None,
) -> tuple[bool, str]:
    """Run pytest for *package* and return (passed, combined_output)."""
    cmd = ["uv", "run", "pytest", package["test_dir"], "-q", "--tb=short"]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(
        cmd,
        cwd=package["path"],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def run_all(
    *,
    skip_integration: bool = True,
    coverage: bool = False,
    package_filter: Optional[str] = None,
) -> bool:
    """Run tests for all (or one) packages; return True if all passed."""
    from rich.console import Console

    console = Console()

    extra_args: list[str] = []
    if skip_integration:
        extra_args += ["-m", "not integration"]

    packages = (
        [p for p in PACKAGES if p["name"] == package_filter]
        if package_filter
        else PACKAGES
    )

    failed: list[str] = []

    for pkg in packages:
        pkg_args = list(extra_args)
        if coverage:
            pkg_args += [
                f"--cov={pkg['src']}",
                "--cov-report=term-missing",
            ]

        console.print(f"\n[bold]\\[{pkg['name']}][/bold] Running tests...")
        passed, output = run_package_tests(pkg, extra_args=pkg_args or None)

        if passed:
            # Extract summary line (last non-empty line from pytest -q output)
            summary = next(
                (ln for ln in reversed(output.splitlines()) if ln.strip()),
                "passed",
            )
            console.print(f"  [green]OK[/green]  {summary}")
        else:
            failed.append(pkg["name"])
            console.print("  [red]!![/red]  FAILED")
            for line in output.splitlines():
                console.print(f"    {line}")

    console.print("")
    if failed:
        console.print(
            f"[red]SUMMARY:[/red] {len(failed)}/{len(packages)} package(s) failed"
        )
        for name in failed:
            console.print(f"  [red]!![/red]  {name}")
        return False

    console.print(
        f"[green]SUMMARY:[/green] all {len(packages)} package(s) passed"
    )
    return True
