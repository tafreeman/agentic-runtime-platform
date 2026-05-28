"""Runtime abstractions for isolated task execution.

Provides a pluggable :class:`IsolatedTaskRuntime` interface with two
concrete implementations:

- :class:`SubprocessRuntime` (default) — runs commands in host
  subprocesses with managed temporary working directories.
- :class:`DockerRuntime` (opt-in via ``execution_profile.runtime="docker"``)
  — runs commands inside Docker containers with resource limits,
  execution timeouts, network isolation, and reliable cleanup via
  named containers.

The factory function :func:`create_runtime` selects the runtime from
an ``execution_profile`` mapping (typically sourced from YAML workflow
configuration or API request parameters).

Docker hardening defaults:
- Execution timeout: 300 s
- Memory limit: 512 MB
- CPU limit: 1.0 core
- Network isolation: enabled (``--network=none``)
- Named containers (``agentic-<uuid>``) for reliable force-kill cleanup
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

DEFAULT_DOCKER_IMAGE = "python:3.11-slim"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MEMORY_LIMIT = "512m"
DEFAULT_CPU_LIMIT = 1.0


@dataclass(slots=True)
class RuntimeExecutionResult:
    """Result from a single runtime command execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    workdir: str


class RuntimeExecutionError(RuntimeError):
    """Raised when a runtime command exits with a non-zero status."""

    def __init__(
        self,
        command: str,
        exit_code: int,
        stdout: str,
        stderr: str,
    ) -> None:
        message = (
            f"Command failed (exit code {exit_code}): {command}\n"
            f"stderr: {stderr.strip() or '<empty>'}"
        )
        super().__init__(message)
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class IsolatedTaskRuntime(ABC):
    """Abstract runtime lifecycle for command execution."""

    @abstractmethod
    async def setup(self) -> None:
        """Initialize runtime dependencies/resources."""

    @abstractmethod
    async def execute(
        self, cmd: str, workdir: Path | str | None = None
    ) -> RuntimeExecutionResult:
        """Execute a command in an isolated environment."""

    @abstractmethod
    async def collect_artifacts(self) -> dict[str, Any]:
        """Collect runtime artifacts produced during execution."""

    @abstractmethod
    async def cleanup(self) -> None:
        """Release runtime resources."""


def _host_shell_command(command: str) -> tuple[str, ...]:
    """Return host shell invocation args while still using subprocess_exec."""
    if os.name == "nt":
        return ("cmd", "/c", command)
    from agentic_v2.settings import get_settings
    shell = get_settings().shell
    return (shell, "-lc", command)


