"""Cutover: load the SWE-AB campaign's report files into the ledger.

Scope
-----
42 files sit under `reports/`. Five are excluded here, not silently skipped
(see `EXCLUDED_REPORTS` for the authoritative, per-file reasons):

* `arm-a-direct-memoryctl.json` / `arm-b-review-loop-memoryctl.json` -- these
  samples repair a local `memoryctl` test failure, not a SWE-bench instance.
  There is no `repo`/`base_commit`/container image to give `task` (NOT NULL
  columns), and inventing one would be exactly the "silently emit a wrong
  value" failure `ledger.load_report` is written to avoid. They need their
  own task-set shape, not this migration.
* `arm-a-direct-bigfile-probe.json` -- one sample, whose dataset file
  (`_sw_big.jsonl`) is not present on disk and whose only sample has no
  execution output at all. Nothing here to derive a `Task` row from.
* `arm-a-direct.json` / `arm-b-review-loop.json` -- the "consolidated"
  full-pool reports. Their dataset (`cases.jsonl`) turned out, on the first
  migration attempt, to mix real SWE-bench instances with `ARP-MUT-*`
  mutation cases that carry no `metadata.instance_id` at all, which
  `load_report` requires on every sample. Splitting a report by sample is
  out of scope for that loader, so the whole file is excluded rather than
  guessing which samples are safe.

The remaining 37 files are every report whose dataset traces back to a real
`dataset/swebench_cases/<instance_id>/oracle.json` -- see `CAMPAIGNS` below
for how they map onto ledger campaigns, waves and arms. That mapping is a
judgement call (the reports were never labelled with a campaign/wave id);
`docs/WAVE-RUNBOOK.md` gives the segment boundaries for the wave-numbered
files, and everything else is grouped by the shared filename suffix
(`--left`/`--right` in `analyze.py` terms). Re-running this script is free
-- nothing it writes is committed except the JSONL export -- so a different
grouping is a re-run away, not a migration.

Blobs
-----
813 of the 1,703 migrated trials have `execution.output = null` with a real
`artifacts.output_ref` digest -- the README's "78% unreachable" finding, for
the slice of it this migration covers. All 813 resolve: every digest a
report names is present, intact (rehashes correctly) and readable as JSON
under `artifacts/` on this machine, and each resolved payload's
`models_used` enriches the trial's `models_answered` rather than leaving it
`[]`. The corresponding `blob` rows land in the ledger's own `BlobStore`
(default `ledger/blobs/`) with `retention='prunable'` -- the payload is
useful for enrichment, not required for correctness the way a grade or a
trial is.

The resolver still has a "not found" branch, and `PendingBlobChannel` still
exists to record it, because artifacts/ is this one machine's local,
gitignored disk -- a clone that has these report files but never generated
them locally would find zero of the 813, not all of them. A digest that
cannot be resolved still needs a row in `blob` for the foreign key `trial.
answer_blob` references to hold (the row and the trial referencing it are
inserted in separate transactions), so an unresolvable digest gets a
tombstone -- `media_type='application/x-ledger-pending'`, `size_bytes=0` --
never a fabricated real one.

Usage
-----
    uv run python migrate_reports.py [--db PATH] [--export-dir PATH]
                                      [--blob-root PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import importlib.metadata
import json
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ledger
import yaml
from ledger.blobs import BlobStore
from ledger.load_report import (
    LoadedBatch,
    UnknownInstanceError,
    load_report,
    parse_model_ref,
)
from ledger.store import ArmsUnbalanced, LedgerStore, open_ledger

KIT_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = KIT_ROOT / "reports"
ARTIFACTS_DIR = KIT_ROOT / "artifacts"
DATASET_DIR = KIT_ROOT / "dataset"
WORKFLOWS_DIR = KIT_ROOT / "workflows"
LEDGER_DIR = KIT_ROOT / "ledger"

DEFAULT_DB_PATH = LEDGER_DIR / "campaign.db"
DEFAULT_EXPORT_DIR = LEDGER_DIR / "export"
DEFAULT_BLOB_ROOT = LEDGER_DIR / "blobs"
PENDING_BLOBS_FILENAME = "pending_blobs.jsonl"

#: No harness version is recorded anywhere in a report; this identifies the
#: harness package itself (this directory), pinned so a future incompatible
#: change to the report shape produces a new value deliberately, not by
#: accident.
HARNESS_VERSION = "swe_ab@1"

GRADER_NAME = "swebench-composite@1"
#: The files that together decide a verdict for a graded sample. Hashed as
#: the grader's `module_digest` -- a change to any of them is a change to
#: what "pass" means, which is exactly what `module_digest` exists to pin.
GRADER_SOURCE_FILES = ("graders.py", "swebench_graders.py", "rubric.py")

RETRIEVAL_MODE = (
    "oracle"  # every case under dataset/swebench_cases/ is oracle-retrieval
)


class MigrationError(RuntimeError):
    """A report or instance could not be migrated; see the message for why."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return ledger.digest_bytes(path.read_bytes())


