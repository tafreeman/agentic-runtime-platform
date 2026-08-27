"""Run one arm of the SWE-fix A/B through EvalKit's Python API.

Runs in EvalKit's virtualenv. Imports ``agentic_evalkit`` only -- ARP is
reached as a subprocess (``bridge.py``), never as an import, so the one-way
dependency boundary holds in both directions.

The child environment is built by *removing* every paid-provider credential.
That is not a policy note, it is the enforcement: ARP's tier fallback chain
will still list paid models as candidates, and without a key in the
environment those candidates cannot be called at all. A run that finishes is
therefore free by construction, not by promise.

Usage (from EvalKit's checkout, so ``uv run`` resolves the right venv):
    uv run python <kit>/run_ab.py --arm a --limit 3
    uv run python <kit>/run_ab.py --arm b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

KIT_ROOT = Path(__file__).resolve().parent
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from agentic_evalkit.artifacts import ArtifactStore  # noqa: E402
from agentic_evalkit.datasets.local import LocalDatasetProvider  # noqa: E402
from agentic_evalkit.models import (  # noqa: E402
    DatasetRef,
    DatasetSelection,
    EvalRunManifest,
    EvalSample,
    GraderSpec,
    ResolvedDataset,
    SamplingPolicy,
    SourceRecord,
)
from agentic_evalkit.reporters.json import JsonReporter  # noqa: E402
from agentic_evalkit.runner import EvalRunner  # noqa: E402
from agentic_evalkit.targets.subprocess import SubprocessTarget  # noqa: E402
from graders import build_grader, cleanup_worktree, prepare_worktree  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

CASES_JSONL = KIT_ROOT / "dataset" / "cases.jsonl"
REPORTS_DIR = KIT_ROOT / "reports"
ARP_PYTHON = Path("C:/Users/tandf/source/agentic-runtime-platform/.venv/Scripts/python.exe")
SCRATCH = Path(
    "C:/Users/tandf/AppData/Local/Temp/claude/"
    "C--Users-tandf-source-agentic-evalkit/98683646-eaf6-4196-85d4-372846e7317f/scratchpad"
)

#: Grading checkout per source repo: (repository, worktree used for grading).
#: A case is graded in a throwaway worktree of the repo it was mined from, never
#: in the repo itself. The worktrees double as the mining checkouts -- same
#: commit, already synced -- so an A/B run costs no extra checkout.
REPO_WORKTREES: dict[str, tuple[Path, Path]] = {
    "evk": (Path("C:/Users/tandf/source/agentic-evalkit"), SCRATCH / "evk-mine"),
    "ek": (Path("C:/Users/tandf/source/executionkit"), SCRATCH / "ek-mine"),
    "arp": (
        Path("C:/Users/tandf/source/agentic-runtime-platform"),
        SCRATCH / "arp-mine/agentic-workflows-v2",
    ),
    "memoryctl": (Path("C:/Users/tandf/source/repos/memoryctl"), SCRATCH / "mc-mine"),
}

ARMS = {
    "a": ("swe_fix_direct", "arm-a-direct"),
    "b": ("swe_fix_review_loop", "arm-b-review-loop"),
}

ADAPTER_NAME = "arp-swe-cases@1"
GRADER_NAME = "swe-fix-composite@1"

#: Credentials removed from the child environment so no paid provider in ARP's
#: fallback chain can be reached. Removing the key is the control; a config
#: flag would only be a request.
PAID_CREDENTIALS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GITHUB_TOKEN",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_FOUNDRY_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


class SweCaseAdapter:
    """Projects one mined case into an ``EvalSample``. Pure projection, no I/O."""

    api_version = "1"
    name = ADAPTER_NAME

    def __init__(self, grader_name: str = GRADER_NAME) -> None:
        self._grader_name = grader_name

    def prepare(self, record: SourceRecord) -> EvalSample:
        data: dict[str, Any] = dict(record.data)
        sample_id = str(data["sample_id"])
        payload = dict(data.get("input") or {})
        # The bridge reads the broken file from the case directory rather than
        # receiving it inline, so the request line stays small regardless of
        # how large the module under repair is.
        existing = str(payload.get("repo_path") or "")
        payload["case_dir"] = (
            existing
            if existing and Path(existing).is_dir()
            else str(KIT_ROOT / "dataset" / "cases" / sample_id)
        )
        metadata = {str(k): str(v) for k, v in (data.get("metadata") or {}).items()}
        return EvalSample(
            sample_id=sample_id,
            input=payload,
            reference=None,
            source_row_id=record.row_id,
            source_digest=record.digest,
            adapter=ADAPTER_NAME,
            metadata=metadata,
            grader=GraderSpec(
                name=self._grader_name, grader_type="composite", hard_gate=True
            ),
        )


class _LocalCatalogAdapter:
    """Adapts LocalDatasetProvider to EvalRunner's minimal catalog protocol."""

    def __init__(self, provider: LocalDatasetProvider) -> None:
        self._provider = provider

    async def resolve(self, ref: DatasetRef) -> ResolvedDataset:
        return await self._provider.resolve(ref)

    def iter_records(
        self, dataset: ResolvedDataset, *, offset: int = 0, limit: int | None = None
    ) -> AsyncIterator[SourceRecord]:
        return self._provider.iter_records(dataset, offset=offset, limit=limit)


