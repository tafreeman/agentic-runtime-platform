"""Run the official SWE-bench harness from Windows, inside a Linux container.

``swebench.harness.prepare_images`` imports ``resource``, which is Unix-only,
so the harness cannot be imported on Windows at all -- not the package, not
even its constants module. Two Linux routes exist on this machine: WSL, whose
Ubuntu distro currently has an interrupted dpkg and so cannot install anything,
and a container. The container is used here because it changes nothing on the
host.

The runner image mounts the host's Docker socket, so the harness spawns its
instance containers as siblings of itself against the same daemon and the same
prebuilt images already pulled on the host.

``SweBenchDockerHarnessExecutor`` accepts ``preflight`` and ``evaluator`` as
constructor arguments exactly so the execution mechanism can be swapped without
touching how a result is interpreted. It is still the official harness
deciding; only the shell it runs in changed.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Final

RUNNER_IMAGE: Final[str] = "swebench-runner:local"
DATASET: Final[str] = "princeton-nlp/SWE-bench_Verified"
DOCKER_SOCKET: Final[str] = "/var/run/docker.sock:/var/run/docker.sock"


def _run(args: list[str], *, timeout: int) -> tuple[int, str]:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout + proc.stderr


def container_preflight() -> str | None:
    """Why the containerised harness cannot run, or None if it is ready."""
    try:
        code, out = _run(
            [
                "docker", "run", "--rm", "-v", DOCKER_SOCKET, RUNNER_IMAGE,
                "python", "-c",
                "import swebench.harness.run_evaluation, docker; "
                "docker.from_env().ping(); print('READY')",
            ],
            timeout=300,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        return f"the runner container could not start: {type(error).__name__}"
    if "READY" not in out:
        return (
            f"{RUNNER_IMAGE} is not ready (build it from the Dockerfile in this "
            f"kit, and check Docker Desktop is running): {out.strip()[-200:]}"
        )
    return None


def container_evaluator(request: Any) -> dict[str, Any]:
    """Run one instance through the official harness, in the runner container.

    Returns the harness's own per-instance report untouched. Anything that
    prevents one being produced raises, and the executor turns that into ERROR
    -- never into a verdict.
    """
    prediction = dict(request.prediction)
    instance_id = str(prediction["instance_id"])
    run_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(request.sample_id))[:60]

    with tempfile.TemporaryDirectory(prefix="swebench-work-") as tmp:
        work = Path(tmp)
        (work / "preds.json").write_text(
            json.dumps([prediction]), encoding="utf-8"
        )
        code, out = _run(
            [
                "docker", "run", "--rm",
                "-v", DOCKER_SOCKET,
                "-v", f"{work.as_posix()}:/work",
                RUNNER_IMAGE,
                "python", "-m", "swebench.harness.run_evaluation",
                "--dataset_name", DATASET,
                "--predictions_path", "/work/preds.json",
                "--max_workers", "1",
                "--run_id", run_id,
                "--instance_ids", instance_id,
                "--cache_level", "instance",
                "--timeout", "1800",
            ],
            timeout=int(request.timeout_seconds) + 600,
        )

        reports = sorted(work.rglob("report.json"))
        if not reports:
            reports = [p for p in sorted(work.rglob("*.json")) if p.name != "preds.json"]
        if not reports:
            raise RuntimeError(
                f"the harness produced no report for {instance_id} (exit {code}); "
                f"tail: {out[-600:]}"
            )
        payload = json.loads(reports[0].read_text(encoding="utf-8", errors="replace"))

    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected harness report shape for {instance_id}")

    # The harness writes {instance_id: {resolved, tests_status, ...}}. The
    # executor's default evaluator unwraps that itself, but a custom evaluator
    # hands its return value straight to the result mapper, which looks for
    # `resolved` at the top level -- so unwrap here, or every run reports
    # "no 'resolved' field" on a report that plainly has one.
    inner = payload.get(instance_id)
    if isinstance(inner, dict):
        return inner
    if "resolved" in payload:
        return payload
    raise RuntimeError(
        f"harness report for {instance_id} has no verdict; keys: {sorted(payload)[:8]}"
    )


def build_container_executor() -> Any:
    from agentic_evalkit.benchmarks.swebench_docker import SweBenchDockerHarnessExecutor

    return SweBenchDockerHarnessExecutor(
        install_hint=(
            f"build {RUNNER_IMAGE} (Dockerfile in this kit) and start Docker Desktop"
        ),
        preflight=container_preflight,
        evaluator=container_evaluator,
    )