def _sha256_files(paths: Sequence[Path]) -> str:
    """A single digest over several files' contents, order-independent."""
    parts = sorted(path.read_bytes() for path in paths)
    return ledger.digest_bytes(b"\0".join(parts))


# ---------------------------------------------------------------------
# Pending blobs: a queue of "referenced but not materialized" digests
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PendingBlob:
    digest: str
    reason: str
    context: str
    seen_at: str


class PendingBlobChannel:
    """Every blob digest a report referenced that this migration could not
    read real bytes for.

    A trial whose `answer_blob` points at such a digest still needs a `blob`
    row to satisfy the foreign key -- `tombstone_row()` gives it one that is
    honestly labelled as absent (`media_type='application/x-ledger-pending'`,
    `size_bytes=0`) rather than a fabricated real one. Reading that digest
    back out of `BlobStore` correctly raises `BlobMissing`: the tombstone
    records that the reference existed, not that the bytes do.
    """

    def __init__(self) -> None:
        self._items: list[PendingBlob] = []

    def push(self, *, digest: str, reason: str, context: str) -> None:
        self._items.append(
            PendingBlob(
                digest=digest, reason=reason, context=context, seen_at=_utc_now_iso()
            )
        )

    def __len__(self) -> int:
        return len(self._items)

    @staticmethod
    def tombstone_row(digest: str) -> ledger.Blob:
        return ledger.Blob(
            digest=digest,
            media_type="application/x-ledger-pending",
            size_bytes=0,
            retention=ledger.Retention.PRUNABLE.value,
            stored_at=_utc_now_iso(),
        )

    def flush_to(self, path: Path) -> int:
        """Write every pending entry as one JSON object per line and return
        the count written. Overwrites `path` -- this channel is rebuilt
        fresh on every migration run, not accumulated across runs."""
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(self._items, key=lambda item: (item.digest, item.seen_at))
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for item in ordered:
                handle.write(json.dumps(dataclasses.asdict(item), sort_keys=True))
                handle.write("\n")
        return len(ordered)


def make_output_resolver(
    *,
    report_name: str,
    blob_store: BlobStore,
    ledger_store: LedgerStore,
    pending: PendingBlobChannel,
) -> Callable[[str], Mapping[str, Any] | None]:
    """Build the `resolve_output` callback `load_report` calls for a spilled
    sample. Looks for `<hex digest>.bin` under `artifacts/` (the shape
    `agentic_evalkit.artifacts.ArtifactStore` writes); on any failure to
    locate, verify or parse it, records a `PendingBlob` and registers a
    tombstone so the trial referencing this digest can still be inserted.
    """

    def resolve(digest: str) -> Mapping[str, Any] | None:
        hex_part = digest.rsplit(":", 1)[-1]
        bin_path = ARTIFACTS_DIR / f"{hex_part}.bin"
        if not bin_path.is_file():
            pending.push(
                digest=digest,
                reason="not found under artifacts/",
                context=report_name,
            )
            ledger_store.register(pending.tombstone_row(digest))
            return None

        data = bin_path.read_bytes()
        if ledger.digest_bytes(data) != digest:
            pending.push(
                digest=digest,
                reason="local bytes at artifacts/ do not hash to the referenced digest",
                context=report_name,
            )
            ledger_store.register(pending.tombstone_row(digest))
            return None

        media_type = _sidecar_media_type(hex_part) or "application/octet-stream"
        blob_row = blob_store.put(data, media_type=media_type, retention="prunable")
        ledger_store.register(blob_row)

        payload = _parse_spilled_payload(data)
        if payload is None:
            pending.push(
                digest=digest,
                reason="bytes are neither valid JSON nor a Python literal mapping",
                context=report_name,
            )
        return payload

    return resolve


