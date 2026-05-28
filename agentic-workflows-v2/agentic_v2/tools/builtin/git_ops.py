"""Tier 0 Git operation tools - No LLM required."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..base import BaseTool, ToolResult
from ..subprocess_utils import minimal_subprocess_env


class GitTool(BaseTool):
    """Execute git operations (status, diff, commit, log)."""

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return "Execute git operations like status, diff, commit, log, add"

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

            # Verify working directory exists
            cwd_path = Path(cwd)
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
            return ToolResult(
                success=False, error=f"Failed to execute git command: {e!s}"
            )


class GitStatusTool(BaseTool):
    """Convenience wrapper for git status."""

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return "Get the current git working tree status"

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
        git_tool = GitTool()
        args = ["--short"] if short else []
        return await git_tool.execute(command="status", args=args, cwd=cwd)


class GitDiffTool(BaseTool):
    """Convenience wrapper for git diff."""

    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def description(self) -> str:
        return "Show changes between commits, commit and working tree, etc"

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
        git_tool = GitTool()
        args = []
        if cached:
            args.append("--cached")
        if ref:
            args.append(ref)
        return await git_tool.execute(command="diff", args=args, cwd=cwd)
