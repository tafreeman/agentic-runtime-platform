"""Tier 0 build verification tools.

Provides a deterministic build/test/smoke contract that agents can use
to verify runnable package integrity before release.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import time
from pathlib import Path
from typing import Any

from ..base import BaseTool, ToolResult
from ..subprocess_utils import minimal_subprocess_env

_PYPROJECT_TOML = "pyproject.toml"
_REQUIREMENTS_TXT = "requirements.txt"
_PACKAGE_JSON = "package.json"


def _truncate(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[truncated]"


class BuildAppTool(BaseTool):
    """Run a build verification pipeline for Python/Node projects."""

    @property
    def name(self) -> str:
        return "build_app"

    @property
    def requires_approval(self) -> bool:
        # High-impact: runs install/build/test/smoke shell commands (including a
        # create_subprocess_shell path). Gated by default — fail-closed HITL.
        return True

    @property
    def description(self) -> str:
        return (
            "Detect project stack and execute install/build/test/smoke phases "
            "with structured, machine-readable results"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "project_root": {
                "type": "string",
                "description": "Root directory of the project to verify",
                "required": True,
            },
            "stack_hint": {
                "type": "string",
                "description": "Optional stack hint: python|node|fullstack|auto",
                "required": False,
                "default": "auto",
            },
            "install_command": {
                "type": "string",
                "description": "Optional explicit install command override",
                "required": False,
            },
            "build_command": {
                "type": "string",
                "description": "Optional explicit build command override",
                "required": False,
            },
            "test_command": {
                "type": "string",
                "description": "Optional explicit test command override",
                "required": False,
            },
            "smoke_command": {
                "type": "string",
                "description": "Optional explicit smoke command override",
                "required": False,
            },
            "run_smoke": {
                "type": "boolean",
                "description": "Whether to run smoke command phase",
                "required": False,
                "default": False,
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, only plan commands and do not execute",
                "required": False,
                "default": False,
            },
            "timeout_per_step": {
                "type": "number",
                "description": "Per-phase timeout in seconds",
                "required": False,
                "default": 300,
            },
            "fail_fast": {
                "type": "boolean",
                "description": "Stop on first failed phase",
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
            "build_app(project_root='.', dry_run=True)",
            "build_app(project_root='repo', run_smoke=True, smoke_command='python -m uvicorn app:app --help')",
        ]

    # Shell metacharacters that require shell=True to work correctly
    _SHELL_METACHARS = re.compile(r"[&|;<>(){}\$`]")

    # Commands blocked from build execution (case-insensitive substring match).
    _BLOCKED_CMD_PATTERNS = [
        "rm -rf /",
        "rm -r -f /",
        ":(){ :|:& };:",
        "mkfs",
        "dd if=",
        "> /dev/sd",
        "curl ",
        "wget ",
        "nc -l",
        "ncat ",
        "/dev/tcp/",
        "perl -e",
        "ruby -e",
        "base64 -d",
        "bash -i",
        "sh -i",
    ]

    def _validate_build_command(self, command: str) -> str | None:
        """Return error string if command is blocked, else None."""
        cmd_lower = command.lower()
        for pattern in self._BLOCKED_CMD_PATTERNS:
            if pattern in cmd_lower:
                return f"Command blocked by security policy: matches '{pattern}'"
        return None

    async def _run_shell(
        self, command: str, cwd: Path, timeout: float
    ) -> dict[str, Any]:
        # Validate command before execution
        block_error = self._validate_build_command(command)
        if block_error:
            return {
                "command": command,
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": block_error,
                "duration_ms": 0.0,
            }
        started = time.perf_counter()
        needs_shell = bool(self._SHELL_METACHARS.search(command))
        if needs_shell:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=minimal_subprocess_env(),
            )
        else:
            args = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=minimal_subprocess_env(),
            )
        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await proc.communicate()
            duration_ms = (time.perf_counter() - started) * 1000
            return {
                "command": command,
                "success": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": _truncate(stdout.decode("utf-8", errors="replace")),
                "stderr": _truncate(stderr.decode("utf-8", errors="replace")),
                "duration_ms": round(duration_ms, 2),
            }
        except TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
            duration_ms = (time.perf_counter() - started) * 1000
            return {
                "command": command,
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds",
                "duration_ms": round(duration_ms, 2),
                "timeout": True,
            }

    def _detect_stack(self, root: Path, stack_hint: str) -> dict[str, Any]:
        hint = (stack_hint or "auto").lower()
        has_py = any(
            (root / name).exists()
            for name in [_PYPROJECT_TOML, _REQUIREMENTS_TXT, "setup.py"]
        )
        has_node = (root / _PACKAGE_JSON).exists()

        if hint in {"python", "node", "fullstack"}:
            detected = hint
        elif has_py and has_node:
            detected = "fullstack"
        elif has_py:
            detected = "python"
        elif has_node:
            detected = "node"
        else:
            detected = "unknown"

        return {
            "detected_stack": detected,
            "has_python_manifest": has_py,
            "has_node_manifest": has_node,
        }

    def _default_commands(
        self, root: Path, detected_stack: str
    ) -> dict[str, str | None]:
        commands: dict[str, str | None] = {
            "install": None,
            "build": None,
            "test": None,
            "smoke": None,
        }

        if detected_stack in {"python", "fullstack"}:
            self._apply_python_commands(commands, root)

        if detected_stack in {"node", "fullstack"}:
            self._apply_node_commands(commands, root, detected_stack)

        return commands

    @staticmethod
    def _apply_python_commands(commands: dict[str, str | None], root: Path) -> None:
        """Populate install/build/test commands for a Python project."""
        if (root / _REQUIREMENTS_TXT).exists():
            commands["install"] = f"python -m pip install -r {_REQUIREMENTS_TXT}"
        elif (root / _PYPROJECT_TOML).exists():
            commands["install"] = "python -m pip install -e ."
        commands["build"] = "python -m compileall -q ."
        if (root / "tests").exists() or (root / "test").exists():
            commands["test"] = "python -m pytest -q"

    @staticmethod
    def _read_npm_scripts(root: Path) -> dict[str, Any]:
        """Read the ``scripts`` table from package.json, tolerating errors."""
        pkg_path = root / _PACKAGE_JSON
        if not pkg_path.exists():
            return {}
        try:
            return json.loads(pkg_path.read_text(encoding="utf-8")).get("scripts", {})
        except Exception:
            return {}

    def _apply_node_commands(
        self, commands: dict[str, str | None], root: Path, detected_stack: str
    ) -> None:
        """Populate install/build/test commands for a Node project."""
        scripts = self._read_npm_scripts(root)
        npm_install = (
            "npm ci" if (root / "package-lock.json").exists() else "npm install"
        )

        if detected_stack == "node":
            commands["install"] = npm_install
            if "build" in scripts:
                commands["build"] = "npm run build"
            if "test" in scripts:
                commands["test"] = "npm test"
        else:
            # fullstack fallback command chain if both ecosystems are present
            py_install = commands["install"]
            commands["install"] = (
                f"{py_install} && {npm_install}" if py_install else npm_install
            )
            if "build" in scripts:
                commands["build"] = "npm run build"
            if commands["test"] and "test" in scripts:
                commands["test"] = f"{commands['test']} && npm test"
            elif "test" in scripts:
                commands["test"] = "npm test"

    async def execute(
        self,
        project_root: str,
        stack_hint: str = "auto",
        install_command: str | None = None,
        build_command: str | None = None,
        test_command: str | None = None,
        smoke_command: str | None = None,
        run_smoke: bool = False,
        dry_run: bool = False,
        timeout_per_step: float = 300.0,
        fail_fast: bool = True,
    ) -> ToolResult:
        root = Path(project_root).resolve()
        if not root.exists() or not root.is_dir():
            return ToolResult(
                success=False,
                error=f"Project root does not exist or is not a directory: {project_root}",
            )

        detection = self._detect_stack(root, stack_hint)
        defaults = self._default_commands(root, detection["detected_stack"])

        planned = self._plan_commands(
            defaults,
            install_command=install_command,
            build_command=build_command,
            test_command=test_command,
            smoke_command=smoke_command,
        )

        required_files, missing_files = self._check_required_files(
            root, detection["detected_stack"]
        )

        phase_order = ["install", "build", "test"] + (["smoke"] if run_smoke else [])

        if dry_run:
            return self._build_dry_run_result(
                root, detection, planned, required_files, missing_files, phase_order
            )

        phase_results = await self._execute_phases(
            phase_order, planned, root, timeout_per_step, fail_fast
        )

        failed_phases = [
            name
            for name, info in phase_results.items()
            if not info.get("success", False)
        ]
        ready = not missing_files and not failed_phases

        return ToolResult(
            success=ready,
            data={
                "project_root": str(root),
                **detection,
                "required_files": required_files,
                "missing_files": missing_files,
                "planned_commands": planned,
                "phase_results": phase_results,
                "failed_phases": failed_phases,
                "ready_for_release": ready,
                "dry_run": False,
            },
            metadata={
                "contract_version": "build_app_v1",
                "retryable": bool(failed_phases),
            },
        )

    @staticmethod
    def _plan_commands(
        defaults: dict[str, str | None],
        *,
        install_command: str | None,
        build_command: str | None,
        test_command: str | None,
        smoke_command: str | None,
    ) -> dict[str, str | None]:
        """Merge explicit command overrides with detected defaults."""
        return {
            "install": (
                install_command
                if install_command is not None
                else defaults.get("install")
            ),
            "build": (
                build_command if build_command is not None else defaults.get("build")
            ),
            "test": test_command if test_command is not None else defaults.get("test"),
            "smoke": (
                smoke_command if smoke_command is not None else defaults.get("smoke")
            ),
        }

    @staticmethod
    def _check_required_files(
        root: Path, detected_stack: str
    ) -> tuple[list[str], list[str]]:
        """Return (required_files, missing_files) for the detected stack."""
        required_files: list[str] = []
        missing_files: list[str] = []
        if detected_stack in {"python", "fullstack"}:
            required_files.append(f"{_REQUIREMENTS_TXT}|{_PYPROJECT_TOML}|setup.py")
            if not (
                (root / _REQUIREMENTS_TXT).exists()
                or (root / _PYPROJECT_TOML).exists()
                or (root / "setup.py").exists()
            ):
                missing_files.append("python manifest")
        if detected_stack in {"node", "fullstack"}:
            required_files.append(_PACKAGE_JSON)
            if not (root / _PACKAGE_JSON).exists():
                missing_files.append(_PACKAGE_JSON)
        return required_files, missing_files

    @staticmethod
    def _build_dry_run_result(
        root: Path,
        detection: dict[str, Any],
        planned: dict[str, str | None],
        required_files: list[str],
        missing_files: list[str],
        phase_order: list[str],
    ) -> ToolResult:
        """Build the ToolResult for a dry-run (plan-only) invocation."""
        phase_results: dict[str, Any] = {}
        for phase in phase_order:
            cmd = planned.get(phase)
            phase_results[phase] = {
                "command": cmd,
                "skipped": True,
                "reason": "dry_run" if cmd else "no_command",
                "success": True,
            }
        ready = not missing_files and all(
            phase_results[p]["success"] for p in phase_results
        )
        return ToolResult(
            success=ready,
            data={
                "project_root": str(root),
                **detection,
                "required_files": required_files,
                "missing_files": missing_files,
                "planned_commands": planned,
                "phase_results": phase_results,
                "ready_for_release": ready,
                "dry_run": True,
            },
            metadata={"contract_version": "build_app_v1"},
        )

    async def _execute_phases(
        self,
        phase_order: list[str],
        planned: dict[str, str | None],
        root: Path,
        timeout_per_step: float,
        fail_fast: bool,
    ) -> dict[str, Any]:
        """Run each planned phase command, honoring fail-fast semantics."""
        phase_results: dict[str, Any] = {}
        for phase in phase_order:
            cmd = planned.get(phase)
            if not cmd:
                phase_results[phase] = {
                    "command": None,
                    "skipped": True,
                    "reason": "no_command",
                    "success": True,
                }
                continue

            result = await self._run_shell(cmd, root, timeout_per_step)
            phase_results[phase] = result

            if fail_fast and not result["success"]:
                break
        return phase_results