def _sidecar_media_type(hex_part: str) -> str | None:
    sidecar = ARTIFACTS_DIR / f"{hex_part}.json"
    if not sidecar.is_file():
        return None
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    media_type = meta.get("media_type")
    return media_type if isinstance(media_type, str) else None


def _parse_spilled_payload(data: bytes) -> Mapping[str, Any] | None:
    """`ArtifactStore` sidecars claim `application/json`, but at least one
    payload observed on disk is a Python `repr()` of a dict (single-quoted,
    not valid JSON) -- so JSON is tried first and a literal-eval fallback
    second, rather than trusting the declared media type.
    """
    text = data.decode("utf-8", errors="strict") if _is_utf8(data) else None
    if text is None:
        return None
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return None
    return parsed if isinstance(parsed, Mapping) else None


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


# ---------------------------------------------------------------------
# Reference rows: grader, workflows, images -- shared by every campaign
# ---------------------------------------------------------------------


def register_grader(store: LedgerStore) -> str:
    module_digest = _sha256_files([KIT_ROOT / name for name in GRADER_SOURCE_FILES])
    grader = ledger.Grader(
        grader_id=ledger.grader_id(
            name=GRADER_NAME,
            kind=ledger.GraderKind.COMPOSITE.value,
            module_digest=module_digest,
            rubric_id=None,
        ),
        name=GRADER_NAME,
        kind=ledger.GraderKind.COMPOSITE.value,
        module_digest=module_digest,
        rubric_id=None,
    )
    return store.register(grader)


#: workflow file name -> (report's `execution.output.workflow` value, role)
_WORKFLOWS = {
    "swe_fix_direct.yaml": "swe_fix_direct",
    "swe_fix_review_loop.yaml": "swe_fix_review_loop",
}


def register_workflows(store: LedgerStore) -> dict[str, str]:
    """Return `{workflow name -> workflow_id}` for both arms' workflows."""
    result: dict[str, str] = {}
    for filename, name in _WORKFLOWS.items():
        path = WORKFLOWS_DIR / filename
        yaml_digest = _sha256_file(path)
        step_count = len(yaml.safe_load(path.read_text(encoding="utf-8"))["steps"])
        workflow_id = ledger.workflow_id(
            name=name, yaml_digest=yaml_digest, prompt_ids=()
        )
        store.register(
            ledger.Workflow(
                workflow_id=workflow_id,
                name=name,
                yaml_digest=yaml_digest,
                step_count=step_count,
            )
        )
        result[name] = workflow_id
    return result


def register_sentinel_image(store: LedgerStore) -> str:
    """Every included report ran its target as a subprocess, not a
    container -- there is no real image digest anywhere in the report
    shape. `task.image_id` is `NOT NULL`, so this registers one honestly
    self-describing sentinel rather than a per-task fabricated digest.
    """
    repo = "sentinel:no-container-subprocess-target"
    digest = ledger.digest_bytes(repo.encode("utf-8"))
    image = ledger.Image(
        image_id=ledger.image_id(repo=repo, digest=digest),
        repo=repo,
        tag=None,
        digest=digest,
        pulled_at=_utc_now_iso(),
    )
    return store.register(image)


# ---------------------------------------------------------------------
# Task set: the pool of real SWE-bench oracle cases these reports drew from
# ---------------------------------------------------------------------


