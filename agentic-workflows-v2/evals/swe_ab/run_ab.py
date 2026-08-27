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
EVK_REPO = Path("C:/Users/tandf/source/agentic-evalkit")
ARP_PYTHON = Path("C:/Users/tandf/source/agentic-runtime-platform/.venv/Scripts/python.exe")
GRADING_WORKTREE = Path(
    "C:/Users/tandf/AppData/Local/Temp/claude/"
    "C--Users-tandf-source-agentic-evalkit/98683646-eaf6-4196-85d4-372846e7317f/"
    "scratchpad/evk-mine"
)

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

    def prepare(self, record: SourceRecord) -> EvalSample:
        data: dict[str, Any] = dict(record.data)
        sample_id = str(data["sample_id"])
        payload = dict(data.get("input") or {})
        # The bridge reads the broken file from the case directory rather than
        # receiving it inline, so the request line stays small regardless of
        # how large the module under repair is.
        payload["case_dir"] = str(KIT_ROOT / "dataset" / "cases" / sample_id)
        metadata = {str(k): str(v) for k, v in (data.get("metadata") or {}).items()}
        return EvalSample(
            sample_id=sample_id,
            input=payload,
            reference=None,
            source_row_id=record.row_id,
            source_digest=record.digest,
            adapter=ADAPTER_NAME,
            metadata=metadata,
            grader=GraderSpec(name=GRADER_NAME, grader_type="composite", hard_gate=True),
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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
    parser.add_argument("--model", default="ollama:deepseek-v4-flash:0731-cloud")
    parser.add_argument("--limit", type=int, default=None)
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
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    provider = LocalDatasetProvider(allowed_roots=(CASES_JSONL.parent,))
    catalog = _LocalCatalogAdapter(provider)

    target = SubprocessTarget(
        command=(str(ARP_PYTHON), str(KIT_ROOT / "bridge.py")),
        env=build_child_env(workflow, args.model, args.timeout),
        max_output_bytes=4 * 1024 * 1024,
    )

    worktree = prepare_worktree(EVK_REPO, GRADING_WORKTREE)
    grader = build_grader(worktree=worktree, repo=EVK_REPO)
    runner = EvalRunner(
        catalog=catalog,
        adapters={ADAPTER_NAME: SweCaseAdapter()},
        targets={f"arp-{workflow}": target},
        graders={GRADER_NAME: grader},
        artifact_store=ArtifactStore(KIT_ROOT / "artifacts"),
    )

    manifest = EvalRunManifest(
        run_name=run_name,
        dataset_ref=DatasetRef(provider="local", dataset_id=str(CASES_JSONL)),
        adapter=ADAPTER_NAME,
        grader=GRADER_NAME,
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
            cleanup_worktree(EVK_REPO, worktree)

    report_path = REPORTS_DIR / f"{run_name}.json"
    JsonReporter().write(result, report_path)
    summary = result.summary
    print(
        f"[{run_name}] total={summary.total} passed={summary.passed} "
        f"failed={summary.failed} errors={summary.errors} "
        f"timeouts={summary.timeouts} unavailable={summary.unavailable}"
    )
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
