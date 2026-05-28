"""Sandbox environments for code execution.

Provides isolated environments for running untrusted code during evaluation.

Classes:
    Sandbox: Abstract base class for sandboxes.
    ExecutionResult: Result of command execution.
    LocalSubprocessSandbox: Subprocess-based sandbox (dev/test).
"""

from __future__ import annotations

from .base import ExecutionResult, Sandbox
from .local import LocalSubprocessSandbox

__all__ = [
    "ExecutionResult",
    "LocalSubprocessSandbox",
    "Sandbox",
]