def _oracle_json(instance_id: str) -> dict[str, Any]:
    path = DATASET_DIR / "swebench_cases" / instance_id / "oracle.json"
    if not path.is_file():
        raise MigrationError(
            f"instance {instance_id!r} has no dataset/swebench_cases/.../oracle.json "
            "-- cannot build its Task row without inventing repo/base_commit/image"
        )
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def register_task_set_and_tasks(
    store: LedgerStore, instance_ids: Sequence[str], image_id: str
) -> tuple[str, dict[str, str]]:
    """Register one `TaskSet` covering every instance this migration touches
    plus one `Task` row per instance, and return `(task_set_id, {instance_id
    -> task_id})`.
    """
    unique_ids = sorted(set(instance_ids))
    revision = ledger.digest_bytes("\n".join(unique_ids).encode("utf-8"))
    task_set_id = ledger.task_set_id(
        name="swebench-oracle-pool",
        source="dataset/swebench_cases",
        revision=revision,
        filter_expr=None,
    )
    store.register(
        ledger.TaskSet(
            task_set_id=task_set_id,
            name="swebench-oracle-pool",
            source="dataset/swebench_cases",
            revision=revision,
            filter_expr=None,
            row_count=len(unique_ids),
            licence=None,
            built_at=_utc_now_iso(),
        )
    )

    task_ids: dict[str, str] = {}
    for instance_id in unique_ids:
        oracle = _oracle_json(instance_id)
        task_id = ledger.task_id(task_set_id=task_set_id, instance_id=instance_id)
        store.register(
            ledger.Task(
                task_id=task_id,
                task_set_id=task_set_id,
                instance_id=instance_id,
                repo=oracle["repo"],
                base_commit=oracle["base_commit"],
                target_file=oracle["target_file"],
                image_id=image_id,
                fail_to_pass=json.dumps(oracle["fail_to_pass"], separators=(",", ":")),
                difficulty=oracle.get("difficulty"),
                contamination_risk=oracle.get("contamination_risk"),
                safe_after=None,
                problem_blob=None,
                source_blob=None,
                max_changed_lines=oracle.get("max_changed_lines"),
            )
        )
        task_ids[instance_id] = task_id
    return task_set_id, task_ids


# ---------------------------------------------------------------------
# Model resolution: manifest.target_fingerprint, falling back to the first
# sample that actually names a model
# ---------------------------------------------------------------------


def resolve_model_ref(report: Mapping[str, Any]) -> tuple[str, str]:
    """`(provider, wire_ref)` for the model this report ran.

    `manifest.target_fingerprint` is tried first (via `parse_model_ref`,
    same as `load_report` itself); when that is null or unparseable (every
    report predating `run_ab.py` recording it), falls back to the first
    sample naming a model in its own `execution.output.requested_model` or
    `execution.model_name`. Returns `("unknown", "unknown")` only when
    neither source has anything -- never a guess.
    """
    manifest = report.get("manifest") or {}
    provider, wire_ref = parse_model_ref(manifest.get("target_fingerprint"))
    if (provider, wire_ref) != ("unknown", "unknown"):
        return provider, wire_ref

    for sample in report.get("samples", ()):
        execution = sample.get("execution") or {}
        output = execution.get("output")
        candidate = (
            output.get("requested_model") if output else None
        ) or execution.get("model_name")
        if candidate:
            candidate_str = str(candidate)
            if ":" in candidate_str:
                found_provider, wire = candidate_str.split(":", 1)
                return found_provider, wire
            return "unknown", candidate_str
    return "unknown", "unknown"


def register_model(store: LedgerStore, provider: str, wire_ref: str) -> str:
    family = wire_ref
    model = ledger.Model(
        model_id=ledger.model_id(
            provider=provider,
            wire_ref=wire_ref,
            family=family,
            params_b=None,
            quantization=None,
            context_window=None,
            serving_mode=ledger.ServingMode.HOSTED.value,
        ),
        provider=provider,
        wire_ref=wire_ref,
        family=family,
        params_b=None,
        quantization=None,
        context_window=None,
        serving_mode=ledger.ServingMode.HOSTED.value,
        weights_probe=None,
        first_seen_at=_utc_now_iso(),
    )
    return store.register(model)


def _evalkit_version() -> str:
    """The currently installed `agentic-evalkit` version.

    No report records which version generated it, so this is the best
    available proxy, not a historical fact -- reports from Aug 27 - Sep 1
    may have run against a different point release within the
    `>=0.3.0,<0.4.0` pin. Recorded as a caveat, not hidden.
    """
    try:
        return importlib.metadata.version("agentic-evalkit")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# ---------------------------------------------------------------------
