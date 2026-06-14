"""Tier 0 Shell execution tools - No LLM required."""

from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path
from typing import Any

from ..base import BaseTool, ToolResult
from ..subprocess_utils import minimal_subprocess_env

_SHELL_METACHARS = frozenset({"|", "&", ";", "<", ">", "`", "$(", "${", "\n", "\r"})
_DANGEROUS_COMMANDS = frozenset({"rm", "del", "rmdir", "format", "mkfs"})
_WINDOWS_EXECUTABLE_SUFFIXES = frozenset({".exe", ".bat", ".cmd", ".com"})
# Commands that are unconditionally dangerous — blocked regardless of arguments.
_UNCONDITIONALLY_BLOCKED_COMMANDS = frozenset({"format", "mkfs"})
# Flags that indicate recursive or forced deletion on file-removal commands.
_DANGEROUS_RECURSIVE_FLAGS = frozenset({
    "-r", "-rf", "-fr", "-R", "-Rf", "-fR", "--recursive",
    "/s",  # Windows: rmdir /s, del /s
})


def _split_command(command: str) -> list[str]:
    """Return argv for a simple command while refusing shell syntax."""
    if any(token in command for token in _SHELL_METACHARS):
        raise ValueError(
            "Shell metacharacters are not supported; use shell_exec args instead"
        )
    return shlex.split(command, posix=os.name != "nt")


def _load_shell_allowlist() -> frozenset[str] | None:
    """Return the set of allowed command basenames, or None if env var is
    unset/empty."""
    raw = os.environ.get("AGENTIC_SHELL_ALLOWED_COMMANDS", "").strip()
    if not raw:
        return None
    return frozenset(_command_name(name) for name in raw.split(",") if name.strip())


def _command_name(program: str) -> str:
    """Return the normalized executable basename used for policy checks."""
    name = Path(program.strip()).name.lower()
    suffix = Path(name).suffix
    if suffix in _WINDOWS_EXECUTABLE_SUFFIXES:
        return name[: -len(suffix)]
    return name


def _shell_policy_error(program: str, args: list[str] | None = None) -> str | None:
    """Return a policy error for disallowed shell execution, if any."""
    if not program.strip():
        return "Command must not be empty"

    exe = _command_name(program)
    if not exe:
        return "Command must not be empty"

    if exe in _UNCONDITIONALLY_BLOCKED_COMMANDS:
        return f"Dangerous shell command blocked: {exe}"

    lowered_args = [arg.lower() for arg in args or []]
    if exe in _DANGEROUS_COMMANDS and (
        any(arg in _DANGEROUS_RECURSIVE_FLAGS for arg in lowered_args)
        or "/" in lowered_args   # bare filesystem root, e.g. rm /
        or "\\" in lowered_args  # bare Windows root, e.g. rmdir \
    ):
        return f"Dangerous shell command blocked: {exe}"

    allowed = _load_shell_allowlist()
    if allowed is None:
        return (
            "Shell commands are disabled. "
            "Set AGENTIC_SHELL_ALLOWED_COMMANDS to a comma-separated list "
            "of permitted command names (e.g. 'ls,cat,python')."
        )

    if exe not in allowed:
        return (
            f"Command '{exe}' is not in the shell allowlist. "
            f"Add it to AGENTIC_SHELL_ALLOWED_COMMANDS to permit it."
        )

    return None


