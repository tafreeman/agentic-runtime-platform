"""Pure adapter: SWE-AB evaluation report JSON -> ledger dataclass rows.

This module never touches a database and never imports `store` (which owns
`LedgerStore`) or any sibling-system package: it takes a parsed report
`Mapping` in and returns frozen dataclass instances out, so it is testable
without SQLite and cannot create a dependency cycle with the store layer.

Standard library only. Do not add third-party imports here.

Deliberate signature extensions
--------------------------------
The task brief that seeded this module gave three function signatures
verbatim:

    load_report(report, *, campaign_id, wave_id, arm_id, batch_id,
                task_ids, resolve_output=None) -> LoadedBatch
    derive_substrate(report, *, harness_version, evalkit_version,
                      grader_id) -> Substrate
    derive_arm_config(report, *, model_id, workflow_id,
                       retrieval_mode) -> ArmConfig

Those signatures cannot, as written, satisfy the frozen schema (`schema.sql`)
and dataclasses (`models.py`):

* `trial.substrate_id`, `trial.arm_config_id` and `trial.model_id` are
  `NOT NULL` foreign keys. Nothing in a report can tell us which
  `Substrate` / `ArmConfig` / `Model` row a trial belongs to -- those are
  identities owned by whichever code builds the reference tables (model
  catalog, workflow catalog, grader catalog), which this module explicitly
  does not own and must not guess at.
* `substrate.task_set_id` is a `NOT NULL` foreign key to `task_set`, a table
  this module never sees (the brief already establishes the same principle
  for `task_id` via `task_ids`: "the loader does not invent task rows for a
  task set it cannot see"). Re-deriving a `task_set_id` here from
  `resolved_dataset` fields, independently of whatever code actually built
  the `task_set` row, risks *silently* producing a value that looks valid
  but does not match the real row -- exactly the failure mode this module
  is required to avoid ("never silently emit a wrong value").

So `load_report` and `derive_substrate` accept additional required
keyword-only parameters beyond the brief's literal signatures:

* `load_report` additionally requires `task_set_id`, `harness_version`,
  `evalkit_version`, `grader_id`, `model_id`, `workflow_id` and
  `retrieval_mode` -- exactly the inputs `derive_substrate` /
  `derive_arm_config` need beyond the report itself. `load_report` calls
  both internally and folds their output into `LoadedBatch` (matching
  `LoadedBatch`'s stated purpose of holding "any reference rows the loader
  can derive"), so every `Trial.substrate_id` / `Trial.arm_config_id` /
  `Trial.model_id` is filled from a real, caller-vouched-for id rather than
  a placeholder.
* `derive_substrate` additionally requires `task_set_id`, for the reason
  above.

`campaign_id` is accepted (matching the brief) but is not stored on any row
this module produces -- no table in `schema.sql` reachable from here has a
`campaign_id` column (`wave.campaign_id` already exists on a row built
elsewhere). It is folded into every warning message for traceability
instead of being silently unused.

Status mappings (see module-level `_EXEC_STATUS_MAP` / `_GRADE_STATUS_MAP`
below for the authoritative tables, cross-checked against the real
`ExecutionStatus` / `GradeStatus` enums in agentic_evalkit -- not imported,
just read for the vocabulary -- since this module must not import
`agentic_evalkit`):

* `ExecutionStatus.COMPLETED` -> `OpStatus.OK`
* `ExecutionStatus.ERROR` -> `OpStatus.ERROR`
* `ExecutionStatus.TIMEOUT` -> `OpStatus.TIMEOUT`
* `ExecutionStatus.CANCELLED` -> `OpStatus.CANCELLED`
* `ExecutionStatus.FAILED` -> `OpStatus.ERROR`, with a warning. `FAILED` has
  no matching `OpStatus` member ("the system being evaluated crashed or
  reported its own internal error" is, from the ledger's point of view, an
  operational error), so this is the "closest allowed value" case the brief
  asks for -- not a value observed in the real reports under `reports/`
  (only `completed`, `error` and `timeout` occur there), but a real member
  of the enum that must not be mishandled if it appears.
* Anything unrecognised -> `OpStatus.UNAVAILABLE`, with a warning.

* `GradeStatus.PASS` -> status `pass`, outcome `pass`
* `GradeStatus.FAIL` -> status `fail`, outcome `fail`
* `GradeStatus.ABSTAIN` -> status `abstain`, outcome `None`
* `GradeStatus.UNAVAILABLE` -> status `unavailable`, outcome `None`
* `GradeStatus.ERROR` -> status `error`, outcome `None`
* `GradeStatus.PARTIAL` -> status `abstain`, outcome `None`, with a warning.
  The ledger's `GradeStatus` (`models.py`) has no `partial` member (it only
  allows `pass`/`fail`/`abstain`/`unavailable`/`error`); of those, `abstain`
  ("no clean verdict was rendered") is the closest fit for partial credit,
  which is more than "no verdict" but does not resolve to a binary
  pass/fail either. The original `score` is preserved untouched either way,
  so the partial-credit information is not lost even though the coarser
  `status` column cannot represent it. Not observed in the real reports
  (`summary.partial` is `0` in every report under `reports/`).
* Anything unrecognised -> status `unavailable`, outcome `None`, with a
  warning.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import ids
from .models import (
    ArmConfig,
    Grade,
    GradeStatus,
    OpStatus,
    Outcome,
    Spend,
    StepUsage,
    Substrate,
    Trial,
)

__all__ = [
    "LoadedBatch",
    "UnknownInstanceError",
    "load_report",
    "derive_substrate",
    "derive_arm_config",
    "parse_model_ref",
]


class UnknownInstanceError(ValueError):
    """Raised when a sample's `instance_id` is absent from `task_ids`.

    The loader is not entitled to invent a `task_id` for an instance it
    cannot see a task row for -- the caller must supply a complete mapping.
    """


@dataclass(frozen=True, slots=True)
class LoadedBatch:
    """Everything `load_report` produced from one report, plus a paper trail.

    `warnings` records every field this loader could not populate from the
    source report (and why) -- it is empty only when the report supplied
    everything this loader knows how to map. It is not an error channel:
    `load_report` still returns a complete, usable batch even when
    `warnings` is non-empty.
    """

    trials: tuple[Trial, ...]
    step_usage: tuple[StepUsage, ...]
    spends: tuple[Spend, ...]
    grades: tuple[Grade, ...]
    substrate: Substrate
    arm_config: ArmConfig
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------
# Status vocabulary mapping
# ---------------------------------------------------------------------

#: `ExecutionStatus` (agentic_evalkit) wire value -> `OpStatus` (ledger)
#: value. `FAILED` has no matching `OpStatus` member; it is handled
#: separately below (mapped to `error`, with a warning), not listed here,
#: so its absence is a deliberate branch rather than an omission.
_EXEC_STATUS_MAP: dict[str, str] = {
    "completed": OpStatus.OK.value,
    "error": OpStatus.ERROR.value,
    "timeout": OpStatus.TIMEOUT.value,
    "cancelled": OpStatus.CANCELLED.value,
}

#: `GradeStatus` (agentic_evalkit) wire value -> ledger (status, outcome).
#: `PARTIAL` has no matching ledger `GradeStatus` member; handled separately
#: below (mapped to `abstain`/`None`, with a warning).
_GRADE_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    "pass": (GradeStatus.PASS.value, Outcome.PASS.value),
    "fail": (GradeStatus.FAIL.value, Outcome.FAIL.value),
    "abstain": (GradeStatus.ABSTAIN.value, None),
    "unavailable": (GradeStatus.UNAVAILABLE.value, None),
    "error": (GradeStatus.ERROR.value, None),
}


def _map_op_status(raw: Any) -> tuple[str, str | None]:
    """Return `(op_status, warning)`; `warning` is `None` on a clean hit."""
    if isinstance(raw, str) and raw in _EXEC_STATUS_MAP:
        return _EXEC_STATUS_MAP[raw], None
    if raw == "failed":
        return (
            OpStatus.ERROR.value,
            "execution.status 'failed' has no matching op_status; mapped "
            "to the closest allowed value 'error'",
        )
    return (
        OpStatus.UNAVAILABLE.value,
        f"execution.status {raw!r} is not a recognised ExecutionStatus "
        "member; mapped to the closest allowed value 'unavailable'",
    )


def _map_grade_status(raw: Any) -> tuple[str, str | None, str | None]:
    """Return `(status, outcome, warning)`; `warning` is `None` on a clean hit."""
    if isinstance(raw, str) and raw in _GRADE_STATUS_MAP:
        status, outcome = _GRADE_STATUS_MAP[raw]
        return status, outcome, None
    if raw == "partial":
        return (
            GradeStatus.ABSTAIN.value,
            None,
            "grade.status 'partial' has no matching ledger GradeStatus; "
            "mapped to the closest allowed value 'abstain' (score, if any, "
            "is preserved separately)",
        )
    return (
        GradeStatus.UNAVAILABLE.value,
        None,
        f"grade.status {raw!r} is not a recognised GradeStatus member; "
        "mapped to the closest allowed value 'unavailable'",
    )


# ---------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp string; return `None` on anything else.

    Never raises: a malformed or missing timestamp is a "can't derive this"
    situation for the caller to warn about, not a crash.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _wall_seconds(started: datetime | None, finished: datetime | None) -> float | None:
    if started is None or finished is None:
        return None
    return (finished - started).total_seconds()


def _json_array(values: Sequence[str]) -> str:
    """A stable, sorted JSON array literal for a `NOT NULL TEXT` column.

    Empty input renders as `"[]"` -- an explicit, honest "we know of no
    models" rather than `NULL`, which the column does not allow anyway.
    """
    return json.dumps(sorted(set(values)), separators=(",", ":"), ensure_ascii=False)


def parse_model_ref(target_fingerprint: str | None) -> tuple[str, str]:
    """Split a `manifest.target_fingerprint` into `(provider, wire_ref)`.

    Real shapes seen in `reports/*.json`:

        "ollama:deepseek-v4-flash:0731-cloud@20ace0a669f0"
        "nvidia:deepseek-ai/deepseek-v4-flash-0731@321891f06917"
        "openrouter:minimax/minimax-m3:free@a6fd1fce537d"
        null

    The implementation hash after the last "@" is discarded -- this module
    has no Model-row-building responsibility (`family`, `params_b`,
    `quantization`, `context_window`, `serving_mode` are not derivable from
    a report at all), so only the model reference itself is worth
    extracting here.

    Never raises. On `None` or a string with no "@" (so no implementation
    hash to split off), returns the `("unknown", "unknown")` sentinel; the
    caller is responsible for detecting that sentinel and recording a
    warning, since this function's return type carries no warning channel
    of its own.
    """
    if not target_fingerprint or "@" not in target_fingerprint:
        return "unknown", "unknown"
    model_ref, _implementation_hash = target_fingerprint.rsplit("@", 1)
    if ":" not in model_ref:
        return "unknown", "unknown"
    provider, wire_ref = model_ref.split(":", 1)
    if not provider or not wire_ref:
        return "unknown", "unknown"
    return provider, wire_ref


# ---------------------------------------------------------------------
# Reference-row derivation
# ---------------------------------------------------------------------


def derive_substrate(
    report: Mapping[str, Any],
    *,
    harness_version: str,
    evalkit_version: str,
    grader_id: str,
    task_set_id: str,
) -> Substrate:
    """Build the `Substrate` row for one report.

    `task_set_id` is required beyond the brief's literal signature -- see
    the "Deliberate signature extensions" note in this module's docstring.

    `image_digest_set` is computed over an empty set: these reports run a
    subprocess target directly (`target_fingerprint` starts with
    `"subprocess:..."`), and no container image digest appears anywhere in
    the report shape. Callers that DO have image digests for a run should
    not use this function as-is; `load_report`'s caller is expected to
    record a warning for the empty case (this function has no warning
    channel of its own, by design -- see the module docstring).
    """
    manifest = report.get("manifest") or {}
    runtime_digest = str(manifest.get("code_fingerprint") or "unknown")
    image_digests = ids.image_digest_set(())
    substrate_id = ids.substrate_id(
        task_set_id=task_set_id,
        harness_version=harness_version,
        runtime_digest=runtime_digest,
        evalkit_version=evalkit_version,
        grader_id=grader_id,
        image_digest_set=image_digests,
    )
    return Substrate(
        substrate_id=substrate_id,
        task_set_id=task_set_id,
        harness_version=harness_version,
        runtime_digest=runtime_digest,
        evalkit_version=evalkit_version,
        grader_id=grader_id,
        image_digest_set=image_digests,
    )


def derive_arm_config(
    report: Mapping[str, Any],
    *,
    model_id: str,
    workflow_id: str,
    retrieval_mode: str,
) -> ArmConfig:
    """Build the `ArmConfig` row for one report.

    `temperature` and `seed` come from `manifest.sampling`. `top_p`,
    `top_k`, `max_tokens`, `context_window_used` and `tool_policy` are
    absent from every report seen under `reports/*.json`; they are set to
    `None` here rather than defaulted to a made-up number. This function
    has no warning channel of its own (see the module docstring); its
    caller (`load_report`) is responsible for recording that gap.
    """
    manifest = report.get("manifest") or {}
    sampling = manifest.get("sampling") or {}
    temperature = sampling.get("temperature")
    seed = sampling.get("seed")
    arm_config_id = ids.arm_config_id(
        model_id=model_id,
        temperature=temperature,
        top_p=None,
        top_k=None,
        max_tokens=None,
        seed=seed,
        stop_sequences=(),
        context_window_used=None,
        workflow_id=workflow_id,
        retrieval_mode=retrieval_mode,
        tool_policy=None,
    )
    return ArmConfig(
        arm_config_id=arm_config_id,
        model_id=model_id,
        temperature=temperature,
        top_p=None,
        top_k=None,
        max_tokens=None,
        seed=seed,
        stop_sequences=None,
        context_window_used=None,
        workflow_id=workflow_id,
        retrieval_mode=retrieval_mode,
        tool_policy=None,
    )


# ---------------------------------------------------------------------
# Deterministic per-observation ids
#
# Unlike the reference-table ids in `ids.py` (which identify entities that
# may be shared/deduplicated across many loads), these identify a single
# observation *within* one report load. They are still deterministic
# content ids (via `ids.content_id`), just scoped locally to this module
# rather than promoted to the frozen `ids.py` contract.
# ---------------------------------------------------------------------


def _trial_id(wave_id: str, arm_id: str, task_id: str, run_idx: int) -> str:
    return ids.content_id(
        "trl",
        {"wave_id": wave_id, "arm_id": arm_id, "task_id": task_id, "run_idx": run_idx},
    )


def _trace_id(wave_id: str, arm_id: str, task_id: str, run_idx: int) -> str:
    """A synthesized trace id for a historical report with no real trace.

    Every sample in these reports has `trace_refs == []` -- no execution
    trace was ever recorded. `trial.trace_id` is `NOT NULL`, so this mints
    a deterministic id from the trial's own identity tuple instead of
    leaving a real-looking but fabricated trace reference. Prefixed `trc`
    (per the brief) specifically so it reads as synthesized: a real trace
    id from a tracing backend would not carry this module's content-id
    shape, making the two distinguishable on sight.
    """
    return ids.content_id(
        "trc",
        {"wave_id": wave_id, "arm_id": arm_id, "task_id": task_id, "run_idx": run_idx},
    )


def _grade_id(trial_id: str, grader: str) -> str:
    return ids.content_id("gde", {"trial_id": trial_id, "grader": grader})


def _spend_id(trial_id: str) -> str:
    return ids.content_id("spd", {"trial_id": trial_id})


# ---------------------------------------------------------------------
# The adapter itself
# ---------------------------------------------------------------------


def load_report(
    report: Mapping[str, Any],
    *,
    campaign_id: str,
    wave_id: str,
    arm_id: str,
    batch_id: str,
    task_ids: Mapping[str, str],
    task_set_id: str,
    harness_version: str,
    evalkit_version: str,
    grader_id: str,
    model_id: str,
    workflow_id: str,
    retrieval_mode: str,
    resolve_output: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> LoadedBatch:
    """Turn one parsed evaluation report into ledger rows.

    `task_ids` maps `instance_id -> task_id`; this loader does not invent
    task rows for a task set it cannot see, so a sample whose `instance_id`
    is absent from `task_ids` raises `UnknownInstanceError` naming the
    instance.

    `resolve_output`, if given, is called with a spilled sample's
    `artifacts.output_ref` digest and may return the original output
    payload (or `None` if it cannot resolve it). When absent, or when it
    returns `None`, the trial is still produced -- with `answer_blob`
    pointing at the ref the report already gave us -- and a warning names
    every field this loader could not therefore populate. No field is ever
    guessed at to fill the gap.

    See the module docstring's "Deliberate signature extensions" section
    for why this signature carries more keyword-only parameters than the
    literal brief that seeded it.
    """
    substrate = derive_substrate(
        report,
        harness_version=harness_version,
        evalkit_version=evalkit_version,
        grader_id=grader_id,
        task_set_id=task_set_id,
    )
    arm_config = derive_arm_config(
        report,
        model_id=model_id,
        workflow_id=workflow_id,
        retrieval_mode=retrieval_mode,
    )

    warnings: list[str] = [
        f"[campaign={campaign_id} wave={wave_id} arm={arm_id} batch={batch_id}] "
        "arm_config: top_p, top_k, max_tokens, context_window_used, tool_policy "
        "are not present in this report shape; set to None",
    ]

    manifest = report.get("manifest") or {}
    provider, wire_ref = parse_model_ref(manifest.get("target_fingerprint"))
    if (provider, wire_ref) == ("unknown", "unknown"):
        warnings.append(
            f"[campaign={campaign_id} wave={wave_id} arm={arm_id} batch={batch_id}] "
            f"manifest.target_fingerprint {manifest.get('target_fingerprint')!r} is "
            "null or malformed; provider/wire_ref could not be parsed"
        )

    report_generated_at = report.get("generated_at")

    trials: list[Trial] = []
    step_usage: list[StepUsage] = []
    spends: list[Spend] = []
    grades: list[Grade] = []

    for entry in report.get("samples", ()):
        sample_raw = entry.get("sample") or {}
        execution_raw = entry.get("execution") or {}
        grade_raw = entry.get("grade")

        top_sample_id = sample_raw.get("sample_id")
        metadata = sample_raw.get("metadata") or {}
        instance_id = metadata.get("instance_id")
        if not instance_id:
            raise UnknownInstanceError(
                f"sample {top_sample_id!r} has no metadata.instance_id"
            )
        if instance_id not in task_ids:
            raise UnknownInstanceError(
                f"instance_id {instance_id!r} not found in task_ids mapping"
            )
        task_id_ = task_ids[instance_id]

        run_idx = execution_raw.get("attempt")
        if not isinstance(run_idx, int) or run_idx < 1:
            raise ValueError(
                f"sample {instance_id!r}: execution.attempt {run_idx!r} is not a "
                "valid run_idx (expected an int >= 1)"
            )

        ctx = (
            f"[campaign={campaign_id} wave={wave_id} arm={arm_id} "
            f"batch={batch_id} sample={instance_id} run_idx={run_idx}]"
        )

        trial_id_ = _trial_id(wave_id, arm_id, task_id_, run_idx)
        trace_id_ = _trace_id(wave_id, arm_id, task_id_, run_idx)

        started_at_raw = execution_raw.get("started_at")
        finished_at_raw = execution_raw.get("finished_at")
        started_dt = _parse_dt(started_at_raw)
        finished_dt = _parse_dt(finished_at_raw)
        wall_seconds = _wall_seconds(started_dt, finished_dt)
        if wall_seconds is None:
            warnings.append(
                f"{ctx} could not derive wall_seconds from started_at="
                f"{started_at_raw!r} / finished_at={finished_at_raw!r}"
            )

        op_status, status_warning = _map_op_status(execution_raw.get("status"))
        if status_warning is not None:
            warnings.append(f"{ctx} {status_warning}")

        error_raw = execution_raw.get("error")
        error_kind: str | None = None
        if isinstance(error_raw, dict):
            code = error_raw.get("code")
            error_kind = str(code) if code is not None else None
            extra_keys = sorted(set(error_raw) - {"code"})
            if extra_keys:
                warnings.append(
                    f"{ctx} error detail beyond 'code' ({extra_keys}) is not "
                    "persisted; error_blob is left None (writing blobs is out "
                    "of scope for this pure loader)"
                )

        tokens_in = execution_raw.get("input_tokens")
        tokens_out = execution_raw.get("output_tokens")
        cost_usd = execution_raw.get("cost_usd")
        latency_ms = execution_raw.get("latency_ms")
        model_name = execution_raw.get("model_name")
        if (
            tokens_in is None
            and tokens_out is None
            and cost_usd is None
            and latency_ms is None
            and model_name is None
        ):
            warnings.append(
                f"{ctx} input_tokens/output_tokens/cost_usd/latency_ms/model_name "
                "not reported by the source report (all null); mapped to None"
            )

        output = execution_raw.get("output")
        artifacts = execution_raw.get("artifacts") or {}
        output_ref = artifacts.get("output_ref")
        models_answered_list: list[str] = []
        answer_blob: str | None = None

        if output is not None:
            models_answered_list = [str(m) for m in (output.get("models_used") or ())]
            step_count = output.get("step_count")
            if step_count is not None:
                warnings.append(
                    f"{ctx} output.step_count={step_count!r} present but no "
                    "per-step breakdown is available in this report shape; no "
                    "step_usage rows emitted"
                )
        elif output_ref:
            answer_blob = str(output_ref)
            resolved = (
                resolve_output(str(output_ref)) if resolve_output is not None else None
            )
            if resolved is not None:
                models_answered_list = [
                    str(m) for m in (resolved.get("models_used") or ())
                ]
                if "models_used" not in resolved:
                    warnings.append(
                        f"{ctx} resolved output payload for {output_ref} is "
                        "missing 'models_used'"
                    )
                step_count = resolved.get("step_count")
                if step_count is not None:
                    warnings.append(
                        f"{ctx} resolved output.step_count={step_count!r} present "
                        "but no per-step breakdown is available; no step_usage "
                        "rows emitted"
                    )
            else:
                warnings.append(
                    f"{ctx} execution output spilled to blob {output_ref} "
                    f"({'no resolver supplied' if resolve_output is None else 'resolver returned None'}); "
                    "workflow, requested_model, models_used and elapsed_seconds "
                    "are unavailable; models_answered set to an empty list"
                )
        else:
            warnings.append(
                f"{ctx} execution.output is null and artifacts.output_ref is "
                "absent; no output data is available for this trial"
            )

        trial = Trial(
            wave_id=wave_id,
            arm_id=arm_id,
            task_id=task_id_,
            run_idx=run_idx,
            trial_id=trial_id_,
            batch_id=batch_id,
            substrate_id=substrate.substrate_id,
            arm_config_id=arm_config.arm_config_id,
            model_id=model_id,
            models_answered=_json_array(models_answered_list),
            started_at=started_at_raw if isinstance(started_at_raw, str) else "",
            finished_at=finished_at_raw if isinstance(finished_at_raw, str) else None,
            wall_seconds=wall_seconds,
            op_status=op_status,
            error_kind=error_kind,
            error_blob=None,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            trace_id=trace_id_,
            transcript_blob=None,
            answer_blob=answer_blob,
            supersedes=None,
        )
        trials.append(trial)

        if not isinstance(started_at_raw, str) or not started_at_raw:
            warnings.append(f"{ctx} execution.started_at is missing or invalid")

        if cost_usd is not None:
            spends.append(
                Spend(
                    spend_id=_spend_id(trial_id_),
                    trial_id=trial_id_,
                    price_snapshot_id=None,
                    cost_usd=cost_usd,
                    gpu_seconds=None,
                    computed_at=_first_str(
                        report_generated_at, finished_at_raw, started_at_raw
                    ),
                )
            )

        if op_status != OpStatus.OK.value:
            if grade_raw is not None:
                warnings.append(
                    f"{ctx} trial op_status={op_status!r} (not ok); dropping the "
                    f"grade present in the source report (grader="
                    f"{grade_raw.get('grader')!r}) -- an operational failure "
                    "renders no verdict"
                )
            continue

        if grade_raw is None:
            warnings.append(
                f"{ctx} trial op_status=ok but the source report has no grade"
            )
            continue

        g_status, g_outcome, g_warning = _map_grade_status(grade_raw.get("status"))
        if g_warning is not None:
            warnings.append(f"{ctx} {g_warning}")

        evidence = grade_raw.get("evidence") or {}
        if evidence:
            warnings.append(
                f"{ctx} grade evidence ({sorted(evidence)}) is not persisted; "
                "evidence_blob is left None (writing blobs is out of scope for "
                "this pure loader)"
            )

        oracle_provenance = grade_raw.get("oracle_provenance") or {}
        oracle_text = (
            ids.canonical_json(oracle_provenance) if oracle_provenance else None
        )

        grades.append(
            Grade(
                grade_id=_grade_id(trial_id_, str(grade_raw.get("grader", ""))),
                trial_id=trial_id_,
                grader_id=grader_id,
                status=g_status,
                outcome=g_outcome,
                score=grade_raw.get("score"),
                evidence_blob=None,
                oracle_provenance=oracle_text,
                graded_at=_first_str(grade_raw.get("created_at"), report_generated_at),
                supersedes=None,
            )
        )

    return LoadedBatch(
        trials=tuple(trials),
        step_usage=tuple(step_usage),
        spends=tuple(spends),
        grades=tuple(grades),
        substrate=substrate,
        arm_config=arm_config,
        warnings=tuple(warnings),
    )


def _first_str(*candidates: Any) -> str:
    """The first candidate that is a non-empty `str`, else `""`."""
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return ""