# Locally-scoped ids for rows `ledger.ids` has no id function for
# (Campaign, Arm, Wave -- see store.register's docstring)
# ---------------------------------------------------------------------


def _campaign_row_id(name: str) -> str:
    return ledger.content_id("cmp", {"name": name})


def _arm_row_id(campaign_id: str, arm_key: str) -> str:
    return ledger.content_id("armrow", {"campaign_id": campaign_id, "arm_key": arm_key})


def _wave_row_id(campaign_id: str, wave_no: int) -> str:
    return ledger.content_id("wav", {"campaign_id": campaign_id, "wave_no": wave_no})


ARM_ROLE: Mapping[str, str] = {
    "arm-a-direct": ledger.ArmRole.CONTROL.value,
    "arm-b-review-loop": ledger.ArmRole.TREATMENT.value,
}
ARM_WORKFLOW_NAME: Mapping[str, str] = {
    "arm-a-direct": "swe_fix_direct",
    "arm-b-review-loop": "swe_fix_review_loop",
}


# ---------------------------------------------------------------------
# Campaign plan -- which report files become which wave's arms
#
# No report carries a campaign/wave id of its own; this mapping is this
# migration's judgement call, built from docs/WAVE-RUNBOOK.md's segment
# boundaries (for the wave-numbered files) and each remaining file's shared
# filename suffix otherwise (the same grouping analyze.py's own --left/
# --right flags already imply). Nothing here is committed except the JSONL
# export downstream of it, so a different grouping is a re-run away.
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WavePlan:
    wave_no: int
    substrate_label: str
    arms: Mapping[str, str]  # arm_key -> report filename


@dataclass(frozen=True, slots=True)
class CampaignPlan:
    name: str
    question: str
    waves: tuple[WavePlan, ...]


#: docs/WAVE-RUNBOOK.md: "wave 8 opened a new segment; wave 10 opened a
#: second one inside it" -- the harness changed underneath waves 1-7 via
#: PR #282 (the wave-8 boundary), and Ollama Cloud pushed a live weight
#: update between wave 9 and wave 10 (the wave-10 boundary). Waves sharing a
#: label here share a substrate; every report in this family has
#: `manifest.code_fingerprint = null`, so without this label all three
#: segments would collide onto one substrate and hide a real runtime change.
_WAVE_SEGMENT_LABEL: Mapping[int, str] = {
    **{n: "closed-pre-pr282" for n in range(1, 8)},
    8: "seg2-post-pr282",
    9: "seg2-post-pr282",
    10: "seg3-weight-update",
    11: "seg3-weight-update",
}

