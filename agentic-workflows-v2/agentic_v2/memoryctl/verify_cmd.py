"""Execute machine-runnable ``verify:`` commands from topic frontmatter.

Design doc §5.1/§6: memories are hypotheses (P5). Every topic file whose
frontmatter carries a ``verify`` command other than ``manual`` is executed
deterministically and the pass/fail outcome is recorded as a finding; only
failures need LLM interpretation downstream. Files without a ``verify`` key
(or marked ``manual``) are counted in the summary only. This command never
mutates files.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from collections import Counter
from pathlib import Path

from agentic_v2.memoryctl._shared import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    VERIFY_MANUAL,
    CommandResult,
    Finding,
    MemoryctlConfig,
    discover_memory_files,
    load_memory_doc,
)

COMMAND_NAME = "verify"
CODE_PASS = "verify.pass"
CODE_FAIL = "verify.fail"
CODE_TIMEOUT = "verify.timeout"
CODE_WOULD_RUN = "verify.would-run"
STDERR_TAIL_CHARS = 300


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Run every runnable ``verify:`` command and report pass/fail/timeout.

    With ``dry_run`` the commands are listed as ``verify.would-run``
    findings and nothing is executed. Read-only either way.
    """
    findings: list[Finding] = []
    manual_count = 0
    for memory_dir in cfg.memory_dirs:
        for path in discover_memory_files(memory_dir, cfg.index_name):
            doc = load_memory_doc(path)
            raw = doc.meta.get("verify")
            if raw is None or str(raw).strip() == VERIFY_MANUAL:
                manual_count += 1
                continue
            command = str(raw)
            if dry_run:
                findings.append(_would_run_finding(command, path))
                continue
            findings.append(_execute_verify(command, path, cfg.verify_timeout_s))
    summary = _summarize(findings, manual_count, dry_run=dry_run)
    return CommandResult(
        name=COMMAND_NAME, findings=tuple(findings), changed=(), summary=summary
    )


def _would_run_finding(command: str, path: Path) -> Finding:
    """Dry-run placeholder finding for one verify command."""
    return Finding(
        code=CODE_WOULD_RUN,
        severity=SEVERITY_INFO,
        message=f"would run: {command}",
        path=path,
        data={"command": command},
    )


def _spawn_shell(command: str) -> subprocess.Popen[str]:
    """Start one verify command's shell.

    shell=True is required and intentional: verify commands are
    user-authored shell snippets in the same trust domain as hooks
    (design doc §4.1) — configuration, not external input. On POSIX the
    shell gets its own session so a timeout can kill the whole process
    group, not just the shell; on Windows ``Popen.kill`` terminates the
    shell only (grandchildren are not tracked — accepted limitation).
    """
    if sys.platform == "win32":
        return subprocess.Popen(  # noqa: S602
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    return subprocess.Popen(  # noqa: S602
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    """Kill a timed-out verify process — on POSIX, its whole group."""
    if sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        return
    proc.kill()


def _execute_verify(command: str, path: Path, timeout_s: int) -> Finding:
    """Execute one verify command and map its outcome to a finding."""
    proc = _spawn_shell(command)
    try:
        _stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.communicate()
        return Finding(
            code=CODE_TIMEOUT,
            severity=SEVERITY_ERROR,
            message=f"verify timed out after {timeout_s}s: {command}",
            path=path,
            data={"command": command, "timeout_s": timeout_s},
        )
    if proc.returncode == 0:
        return Finding(
            code=CODE_PASS,
            severity=SEVERITY_INFO,
            message=f"verified: {command}",
            path=path,
            data={"command": command},
        )
    stderr_tail = (stderr or "")[-STDERR_TAIL_CHARS:]
    return Finding(
        code=CODE_FAIL,
        severity=SEVERITY_ERROR,
        message=f"verify failed (exit {proc.returncode}): {command}",
        path=path,
        data={
            "command": command,
            "returncode": proc.returncode,
            "stderr_tail": stderr_tail,
        },
    )


def _summarize(findings: list[Finding], manual_count: int, *, dry_run: bool) -> str:
    """One-line summary with the manual/unset count (info-only per spec)."""
    counts = Counter(f.code for f in findings)
    if dry_run:
        return (
            f"verify (dry-run): would run {counts[CODE_WOULD_RUN]} command(s); "
            f"{manual_count} manual/unset"
        )
    return (
        f"verify: {counts[CODE_PASS]} pass, {counts[CODE_FAIL]} fail, "
        f"{counts[CODE_TIMEOUT]} timeout, {manual_count} manual/unset"
    )