class SubprocessRuntime(IsolatedTaskRuntime):
    """Default runtime: run commands in host subprocesses."""

    def __init__(self) -> None:
        self._is_setup = False
        self._managed_workdirs: list[Path] = []
        self._executions: list[RuntimeExecutionResult] = []

    async def setup(self) -> None:
        self._is_setup = True

    async def execute(
        self, cmd: str, workdir: Path | str | None = None
    ) -> RuntimeExecutionResult:
        if not self._is_setup:
            await self.setup()

        cwd = self._resolve_workdir(workdir)
        proc = await asyncio.create_subprocess_exec(
            *_host_shell_command(cmd),
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        result = RuntimeExecutionResult(
            command=cmd,
            exit_code=int(proc.returncode or 0),
            stdout=stdout,
            stderr=stderr,
            workdir=str(cwd),
        )
        self._executions.append(result)

        if result.exit_code != 0:
            raise RuntimeExecutionError(cmd, result.exit_code, stdout, stderr)

        return result

    async def collect_artifacts(self) -> dict[str, Any]:
        return {
            "executions": [asdict(execution) for execution in self._executions],
            "workdirs": [str(path) for path in self._managed_workdirs],
        }

    async def cleanup(self) -> None:
        for path in self._managed_workdirs:
            shutil.rmtree(path, ignore_errors=True)
        self._managed_workdirs.clear()
        self._is_setup = False

    def _resolve_workdir(self, workdir: Path | str | None) -> Path:
        if workdir is not None:
            return Path(workdir)
        tmp = Path(tempfile.mkdtemp(prefix="agentic-runtime-"))
        self._managed_workdirs.append(tmp)
        return tmp


class DockerRuntime(IsolatedTaskRuntime):
    """Optional runtime: run commands inside Docker with resource limits.

    Hardening features:
    - Named containers (``agentic-<uuid>``) for reliable cleanup.
    - Execution timeout (``timeout_seconds``, default 300).
    - Memory limit (``memory_limit``, default "512m").
    - CPU limit (``cpu_limit``, default 1.0 core).
    - Network isolation (``network_disabled``, default True).
    """

    def __init__(
        self,
        container_image: str | None = None,
        timeout_seconds: int | None = None,
        memory_limit: str | None = None,
        cpu_limit: float | None = None,
        network_disabled: bool = True,
    ) -> None:
        self._container_image = container_image or DEFAULT_DOCKER_IMAGE
        self._timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self._memory_limit = memory_limit or DEFAULT_MEMORY_LIMIT
        self._cpu_limit = cpu_limit if cpu_limit is not None else DEFAULT_CPU_LIMIT
        self._network_disabled = network_disabled
        self._is_setup = False
        self._managed_workdirs: list[Path] = []
        self._executions: list[RuntimeExecutionResult] = []
        self._active_containers: list[str] = []

    @staticmethod
    def is_available() -> bool:
        return shutil.which("docker") is not None

    async def setup(self) -> None:
        if not self.is_available():
            raise RuntimeError(
                "Docker runtime requested but Docker was not found on PATH."
            )
        self._is_setup = True

    async def execute(
        self, cmd: str, workdir: Path | str | None = None
    ) -> RuntimeExecutionResult:
        if not self._is_setup:
            await self.setup()

        cwd = self._resolve_workdir(workdir)
        container_name = f"agentic-{uuid.uuid4().hex[:12]}"
        command = self._docker_command(cmd, cwd, container_name)
        self._active_containers.append(container_name)

        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            timed_out = True
            logger.warning(
                "Docker container %s exceeded %ds timeout — killing",
                container_name,
                self._timeout_seconds,
            )
            await self._kill_container(container_name)
            # Collect any partial output after kill
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=10,
                )
            except TimeoutError:
                stdout_bytes = b""
                stderr_bytes = b"<timeout: container killed>"
        finally:
            # Remove from active list — cleanup already handled by --rm or kill
            if container_name in self._active_containers:
                self._active_containers.remove(container_name)

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        exit_code = 137 if timed_out else int(proc.returncode or 0)
        result = RuntimeExecutionResult(
            command=cmd,
            exit_code=exit_code,
            stdout=stdout,
            stderr=(
                stderr
                if not timed_out
                else f"[TIMEOUT after {self._timeout_seconds}s] {stderr}"
            ),
            workdir=str(cwd),
        )
        self._executions.append(result)

        if result.exit_code != 0:
            raise RuntimeExecutionError(cmd, result.exit_code, stdout, result.stderr)

        return result

    async def collect_artifacts(self) -> dict[str, Any]:
        return {
            "container_image": self._container_image,
            "executions": [asdict(execution) for execution in self._executions],
            "workdirs": [str(path) for path in self._managed_workdirs],
        }

    async def cleanup(self) -> None:
        # Kill any still-running containers
        for name in list(self._active_containers):
            await self._kill_container(name)
        self._active_containers.clear()

        for path in self._managed_workdirs:
            shutil.rmtree(path, ignore_errors=True)
        self._managed_workdirs.clear()
        self._is_setup = False

    def _resolve_workdir(self, workdir: Path | str | None) -> Path:
        if workdir is not None:
            return Path(workdir).resolve()
        tmp = Path(tempfile.mkdtemp(prefix="agentic-runtime-docker-")).resolve()
        self._managed_workdirs.append(tmp)
        return tmp

    def _docker_command(
        self,
        cmd: str,
        workdir: Path,
        container_name: str,
    ) -> Sequence[str]:
        args: list[str] = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "-w",
            "/workspace",
            "-v",
            f"{workdir}:/workspace",
            "--memory",
            self._memory_limit,
            f"--cpus={self._cpu_limit}",
        ]
        if self._network_disabled:
            args.append("--network=none")
        args.append(self._container_image)
        if os.name == "nt":
            args.extend(["cmd", "/c", cmd])
        else:
            args.extend(["/bin/sh", "-lc", cmd])
        return args

    @staticmethod
    async def _kill_container(name: str) -> None:
        """Force-kill a running container by name, ignoring errors."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "kill",
                name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10)
        except Exception:
            logger.debug("Failed to kill container %s (may already be stopped)", name)


def create_runtime(
    execution_profile: Mapping[str, Any] | None = None,
) -> IsolatedTaskRuntime:
    """Runtime factory from execution profile settings.

    Docker-specific profile keys:
    - ``container_image``: Docker image name (default ``python:3.11-slim``).
    - ``timeout_seconds``: Per-command execution cap in seconds (default 300).
    - ``memory_limit``: Docker ``--memory`` value (default "512m").
    - ``cpu_limit``: Docker ``--cpus`` value (default 1.0).
    - ``network_disabled``: Whether to run with ``--network=none`` (default True).
    """

    profile = dict(execution_profile or {})
    runtime_name = str(profile.get("runtime", "subprocess")).strip().lower()

    if runtime_name == "subprocess":
        return SubprocessRuntime()
    if runtime_name == "docker":
        return DockerRuntime(
            container_image=profile.get("container_image"),
            timeout_seconds=profile.get("timeout_seconds"),
            memory_limit=profile.get("memory_limit"),
            cpu_limit=profile.get("cpu_limit"),
            network_disabled=profile.get("network_disabled", True),
        )

    raise ValueError(
        f"Unsupported runtime '{runtime_name}'. Expected 'subprocess' or 'docker'."
    )