CAMPAIGNS: tuple[CampaignPlan, ...] = (
    CampaignPlan(
        name="direct-vs-review-loop-waves",
        question=(
            "Does a review-loop workflow beat single-pass repair on "
            "SWE-bench oracle-retrieval instances?"
        ),
        waves=tuple(
            WavePlan(
                wave_no=n,
                substrate_label=_WAVE_SEGMENT_LABEL[n],
                arms={
                    "arm-a-direct": f"arm-a-direct-wave{n}.json",
                    "arm-b-review-loop": f"arm-b-review-loop-wave{n}.json",
                },
            )
            for n in range(1, 12)
        ),
    ),
    CampaignPlan(
        name="direct-vs-review-loop-closed-baseline",
        question=(
            "Same question, run as one batch over the full closed-segment "
            "case pool rather than incrementally by wave."
        ),
        waves=(
            WavePlan(
                1,
                "closed-baseline",
                {
                    "arm-a-direct": "arm-a-direct-swebench.json",
                    "arm-b-review-loop": "arm-b-review-loop-swebench.json",
                },
            ),
            WavePlan(
                2,
                "closed-baseline-c4",
                {"arm-a-direct": "arm-a-direct-swebench-c4.json"},
            ),
            WavePlan(
                3,
                "closed-baseline-floor",
                {"arm-a-direct": "arm-a-direct-swebench-floor.json"},
            ),
            WavePlan(
                4,
                "closed-baseline-fixed",
                {"arm-b-review-loop": "arm-b-review-loop-swebench-fixed.json"},
            ),
        ),
    ),
    CampaignPlan(
        "model-probe-glm53",
        "Does the workflow difference hold on GLM-5.3?",
        (
            WavePlan(
                1,
                "glm53",
                {
                    "arm-a-direct": "arm-a-direct-glm53.json",
                    "arm-b-review-loop": "arm-b-review-loop-glm53.json",
                },
            ),
        ),
    ),
    CampaignPlan(
        "model-probe-minimax1",
        "Does the workflow difference hold on MiniMax-M3?",
        (
            WavePlan(
                1,
                "minimax1",
                {
                    "arm-a-direct": "arm-a-direct-minimax1.json",
                    "arm-b-review-loop": "arm-b-review-loop-minimax1.json",
                },
            ),
        ),
    ),
    CampaignPlan(
        "model-probe-nim1",
        "Does the workflow difference hold on the NVIDIA NIM deployment of DeepSeek?",
        (
            WavePlan(
                1,
                "nim1",
                {
                    "arm-a-direct": "arm-a-direct-nim1.json",
                    "arm-b-review-loop": "arm-b-review-loop-nim1.json",
                },
            ),
        ),
    ),
    CampaignPlan(
        "model-probe-nimbackfill",
        "Direct-arm-only backfill over the NIM deployment's larger case pool.",
        (
            WavePlan(
                1, "nimbackfill", {"arm-a-direct": "arm-a-direct-nimbackfill.json"}
            ),
        ),
    ),
    CampaignPlan(
        "model-probe-run3backfill",
        "Direct-arm-only backfill for the seg3 weight-update segment.",
        (
            WavePlan(
                1, "run3backfill", {"arm-a-direct": "arm-a-direct-run3backfill.json"}
            ),
        ),
    ),
    CampaignPlan(
        "model-probe-hard-slice",
        "Does the workflow difference hold on the harder case slice?",
        (
            WavePlan(
                1,
                "hard-slice",
                {
                    "arm-a-direct": "arm-a-direct-hard-slice.json",
                    "arm-b-review-loop": "arm-b-review-loop-hard-slice.json",
                },
            ),
        ),
    ),
)

EXCLUDED_REPORTS: Mapping[str, str] = {
    "arm-a-direct-memoryctl.json": (
        "task shape is a local memoryctl mutation case (no repo/base_commit/"
        "container image); needs its own task_set design, not this one"
    ),
    "arm-b-review-loop-memoryctl.json": "see arm-a-direct-memoryctl.json",
    "arm-a-direct-bigfile-probe.json": (
        "dataset file (_sw_big.jsonl) is not present on disk and the one "
        "sample has no execution output; nothing to derive a Task row from"
    ),
    "arm-a-direct.json": (
        "cases.jsonl mixes real SWE-bench instances with ARP-MUT-* mutation "
        "cases that carry no metadata.instance_id at all (confirmed: sample "
        "'ARP-MUT-001' has none) -- load_report requires every sample in a "
        "report to resolve one, so this report cannot be migrated whole, and "
        "splitting a report by sample is out of scope for this loader"
    ),
    "arm-b-review-loop.json": "see arm-a-direct.json",
}


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------


