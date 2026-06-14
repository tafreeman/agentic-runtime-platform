"""Checkpoint ``--resume`` + ``fork_session`` + changed-file detection.

Demonstrates the ARP counterparts to the Claude Agent SDK's session resume and
``fork_session`` primitives, built on the existing
:meth:`~agentic_v2.engine.ExecutionContext.save_checkpoint` /
``restore_checkpoint`` machinery (see
``docs/adr/ADR-026-resume-vs-summary-session.md``):

* **Save a checkpoint** that fingerprints a set of tracked files.
* **Resume** it into a fresh context and **detect which files changed** since,
  injecting a "these files changed" notice into the resumed prompt.
* **Fork** a divergent run off the shared baseline via ``fork_session`` so an
  experiment never mutates the original.

No API key required — this is pure context/state machinery.

Usage::

    python examples/resume_and_fork.py demo        # full round-trip walkthrough
    python examples/resume_and_fork.py --resume <name> [--checkpoint-dir DIR]
    python examples/resume_and_fork.py --fork <name>   # resume <name>, then fork
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from agentic_v2.engine import ExecutionContext

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("resume_and_fork")


async def _demo() -> None:
    """Walk through save -> mutate-a-file -> resume -> fork end to end."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        checkpoint_dir = root / "checkpoints"

        # A file the run depends on (e.g. a config the agent read).
        tracked = root / "config.txt"
        tracked.write_text("max_retries = 3\n")

        # 1. Run some work and checkpoint it, fingerprinting the tracked file.
        ctx = ExecutionContext(checkpoint_dir=checkpoint_dir)
        await ctx.set("plan", ["analyze", "fix", "verify"])
        await ctx.mark_step_complete("analyze")
        path = await ctx.save_checkpoint("demo_run", tracked_files=[tracked])
        logger.info("Saved checkpoint: %s", path.name)

        # 2. Something changes the file out-of-band between sessions.
        tracked.write_text("max_retries = 10\n")
        logger.info("Edited %s on disk after the checkpoint", tracked.name)

        # 3. Resume into a fresh context.
        resumed = ExecutionContext(checkpoint_dir=checkpoint_dir)
        await resumed.restore_checkpoint(path)
        logger.info(
            "Resumed: completed=%s plan=%s",
            resumed.completed_steps,
            await resumed.get("plan"),
        )

        # 4. Detect changed files and build the prompt notice.
        changed = ExecutionContext.detect_changed_files(path)
        notice = ExecutionContext.build_changed_files_notice(changed)
        logger.info("\n%s", notice or "(no files changed)")

        # 5. Fork a divergent experiment off the shared baseline.
        fork = resumed.fork_session("experiment_higher_retries")
        await fork.set("plan", ["analyze", "fix", "verify", "stress_test"])
        logger.info(
            "Fork run_id=%s forked_from=%s; baseline plan unchanged=%s",
            fork.run_id,
            fork.metadata.get("forked_from_run"),
            await resumed.get("plan"),
        )


async def _resume(name: str, checkpoint_dir: Path) -> int:
    """Resume a named checkpoint and print the changed-file notice."""
    path = checkpoint_dir / f"{name}.json"
    if not path.exists():
        logger.error("Checkpoint not found: %s", path)
        return 1
    ctx = ExecutionContext(checkpoint_dir=checkpoint_dir)
    await ctx.restore_checkpoint(path)
    logger.info(
        "Resumed %s: completed=%s failed=%s",
        name,
        ctx.completed_steps,
        ctx.failed_steps,
    )
    notice = ExecutionContext.build_changed_files_notice(
        ExecutionContext.detect_changed_files(path)
    )
    logger.info("%s", notice or "No tracked files changed.")
    return 0


async def _resume_and_fork(name: str, checkpoint_dir: Path) -> int:
    """Resume a named checkpoint, then branch a divergent fork off the baseline.

    Mirrors :func:`_resume` but follows it with ``fork_session`` so an
    experiment can diverge from the restored baseline without mutating it.
    """
    path = checkpoint_dir / f"{name}.json"
    if not path.exists():
        logger.error("Checkpoint not found: %s", path)
        return 1
    ctx = ExecutionContext(checkpoint_dir=checkpoint_dir)
    await ctx.restore_checkpoint(path)
    logger.info(
        "Resumed %s: completed=%s failed=%s",
        name,
        ctx.completed_steps,
        ctx.failed_steps,
    )

    fork = ctx.fork_session(f"{name}_fork")
    logger.info(
        "Forked '%s' run_id=%s forked_from=%s (baseline run %s untouched)",
        fork.metadata.get("fork_name"),
        fork.run_id,
        fork.metadata.get("forked_from_run"),
        ctx.run_id,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the example."""
    args = argv if argv is not None else sys.argv[1:]
    checkpoint_dir = Path(".agentic_checkpoints")
    if "--checkpoint-dir" in args:
        i = args.index("--checkpoint-dir")
        checkpoint_dir = Path(args[i + 1])
        args = args[:i] + args[i + 2 :]

    if args and args[0] == "--resume":
        return asyncio.run(_resume(args[1], checkpoint_dir))

    if args and args[0] == "--fork":
        return asyncio.run(_resume_and_fork(args[1], checkpoint_dir))

    asyncio.run(_demo())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