class ShellTool(BaseTool):
    """Execute shell commands securely."""

    @property
    def name(self) -> str:
        return "shell"

    @property
    def requires_approval(self) -> bool:
        # High-impact: arbitrary command execution. Gated by default.
        return True

    @property
    def description(self) -> str:
        return (
            "Run a single shell `command` STRING (e.g. 'ls -la | grep py') with "
            "security controls and captured stdout/stderr, plus optional `cwd`, "
            "`timeout` (default 60s), and `capture_output`. The command is "
            "parsed as a shell line, so it supports pipes/operators but is "
            "subject to a denylist that blocks dangerous patterns. Requires "
            "approval (arbitrary execution). Returns stdout, stderr, and exit "
            "code; a nonzero exit or timeout is a failure result. PREFER "
            "`shell` when you genuinely need shell features (a pipeline, glob, "
            "or redirect); PREFER `shell_exec` when you have a fixed program "
            "plus a list of arguments — it skips shell parsing and escapes "
            "args, avoiding quoting/injection pitfalls."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
                "required": True,
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for command execution",
                "required": False,
                "default": ".",
            },
            "timeout": {
                "type": "number",
                "description": "Command timeout in seconds",
                "required": False,
                "default": 60,
            },
            "capture_output": {
                "type": "boolean",
                "description": "Whether to capture stdout/stderr",
                "required": False,
                "default": True,
            },
        }

    @property
    def tier(self) -> int:
        return 0

    @property
    def examples(self) -> list[str]:
        return [
            "shell(command='ls -la') → List directory contents",
            "shell(command='echo hello') → Echo a string",
            "shell(command='python --version') → Check Python version",
        ]

    async def execute(
        self,
        command: str,
        cwd: str = ".",
        timeout: float = 60.0,
        capture_output: bool = True,
    ) -> ToolResult:
        """Execute shell command."""
        try:
            try:
                cmd_list = _split_command(command)
            except ValueError as exc:
                return ToolResult(success=False, error=str(exc))

            policy_error = _shell_policy_error(
                cmd_list[0] if cmd_list else "", cmd_list[1:]
            )
            if policy_error is not None:
                return ToolResult(success=False, error=policy_error)

            # Verify working directory
            cwd_path = Path(cwd)
            if not cwd_path.exists():
                return ToolResult(
                    success=False, error=f"Working directory does not exist: {cwd}"
                )

            # ``echo`` is a shell builtin on Windows. Keep ShellTool shell-free
            # while preserving the cross-platform test/dev contract.
            exe = _command_name(cmd_list[0])
            if os.name == "nt" and exe == "echo":
                if capture_output:
                    return ToolResult(
                        success=True,
                        data={
                            "stdout": " ".join(cmd_list[1:]) + "\n",
                            "stderr": "",
                            "exit_code": 0,
                            "command": command,
                        },
                        metadata={
                            "cwd": cwd,
                            "timeout": timeout,
                        },
                    )
                return ToolResult(
                    success=True,
                    data={
                        "pid": None,
                        "command": command,
                        "message": "Command completed (output not captured)",
                    },
                    metadata={"cwd": cwd},
                )

            # Execute command without a shell so user input cannot be reinterpreted.
            if capture_output:
                process = await asyncio.create_subprocess_exec(
                    *cmd_list,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(cwd_path),
                    env=minimal_subprocess_env(),
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=timeout
                    )

                    stdout_str = stdout.decode("utf-8", errors="replace")
                    stderr_str = stderr.decode("utf-8", errors="replace")

                    return ToolResult(
                        success=process.returncode == 0,
                        data={
                            "stdout": stdout_str,
                            "stderr": stderr_str,
                            "exit_code": process.returncode,
                            "command": command,
                        },
                        metadata={
                            "cwd": cwd,
                            "timeout": timeout,
                        },
                    )

                except TimeoutError:
                    process.kill()
                    await process.wait()
                    return ToolResult(
                        success=False,
                        error=f"Command timed out after {timeout} seconds",
                        metadata={"command": command, "timeout": timeout},
                    )

            else:
                # Fire and forget mode
                process = await asyncio.create_subprocess_exec(
                    *cmd_list,
                    cwd=str(cwd_path),
                    env=minimal_subprocess_env(),
                )

                return ToolResult(
                    success=True,
                    data={
                        "pid": process.pid,
                        "command": command,
                        "message": "Command started (output not captured)",
                    },
                    metadata={"cwd": cwd},
                )

        except Exception as e:
            return ToolResult(
                success=False, error=f"Failed to execute shell command: {e!s}"
            )


class ShellExecTool(BaseTool):
    """Execute shell commands with automatic argument escaping."""

    @property
    def name(self) -> str:
        return "shell_exec"

    @property
    def requires_approval(self) -> bool:
        # High-impact: arbitrary program execution. Gated by default.
        return True

    @property
    def description(self) -> str:
        return (
            "Run a `program` with an explicit `args` LIST and NO shell parsing — "
            "each argument is passed verbatim, so spaces, quotes, and special "
            "characters in args are never re-interpreted (the injection-safe "
            "way to run a command). Optional `cwd` and `timeout` (default 60s). "
            "Because there is no shell, pipes/globs/redirects do NOT work here. "
            "Requires approval. Returns stdout, stderr, and exit code. PREFER "
            "`shell_exec` for a known program + arguments (e.g. "
            "program='git', args=['commit','-m','my message']); PREFER `shell` "
            "only when you actually need a pipeline or shell expansion."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "program": {
                "type": "string",
                "description": "Program/command to execute",
                "required": True,
            },
            "args": {
                "type": "array",
                "description": "Arguments to pass to the program",
                "required": False,
                "default": [],
            },
            "cwd": {
                "type": "string",
                "description": "Working directory",
                "required": False,
                "default": ".",
            },
            "timeout": {
                "type": "number",
                "description": "Command timeout in seconds",
                "required": False,
                "default": 60,
            },
        }

    async def execute(
        self,
        program: str,
        args: list[str] | None = None,
        cwd: str = ".",
        timeout: float = 60.0,
    ) -> ToolResult:
        """Execute command with escaped arguments."""
        try:
            cwd_path = Path(cwd)
            if not cwd_path.exists():
                return ToolResult(
                    success=False, error=f"Working directory does not exist: {cwd}"
                )

            cmd_list = [program]
            if args:
                cmd_list.extend(args)

            policy_error = _shell_policy_error(program, args)
            if policy_error is not None:
                return ToolResult(success=False, error=policy_error)

            process = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd_path),
                env=minimal_subprocess_env(),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )

                return ToolResult(
                    success=process.returncode == 0,
                    data={
                        "stdout": stdout.decode("utf-8", errors="replace"),
                        "stderr": stderr.decode("utf-8", errors="replace"),
                        "exit_code": process.returncode,
                        "program": program,
                        "args": args or [],
                    },
                    metadata={"cwd": cwd},
                )

            except TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False, error=f"Command timed out after {timeout} seconds"
                )

        except Exception as e:
            return ToolResult(success=False, error=f"Failed to execute command: {e!s}")
