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
import hashlib
import json
import os
import subprocess
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
from graders import (  # noqa: E402
    build_grader,
    cleanup_worktree,
    load_oracle,
    prepare_worktree,
)

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

#: Credentials neutralised in the child environment so no paid provider in
#: ARP's fallback chain can be reached. Blanking the key is the control; a
#: config flag would only be a request.
#:
#: They are set to "" rather than deleted, and that distinction is the whole
#: control. ``agentic_v2.models.secrets.EnvSecretProvider`` walks up from its
#: own file looking for a ``.env`` and calls ``load_dotenv(override=False)``,
#: so a *deleted* key is simply re-hydrated from ARP's own .env inside the
#: child and the strip achieves nothing. ``load_dotenv`` skips a name already
#: present in ``os.environ`` even when its value is empty, and
#: ``_normalize_secret`` turns "" into None, so a blank survives and reads as
#: absent. This is the same mechanism, for the same reason, as ADR-058's
#: ``backends_claude.subscription_env``.
#:
#: This was not theoretical: with the keys merely deleted, 9 of the first 160
#: graded samples reached gemini-2.5-flash on a campaign meant to spend
#: nothing.
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
    # NVIDIA NIM: the tier-1/2 fallback chains carry paid NIM models, so an
    # Ollama failure could complete a billable call before bridge.py rejects
    # the substituted sample. The rejection protects validity; it cannot
    # refund the call.
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
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


#: Files whose content defines the *treatment* an arm applies, beyond the
#: model. A change to any of them makes a later run a different system.
def _implementation_files(workflow: str) -> tuple[Path, ...]:
    return (KIT_ROOT / "workflows" / f"{workflow}.yaml", KIT_ROOT / "bridge.py")