def build_child_env(workflow: str, model: str, timeout: float) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in PAID_CREDENTIALS}
    env["AB_WORKFLOW"] = workflow
    env["AB_MODEL"] = model
    env["AB_TIMEOUT"] = str(timeout)
    # Pin every tier the two workflows touch to the one model under test, so a
    # tier default can never quietly substitute a different one mid-run.
    for tier in range(0, 6):
        env[f"AGENTIC_MODEL_TIER_{tier}"] = model
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def prepare_grading_worktrees(cases_path: Path) -> dict[str, Path]:
    """Create a grading worktree for each source repo the case set draws on.

    Only the repos actually represented in the case file are checked out, so a
    limited run never pays for a checkout it will not use.
    """
    repos: set[str] = set()
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        repo = str((row.get("metadata") or {}).get("source_repo", ""))
        if repo:
            repos.add(repo)

    prepared: dict[str, Path] = {}
    for name in sorted(repos):
        if name not in REPO_WORKTREES:
            raise SystemExit(
                f"case set references source repo {name!r} with no grading "
                f"worktree configured; known: {sorted(REPO_WORKTREES)}"
            )
        repo, worktree = REPO_WORKTREES[name]
        # The ARP worktree is nested one level down (the package lives in a
        # subdirectory), so create the checkout at its parent.
        checkout = worktree if name != "arp" else worktree.parent
        prepare_worktree(repo, checkout)
        prepared[name] = worktree
    return prepared


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
    parser.add_argument("--model", default="ollama:deepseek-v4-flash:0731-cloud")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--grader",
        choices=("mutation", "swebench"),
        default="mutation",
        help="mutation: local pytest oracle. swebench: the official Docker "
        "harness running the instance's real FAIL_TO_PASS tests.",
    )
    parser.add_argument(
        "--cases",
        default=str(CASES_JSONL),
        help="case index to run (default: the full set). Use a filtered index "
        "to re-run a subset without redoing the cases that already have a verdict.",
    )
    parser.add_argument(
        "--suffix",
        default="",
        help="appended to the report filename, so a subset run does not "
        "overwrite the full run it supplements",
    )
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--cleanup-worktree",
        action="store_true",
        help="remove the grading worktree afterwards (off by default: it is reused "
        "across arms and its venv costs minutes to rebuild)",
    )
    args = parser.parse_args()

    workflow, run_name = ARMS[args.arm]
    cases_path = Path(args.cases)
    report_name = run_name + args.suffix
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    provider = LocalDatasetProvider(allowed_roots=(cases_path.parent,))
    catalog = _LocalCatalogAdapter(provider)

    target = SubprocessTarget(
        command=(str(ARP_PYTHON), str(KIT_ROOT / "bridge.py")),
        env=build_child_env(workflow, args.model, args.timeout),
        max_output_bytes=4 * 1024 * 1024,
    )

    if args.grader == "swebench":
        from container_harness import build_container_executor
        from swebench_graders import build_swebench_grader

        grader = build_swebench_grader(executor=build_container_executor())
        grader_name = "swebench-composite@1"
        print("grader: official SWE-bench Docker harness")
    else:
        worktrees = prepare_grading_worktrees(cases_path)
        print(f"grading worktrees: { {k: str(v) for k, v in worktrees.items()} }")
        grader = build_grader(worktrees=worktrees)
        grader_name = GRADER_NAME
    runner = EvalRunner(
        catalog=catalog,
        adapters={ADAPTER_NAME: SweCaseAdapter(grader_name)},
        targets={f"arp-{workflow}": target},
        graders={grader_name: grader},
        artifact_store=ArtifactStore(KIT_ROOT / "artifacts"),
    )

    manifest = EvalRunManifest(
        run_name=run_name,
        dataset_ref=DatasetRef(provider="local", dataset_id=str(cases_path)),
        adapter=ADAPTER_NAME,
        grader=grader_name,
        target_name=f"arp-{workflow}",
        selection=DatasetSelection(limit=args.limit) if args.limit else DatasetSelection(),
        sampling=SamplingPolicy(attempts=args.attempts, temperature=0.0, seed=20260827),
        attempts=args.attempts,
        timeout_seconds=args.timeout,
        concurrency=args.concurrency,
    )

    try:
        result = await runner.run(manifest)
    finally:
        if args.cleanup_worktree:
            for name, worktree in worktrees.items():
                cleanup_worktree(REPO_WORKTREES[name][0], worktree)

    report_path = REPORTS_DIR / f"{report_name}.json"
    JsonReporter().write(result, report_path)
    summary = result.summary
    print(
        f"[{report_name}] total={summary.total} passed={summary.passed} "
        f"failed={summary.failed} errors={summary.errors} "
        f"timeouts={summary.timeouts} unavailable={summary.unavailable}"
    )
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
