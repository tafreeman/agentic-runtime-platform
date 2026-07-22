"""Tier 0 Git operation tools - No LLM required."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ...settings import get_settings
from ...utils.path_safety import ensure_within_base
from ..base import BaseTool, ToolResult
from ..subprocess_utils import minimal_subprocess_env


def _validate_cwd(cwd: str) -> Path:
    """Resolve and validate that *cwd* is within the configured base directory.

    Mirrors ``file_ops._validate_path``: the sandbox root
    (``AGENTIC_FILE_BASE_DIR``) is read at call time via ``get_settings()``
    rather than captured at import, so a dynamic config change or
    ``monkeypatch`` of the environment is honoured by every subsequent
    validation.

    When ``AGENTIC_FILE_BASE_DIR`` is not set or empty, this function raises a
    ``ValueError`` so that every git tool fails closed. Operators must set the
    environment variable to a directory that agents are permitted to run git
    commands in.

    Raises:
        ValueError: If ``AGENTIC_FILE_BASE_DIR`` is unset/empty, or ``cwd``
            escapes the configured base directory.
    """
    file_base_dir = get_settings().agentic_file_base_dir
    if not file_base_dir:
        raise ValueError(
            "AGENTIC_FILE_BASE_DIR must be set to use git tools. "
            "Set it to the directory agents are allowed to read and write."
        )
    return ensure_within_base(cwd, file_base_dir)


async def _run_git_command(
    command: str, args: list[str] | None = None, cwd: str = "."
) -> ToolResult:
    """Run one allowlisted git subcommand and return a ``ToolResult``.

    Shared by ``GitTool`` / ``GitStatusTool`` / ``GitDiffTool`` so the
    convenience wrappers reuse this logic WITHOUT calling another
    ``BaseTool``'s ``execute`` — post-ADR-047 that would re-enter the
    structural approval gate (a latent double-consult if ``GitTool`` is ever
    gated).
    """
    try:
        # Validate command
        allowed_commands = {
            "status",
            "diff",
            "log",
            "add",
            "commit",
            "branch",
            "show",
            "rev-parse",
        }
        if command not in allowed_commands:
            return ToolResult(
                success=False,
                error=f"Command '{command}' not allowed. Allowed: {', '.join(sorted(allowed_commands))}",
            )

        # Build command
        cmd_list = ["git", command]
        if args:
            cmd_list.extend(args)

        # Containment check: reject a cwd outside the configured sandbox
        # root before any subprocess runs (ARP#2). The validated, resolved
        # path is the one executed against, so the checked path and the
        # subprocess cwd cannot diverge.
        try:
            cwd_path = _validate_cwd(cwd)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))

        # Verify working directory exists
        if not cwd_path.exists():
            return ToolResult(
                success=False, error=f"Working directory does not exist: {cwd}"
            )

        # Execute git command
        process = await asyncio.create_subprocess_exec(
            *cmd_list,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd_path),
            env=minimal_subprocess_env(),
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            return ToolResult(
                success=False,
                error=f"Git command failed (exit {process.returncode}): {stderr.decode('utf-8', errors='replace')}",
                metadata={
                    "command": command,
                    "args": args or [],
                    "exit_code": process.returncode,
                },
            )

        return ToolResult(
            success=True,
            data={
                "output": stdout.decode("utf-8", errors="replace"),
                "command": command,
                "args": args or [],
            },
            metadata={
                "exit_code": process.returncode,
                "cwd": cwd,
            },
        )
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to execute git command: {e!s}")


class GitTool(BaseTool):
    """Execute git operations (status, diff, commit, log)."""

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return (
            "General-purpose git runner: pass a `command` plus an `args` list "
            "and optional `cwd`. ALLOWLISTED commands only — status, diff, log, "
            "add, commit, branch, show, rev-parse; any other command (push, "
            "checkout, reset, …) is rejected, so this cannot mutate remotes or "
            "rewrite history. `args` are passed verbatim after the subcommand "
            "(e.g. command='log', args=['--oneline','-n','5']). Returns raw "
            "stdout; a nonzero exit is surfaced as success=False with stderr. "
            "Edge cases: a missing `cwd` fails fast. PREFER the `git_status` / "
            "`git_diff` convenience wrappers for those two common reads; reach "
            "for this generic tool when you need log, add, commit, branch, "
            "show, or rev-parse, or need to pass custom flags."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "command": {
                "type": "string",
                "description": "Git command to execute (status, diff, log, add, commit)",
                "required": True,
            },
            "args": {
                "type": "array",
                "description": "Arguments for the git command",
                "required": False,
                "default": [],
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for git command",
                "required": False,
                "default": ".",
            },
        }

    @property
    def examples(self) -> list[str]:
        return [
            "git(command='status') → Show working tree status",
            "git(command='diff', args=['HEAD']) → Show changes since HEAD",
            "git(command='log', args=['--oneline', '-n', '5']) → Show last 5 commits",
            "git(command='add', args=['file.txt']) → Stage file.txt",
            "git(command='commit', args=['-m', 'commit message']) → Create commit",
        ]

    async def execute(
        self, command: str, args: list[str] | None = None, cwd: str = "."
    ) -> ToolResult:
        """Execute git command."""
        return await _run_git_command(command, args, cwd)


class GitStatusTool(BaseTool):
    """Convenience wrapper for git status."""

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return (
            "Report the git working-tree status for `cwd`: which files are "
            "staged, modified, or untracked. Set `short=True` for the compact "
            "`--short` porcelain-style listing, else the verbose human format. "
            "Read-only convenience wrapper over `git status` (no other git "
            "subcommands). PREFER `git_status` to answer 'what has changed?' "
            "BEFORE staging or committing; prefer `git_diff` to see the actual "
            "line-level changes, or the generic `git` tool for "
            "log/add/commit/branch."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "cwd": {
                "type": "string",
                "description": "Working directory",
                "required": False,
                "default": ".",
            },
            "short": {
                "type": "boolean",
                "description": "Use short format",
                "required": False,
                "default": False,
            },
        }

    async def execute(self, cwd: str = ".", short: bool = False) -> ToolResult:
        """Execute git status."""
        args = ["--short"] if short else []
        return await _run_git_command("status", args, cwd)


class GitDiffTool(BaseTool):
    """Convenience wrapper for git diff."""

    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def description(self) -> str:
        return (
            "Show the line-level git diff for `cwd`. With no args, diffs the "
            "working tree against the index (unstaged edits). Set `cached=True` "
            "for staged-vs-HEAD (what a commit would capture), or pass `ref` "
            "(e.g. 'HEAD', a branch, or a commit sha) to diff against that "
            "reference. Read-only convenience wrapper over `git diff`. PREFER "
            "`git_diff` to inspect WHAT changed line by line; prefer "
            "`git_status` first for the high-level list of changed files, or "
            "the generic `git` tool for log/show/commit."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "ref": {
                "type": "string",
                "description": "Reference to diff against (e.g., HEAD, branch name)",
                "required": False,
                "default": None,
            },
            "cached": {
                "type": "boolean",
                "description": "Show staged changes",
                "required": False,
                "default": False,
            },
            "cwd": {
                "type": "string",
                "description": "Working directory",
                "required": False,
                "default": ".",
            },
        }

    async def execute(
        self, ref: str | None = None, cached: bool = False, cwd: str = "."
    ) -> ToolResult:
        """Execute git diff."""
        args = []
        if cached:
            args.append("--cached")
        if ref:
            args.append(ref)
        return await _run_git_command("diff", args, cwd)