def target_fingerprint(workflow: str, model: str) -> str:
    """Identify the system under test: the model *and* what orchestrated it.

    Recording only the model is not enough. The A/B's treatment is the
    workflow, so an edit to a workflow YAML or to the bridge between waves
    produces a different system under the same model -- and ``merge_outcomes``
    would union the reports without noticing, because every identity field
    matched.

    That is a demonstrated hazard here, not a hypothetical one: commit
    660ae983 ("fix the arm that discarded repairs") changed
    ``swe_fix_review_loop.yaml`` *after* an earlier result had been observed.
    Waves 1-7 all ran after it, so the current union is unaffected, but a
    report from either side of that commit would have unioned silently.

    Line endings are normalised before hashing so a CRLF checkout does not
    invent a difference the content does not have.
    """
    digest = hashlib.sha256()
    digest.update(model.encode("utf-8"))
    for path in _implementation_files(workflow):
        digest.update(b"\0" + path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return f"{model}@{digest.hexdigest()[:12]}"


def _digest_python_tree(root: Path) -> str:
    """SHA-256 over every ``.py`` under *root*, path-ordered.

    Line endings are normalised so a CRLF checkout does not invent a
    difference, and ``__pycache__`` is skipped so a stale build does not.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts):
        digest.update(b"\0" + path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:12]


def runtime_fingerprint() -> str | None:
    """Digest of the ARP runtime the bridge actually executes.

    The workflow YAML says what the arm does; ``agentic_v2`` decides what that
    produces. A runtime change is therefore a treatment change even when the
    model and the workflow are untouched -- this PR is its own example, having
    altered ``graph_wiring.extract_agent_response_text`` so a blank
    reasoning-model turn now yields the model's reasoning instead of "".
    Waves either side of that produce different answers under an otherwise
    identical fingerprint.

    The package is located by asking the ARP interpreter rather than assuming
    a path relative to this kit: the bridge runs under ``ARP_PYTHON``, whose
    venv may resolve ``agentic_v2`` to a different checkout than the one this
    file happens to sit in.

    Returns ``None`` if the runtime cannot be located, which is recorded as
    "unknown" rather than silently treated as "unchanged".
    """
    probe = subprocess.run(
        [
            str(ARP_PYTHON),
            "-c",
            "import agentic_v2,pathlib;print(pathlib.Path(agentic_v2.__file__).parent)",
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return None
    root = Path(probe.stdout.strip())
    return _digest_python_tree(root) if root.is_dir() else None


def grader_fingerprint() -> str:
    """Digest of the modules that decide a sample's score.

    A grader change makes new numbers incomparable with old ones just as
    surely as a model change does, so it belongs in the union identity.
    """
    digest = hashlib.sha256()
    for name in ("graders.py", "swebench_graders.py", "rubric.py", "container_harness.py"):
        path = KIT_ROOT / name
        if path.is_file():
            digest.update(b"\0" + name.encode("utf-8") + b"\0")
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:12]


def build_child_env(workflow: str, model: str, timeout: float) -> dict[str, str]:
    # Blank, never delete -- see PAID_CREDENTIALS for why deleting is defeated
    # by the child re-reading ARP's .env.
    env = dict(os.environ)
    env.update(dict.fromkeys(PAID_CREDENTIALS, ""))
    env["AB_WORKFLOW"] = workflow
    env["AB_MODEL"] = model
    env["AB_TIMEOUT"] = str(timeout)
    # Pin every tier the two workflows touch to the one model under test, so a
    # tier default can never quietly substitute a different one mid-run.
    for tier in range(0, 6):
        env[f"AGENTIC_MODEL_TIER_{tier}"] = model
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def mined_revisions(cases_path: Path) -> dict[str, set[str | None]]:
    """Per source repo, the revisions its cases were mined at.

    A set rather than one value: a case file that mixes revisions for one
    repo cannot be graded at a single checkout, and that has to be visible
    rather than resolved by picking one arbitrarily.
    """
    revisions: dict[str, set[str | None]] = {}
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        repo = str((row.get("metadata") or {}).get("source_repo", ""))
        if not repo:
            continue
        try:
            oracle = load_oracle(str(row["sample_id"]))
        except (OSError, KeyError):
            revisions.setdefault(repo, set()).add(None)
            continue
        revisions.setdefault(repo, set()).add(oracle.get("source_revision"))
    return revisions


def prepare_grading_worktrees(cases_path: Path) -> dict[str, tuple[Path, Path]]:
    """Create a grading worktree for each source repo the case set draws on.

    Only the repos actually represented in the case file are checked out, so a
    limited run never pays for a checkout it will not use.

    Each entry is ``(grading_path, checkout_root)``. The two differ for ARP,
    whose package lives one level down: the grader needs the package
    subdirectory, but the *registered* git worktree is its parent, and
    cleanup has to be handed the registered path or ``git worktree remove``
    rejects it and leaves the parent behind, broken, for every later run.

    Worktrees are pinned to the revision the cases were mined at where the
    oracle records one. Cases mined before ``source_revision`` existed record
    nothing, so those fall back to the repo's current ``HEAD`` — announced,
    because grading then depends on when it runs.
    """
    revisions = mined_revisions(cases_path)

    prepared: dict[str, tuple[Path, Path]] = {}
    for name in sorted(revisions):
        if name not in REPO_WORKTREES:
            raise SystemExit(
                f"case set references source repo {name!r} with no grading "
                f"worktree configured; known: {sorted(REPO_WORKTREES)}"
            )
        seen = revisions[name]
        pinned = {rev for rev in seen if rev}
        if len(pinned) > 1:
            raise SystemExit(
                f"cases for source repo {name!r} were mined at "
                f"{len(pinned)} different revisions ({', '.join(sorted(pinned))}); "
                f"one checkout cannot grade them all. Split the run per revision."
            )
        revision = next(iter(pinned), None)
        if revision is None:
            print(
                f"WARNING: cases for {name!r} record no source_revision, so "
                f"grading uses the repo's current HEAD. If {name!r} has moved "
                f"since these cases were mined, the outcome depends on when "
                f"this run happens. Re-mine to pin them.",
                file=sys.stderr,
            )
        elif None in seen:
            raise SystemExit(
                f"cases for source repo {name!r} mix pinned ({revision}) and "
                f"unpinned oracles; one checkout cannot grade them all."
            )

        repo, worktree = REPO_WORKTREES[name]
        # The ARP worktree is nested one level down (the package lives in a
        # subdirectory), so create the checkout at its parent.
        checkout = worktree if name != "arp" else worktree.parent
        prepare_worktree(repo, checkout, revision)
        prepared[name] = (worktree, checkout)
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

    # Only the mutation grader builds worktrees; the SWE-bench harness grades
    # in its own containers. Bind it empty either way so the cleanup in the
    # `finally` below is a no-op rather than an UnboundLocalError that would
    # discard a completed multi-hour run before its report is written.
    # Values are (grading_path, checkout_root) -- see prepare_grading_worktrees.
    worktrees: dict[str, tuple[Path, Path]] = {}
    if args.grader == "swebench":
        from container_harness import build_container_executor
        from swebench_graders import build_swebench_grader

        grader = build_swebench_grader(executor=build_container_executor())
        grader_name = "swebench-composite@1"
        print("grader: official SWE-bench Docker harness")
    else:
        worktrees = prepare_grading_worktrees(cases_path)
        print(
            f"grading worktrees: "
            f"{ {k: str(grading) for k, (grading, _) in worktrees.items()} }"
        )
        grader = build_grader(
            worktrees={k: grading for k, (grading, _) in worktrees.items()}
        )
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
        # The model under test, recorded so a union can actually enforce
        # "same arm, same model". --model is an exposed option, and until
        # this was set nothing in the report identified the model at all:
        # target_fingerprint and every sample's model_name were null, so
        # analyze.py could union two different models without noticing.
        # analyze.union_identity already compares this field.
        target_fingerprint=target_fingerprint(workflow, args.model),
        target_fingerprint_policy="model-id+sha256(workflow.yaml,bridge.py)[:12]",
        # What produced the answers, and what scored them. Both change
        # outcomes without touching the model or the workflow, so both are
        # part of whether two runs are one system. "unknown" is recorded
        # rather than omitted when the runtime cannot be located, so it can
        # never be mistaken for "unchanged".
        code_fingerprint=f"agentic_v2:{runtime_fingerprint() or 'unknown'}",
        environment_fingerprint=f"graders:{grader_fingerprint()}",
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
            # Remove the *registered* checkout root, not the grading
            # subdirectory: `git worktree remove` rejects an unregistered
            # child path, and the ignored failure used to leave the parent
            # registered but deleted, breaking every later run.
            for name, (_, checkout) in worktrees.items():
                cleanup_worktree(REPO_WORKTREES[name][0], checkout)

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
