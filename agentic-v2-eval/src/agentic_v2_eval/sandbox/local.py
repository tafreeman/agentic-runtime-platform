"""Local subprocess sandbox for code execution.

Provides a lightweight, no-Docker sandbox that runs commands via
``subprocess.run`` inside a temporary (or user-specified) directory.
Includes a configurable command blocklist for safe mode, path-escape
prevention, and automatic cleanup.

Suitable for development and testing; use a container-based sandbox
for production isolation.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from types import TracebackType

from .base import ExecutionResult, Sandbox

# Commands that are blocked in safe mode
BLOCKED_COMMANDS = frozenset(
    {
        "rm",
        "rmdir",
        "del",
        "format",
        "mkfs",
        "dd",
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
        "init",
        "kill",
        "killall",
        "pkill",
        "taskkill",
        ":(){",  # fork bomb pattern
        "curl",
        "wget",
        "nc",
        "netcat",
    }
)


class LocalSubprocessSandbox(Sandbox):
    """Subprocess-based sandbox for local code execution.

    Features:
    - Runs in a temporary directory (auto-cleaned on close)
    - Configurable timeout and resource limits
    - Optional safe mode blocks dangerous commands
    - Cross-platform (Windows/Linux/macOS)

    Example:
        >>> with LocalSubprocessSandbox() as sandbox:
        ...     sandbox.write_file("hello.py", "print('Hello')")
        ...     result = sandbox.run_command(["python", "hello.py"])
        ...     print(result.stdout)
        Hello
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        timeout: int = 30,
        safe_mode: bool = True,
        env: dict[str, str] | None = None,
    ):
        """Initialize sandbox.

        Args:
            root_dir: Root directory for sandbox. If None, creates a temp dir.
            timeout: Default timeout in seconds for commands.
            safe_mode: If True, blocks dangerous commands.
            env: Base environment variables (merged with system env).
        """
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None

        if root_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="agentic_sandbox_")
            self._root = Path(self._temp_dir.name)
        else:
            self._root = Path(root_dir)
            self._root.mkdir(parents=True, exist_ok=True)

        self.timeout = timeout
        self.safe_mode = safe_mode
        self._base_env = env or {}

    @property
    def root(self) -> Path:
        """Get the sandbox root directory."""
        return self._root

    def _get_env(self, extra_env: dict[str, str] | None = None) -> dict[str, str]:
        """Build environment dict for subprocess."""
        env = os.environ.copy()
        env.update(self._base_env)
        if extra_env:
            env.update(extra_env)
        return env

    def _check_command_safety(self, command: list[str]) -> str | None:
        """Check if command is allowed in safe mode.

        Returns error message if blocked, None if allowed.
        """
        if not self.safe_mode:
            return None

        if not command:
            return "Empty command"

        cmd_name = Path(command[0]).name.lower()

        # Check against blocklist
        if cmd_name in BLOCKED_COMMANDS:
            return f"Command '{cmd_name}' is blocked in safe mode"

        # Check for dangerous patterns in arguments
        full_cmd = " ".join(command).lower()
        for pattern in BLOCKED_COMMANDS:
            if pattern in full_cmd:
                return f"Pattern '{pattern}' is blocked in safe mode"

        return None

    def run_command(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Run a command in the sandbox.

        Args:
            command: Command and arguments list.
            cwd: Working directory relative to sandbox root.
            timeout: Timeout in seconds (overrides default).
            env: Extra environment variables.

        Returns:
            ExecutionResult with exit code, stdout, stderr, duration.
        """
        # Safety check
        if error := self._check_command_safety(command):
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=0,
                error=error,
            )

        # Resolve working directory
        work_dir = self._root
        if cwd:
            work_dir = self._root / cwd
            if not work_dir.exists():
                work_dir.mkdir(parents=True, exist_ok=True)

        # Ensure work_dir is within sandbox root
        try:
            work_dir.resolve().relative_to(self._root.resolve())
        except ValueError:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=0,
                error=f"Working directory escapes sandbox: {cwd}",
            )

        effective_timeout = timeout if timeout is not None else self.timeout

        start = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                cwd=str(work_dir),
                env=self._get_env(env),
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
            duration_ms = (time.perf_counter() - start) * 1000

            return ExecutionResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=duration_ms,
            )

        except subprocess.TimeoutExpired:
            duration_ms = (time.perf_counter() - start) * 1000
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                error=f"Command timed out after {effective_timeout}s",
            )

        except FileNotFoundError:
            duration_ms = (time.perf_counter() - start) * 1000
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                error=f"Command not found: {command[0]}",
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                error=str(e),
            )

    def write_file(self, path: str, content: str) -> None:
        """Write content to a file in the sandbox.

        Args:
            path: Relative path within sandbox.
            content: File content.

        Raises:
            ValueError: If path escapes sandbox.
        """
        file_path = self._root / path

        # Security check
        try:
            file_path.resolve().relative_to(self._root.resolve())
        except ValueError:
            raise ValueError(f"Path escapes sandbox: {path}") from None

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def read_file(self, path: str) -> str:
        """Read content from a file in the sandbox.

        Args:
            path: Relative path within sandbox.

        Returns:
            File content.

        Raises:
            ValueError: If path escapes sandbox.
            FileNotFoundError: If file doesn't exist.
        """
        file_path = self._root / path

        # Security check
        try:
            file_path.resolve().relative_to(self._root.resolve())
        except ValueError:
            raise ValueError(f"Path escapes sandbox: {path}") from None

        return file_path.read_text(encoding="utf-8")

    def exists(self, path: str) -> bool:
        """Check if a path exists in the sandbox."""
        file_path = self._root / path
        try:
            file_path.resolve().relative_to(self._root.resolve())
        except ValueError:
            return False
        return file_path.exists()

    def cleanup(self) -> None:
        """Clean up the sandbox directory."""
        if self._temp_dir:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def __enter__(self) -> LocalSubprocessSandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.cleanup()

    def __del__(self) -> None:
        self.cleanup()