def _instance_ids_of(report: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for sample in report.get("samples", ()):
        instance_id = ((sample.get("sample") or {}).get("metadata") or {}).get(
            "instance_id"
        )
        if instance_id:
            ids.add(str(instance_id))
    return ids


@dataclass(frozen=True, slots=True)
class WaveMigrationResult:
    campaign: str
    wave_no: int
    arm_reports: Mapping[str, str]
    trials: int
    grades: int
    warnings: tuple[str, ...]
    balance_note: str | None


def migrate_wave(
    store: LedgerStore,
    *,
    campaign_id: str,
    wave_plan: WavePlan,
    grader_id: str,
    task_set_id: str,
    task_ids_by_instance: Mapping[str, str],
    workflow_ids: Mapping[str, str],
    blob_store: BlobStore,
    pending: PendingBlobChannel,
) -> WaveMigrationResult:
    """Load every arm's report for one wave, confirm they share a substrate,
    then register the wave and append every trial/grade in one pass per arm.

    Two passes over the arms: `load_report` runs first for every arm (it is
    pure -- it does not touch the store except indirectly through
    `resolve_output`'s blob registration), so the wave's real substrate_id
    is known *before* the `Wave` row is written. Writing `Wave` first with a
    guessed substrate and correcting it after would violate the schema's
    own append-only stance on every table that would need to change.
    """
    wave_id = _wave_row_id(campaign_id, wave_plan.wave_no)
    loaded: dict[str, LoadedBatch] = {}
    opened_at: str | None = None

    for arm_key, filename in sorted(wave_plan.arms.items()):
        report_path = REPORTS_DIR / filename
        report: Mapping[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
        opened_at = opened_at or report.get("generated_at")

        provider, wire_ref = resolve_model_ref(report)
        model_id = register_model(store, provider, wire_ref)
        workflow_id = workflow_ids[ARM_WORKFLOW_NAME[arm_key]]

        instance_ids = _instance_ids_of(report)
        missing = instance_ids - task_ids_by_instance.keys()
        if missing:
            raise MigrationError(
                f"{filename}: instance_id(s) {sorted(missing)} have no Task row "
                "(register_task_set_and_tasks was not given them up front)"
            )
        task_ids = {iid: task_ids_by_instance[iid] for iid in instance_ids}

        resolver = make_output_resolver(
            report_name=filename,
            blob_store=blob_store,
            ledger_store=store,
            pending=pending,
        )
        try:
            batch = load_report(
                report,
                campaign_id=campaign_id,
                wave_id=wave_id,
                arm_id=_arm_row_id(campaign_id, arm_key),
                batch_id=filename,
                task_ids=task_ids,
                task_set_id=task_set_id,
                harness_version=HARNESS_VERSION,
                evalkit_version=_evalkit_version(),
                grader_id=grader_id,
                model_id=model_id,
                workflow_id=workflow_id,
                retrieval_mode=RETRIEVAL_MODE,
                resolve_output=resolver,
            )
        except UnknownInstanceError as exc:
            raise MigrationError(f"{filename}: {exc}") from exc
        loaded[arm_key] = batch

    substrate_ids = {batch.substrate.substrate_id for batch in loaded.values()}
    if len(substrate_ids) > 1:
        detail = {k: b.substrate.substrate_id for k, b in loaded.items()}
        raise MigrationError(
            f"wave {wave_plan.wave_no} in campaign {campaign_id!r}: arms disagree on "
            f"substrate ({detail}) -- they cannot share one wave"
        )
    substrate_id = next(iter(substrate_ids))
    store.register(next(iter(loaded.values())).substrate)

    store.register(
        ledger.Wave(
            wave_id=wave_id,
            campaign_id=campaign_id,
            wave_no=wave_plan.wave_no,
            substrate_id=substrate_id,
            stratification=None,
            planned_runs=1,
            opened_at=opened_at or _utc_now_iso(),
        )
    )

    all_warnings: list[str] = []
    trial_count = 0
    grade_count = 0
    task_ids_used: set[str] = set()
    for arm_key, batch in loaded.items():
        store.register(batch.arm_config)
        store.register(
            ledger.Arm(
                arm_id=_arm_row_id(campaign_id, arm_key),
                campaign_id=campaign_id,
                arm_key=arm_key,
                arm_config_id=batch.arm_config.arm_config_id,
                role=ARM_ROLE[arm_key],
            )
        )
        store.append_batch(
            trials=batch.trials,
            step_usage=batch.step_usage,
            spends=batch.spends,
            grades=batch.grades,
        )
        trial_count += len(batch.trials)
        grade_count += len(batch.grades)
        all_warnings.extend(batch.warnings)
        task_ids_used.update(trial.task_id for trial in batch.trials)

    for task_id in sorted(task_ids_used):
        store.register(ledger.WaveTask(wave_id=wave_id, task_id=task_id))
    for arm_key, batch in loaded.items():
        arm_id = _arm_row_id(campaign_id, arm_key)
        for trial in batch.trials:
            store.register(
                ledger.PlanCell(
                    wave_id=wave_id,
                    arm_id=arm_id,
                    task_id=trial.task_id,
                    run_idx=trial.run_idx,
                    status=ledger.PlanStatus.DONE.value,
                )
            )

    balance_note: str | None = None
    try:
        store.check_arm_balance(wave_id)
    except ArmsUnbalanced as exc:
        balance_note = str(exc)

    return WaveMigrationResult(
        campaign=campaign_id,
        wave_no=wave_plan.wave_no,
        arm_reports=dict(wave_plan.arms),
        trials=trial_count,
        grades=grade_count,
        warnings=tuple(all_warnings),
        balance_note=balance_note,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--blob-root", type=Path, default=DEFAULT_BLOB_ROOT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build everything in an in-memory database and a throwaway blob "
        "store; write nothing under ledger/",
    )
    args = parser.parse_args()

    if not args.dry_run:
        return _migrate(args, db_path=args.db, blob_root=args.blob_root)

    with tempfile.TemporaryDirectory(prefix="migrate-reports-dry-run-") as tmp_dir:
        return _migrate(args, db_path=":memory:", blob_root=Path(tmp_dir))


def _migrate(args: argparse.Namespace, *, db_path: Path | str, blob_root: Path) -> int:
    if not args.dry_run and Path(db_path).exists():
        print(
            f"refusing to migrate into an existing database: {db_path} "
            "(delete it first, or pass --dry-run)",
            file=sys.stderr,
        )
        return 1

    conn = open_ledger(db_path)
    store = LedgerStore(conn)
    blob_store = BlobStore(root=blob_root)
    pending = PendingBlobChannel()

    grader_id = register_grader(store)
    workflow_ids = register_workflows(store)
    image_id = register_sentinel_image(store)

    all_instance_ids: set[str] = set()
    for campaign_plan in CAMPAIGNS:
        for wave_plan in campaign_plan.waves:
            for filename in wave_plan.arms.values():
                report = json.loads(
                    (REPORTS_DIR / filename).read_text(encoding="utf-8")
                )
                all_instance_ids |= _instance_ids_of(report)

    task_set_id, task_ids_by_instance = register_task_set_and_tasks(
        store, sorted(all_instance_ids), image_id
    )

    results: list[WaveMigrationResult] = []
    for campaign_plan in CAMPAIGNS:
        campaign_id = _campaign_row_id(campaign_plan.name)
        store.register(
            ledger.Campaign(
                campaign_id=campaign_id,
                name=campaign_plan.name,
                question=campaign_plan.question,
                primary_contrast="workflow",
                created_at=_utc_now_iso(),
                status=ledger.CampaignStatus.CLOSED.value,
            )
        )
        for wave_plan in campaign_plan.waves:
            results.append(
                migrate_wave(
                    store,
                    campaign_id=campaign_id,
                    wave_plan=wave_plan,
                    grader_id=grader_id,
                    task_set_id=task_set_id,
                    task_ids_by_instance=task_ids_by_instance,
                    workflow_ids=workflow_ids,
                    blob_store=blob_store,
                    pending=pending,
                )
            )

    pending_path = args.export_dir / PENDING_BLOBS_FILENAME
    if args.dry_run:
        export_counts: dict[str, int] = {}
        pending_count = len(pending)
    else:
        export_counts = store.export_jsonl(args.export_dir)
        pending_count = pending.flush_to(pending_path)

    total_trials = sum(r.trials for r in results)
    total_grades = sum(r.grades for r in results)
    total_warnings = sum(len(r.warnings) for r in results)
    unbalanced = [r for r in results if r.balance_note]

    print(
        f"migrated {len(results)} wave(s) across {len(CAMPAIGNS)} campaign(s): "
        f"{total_trials} trials, {total_grades} grades, {total_warnings} loader warning(s)"
    )
    print(
        f"excluded {len(EXCLUDED_REPORTS)} report(s): {', '.join(sorted(EXCLUDED_REPORTS))}"
    )
    print(f"pending blobs: {pending_count}")
    if unbalanced:
        print(
            f"\n{len(unbalanced)} wave(s) have arms with mismatched (task_id, run_idx) coverage:"
        )
        for result in unbalanced:
            print(f"  {result.campaign} wave {result.wave_no}: {result.balance_note}")
    if not args.dry_run:
        print(f"\nexported rows: {export_counts}")
        print(f"db: {db_path}")
        print(f"export dir: {args.export_dir}")
        print(f"pending blobs file: {pending_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
