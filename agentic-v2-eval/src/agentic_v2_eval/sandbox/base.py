"""Abstract sandbox interface for isolated code execution.

Defines :class:`Sandbox` (the abstract base) and :class:`ExecutionResult`
(a structured return type capturing exit code, output streams, timing,
and error information).  Concrete implementations (e.g.
:class:`~agentic_v2_eval.sandbox.local.LocalSubprocessSandbox`) provide
the actual execution backend.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    """Structured result of a sandboxed command execution.

    Attributes:
        exit_code: Process exit code (0 = success, -1 = sandbox error).
        stdout: Captured standard output.
        stderr: Captured standard error.
        duration_ms: Wall-clock execution time in milliseconds.
        error: Human-readable error message if the sandbox itself failed
            (timeout, blocked command, path escape, etc.).
    """

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.exit_code == 0 and not self.error


class Sandbox(abc.ABC):
    """Abstract base class for code execution sandboxes.

    Concrete implementations must provide command execution, file
    writing, and file reading within an isolated filesystem root.
    """

    @abc.abstractmethod
    def run_command(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Run a command in the sandbox.

        Args:
            command: Command and arguments list
            cwd: Working directory (relative to sandbox root)
            timeout: Timeout in seconds
            env: Environment variables

        Returns:
            ExecutionResult
        """
        pass

    @abc.abstractmethod
    def write_file(self, path: str, content: str) -> None:
        """Write content to a file in the sandbox."""
        pass

    @abc.abstractmethod
    def read_file(self, path: str) -> str:
        """Read content from a file in the sandbox."""
        pass
