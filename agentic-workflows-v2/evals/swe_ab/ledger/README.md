# ledger — campaign results as rows, not files

[Kit](../README.md) · [Docs](../docs/README.md)

A SQLite ledger for multi-arm evaluation campaigns. It replaces the
`reports/*.json` shape, where each run is one file per (arm, wave), the arm is
identified by the filename, and a re-run overwrites the evidence it supersedes.

## Why

An audit of the 1,998 rows persisted across the 42 committed reports found four
problems, all downstream of the same cause — identity living beside the data
instead of in it:

- **No row-level arm identity.** Every row carries the same execution
  fingerprint, `subprocess:python.exe:1:7a123ee172d3e4f7`, across two arms, four
  providers and five models. The fingerprint hashes the subprocess command; the
  arm lives in the environment, which is not hashed.
- **Cost is unrecorded.** `input_tokens`, `output_tokens`, `cost_usd`,
  `latency_ms` and `model_name` are null on all 1,998 rows. The runtime computes
  per-step token counts and drops them before anything writes them down.
- **78% of payloads are unreachable.** 1,553 rows have `output: null` and a
  digest pointing into `artifacts/`, which is gitignored. For those rows the
  workflow and model are on one machine's disk and nowhere else.
- **Writes destroy history.** Reports are written with a whole-file
  `os.replace` to a deterministic path, so re-running a wave discards its
  predecessor.

## The model

Three kinds of data, kept apart.

**Reference** — immutable definitions, addressed by a hash of their contents.
Registering the same thing twice is a no-op.
`blob`, `model`, `price_snapshot`, `prompt`, `workflow`, `workflow_prompt`,
`grader`, `judge_calibration`, `image`, `task_set`, `task`.

**Design** — what you intend to run.
`substrate` (held constant across all arms in a wave), `arm_config` (the thing
being varied), `campaign`, `arm`, `wave`, `wave_task`, `plan_cell`.

**Observation** — what happened. Append-only.
`trial` (one row per wave/arm/task/run_idx), `step_usage`, `spend`, `grade`.

Two terms used throughout:

- **substrate** — task set, harness version, runtime digest, grader, container
  image digests. Frozen across every arm in a wave.
- **arm config** — model, decoding settings, workflow, retrieval mode. The
  independent variable.

Retrieval mode sits on `arm_config`, not `substrate`. When every arm uses
`oracle` it is constant in practice and behaves like substrate; putting it here
means an arm whose premise is better code search can be expressed rather than
hidden.

`trial` keeps two model columns: `model_id` is the model requested,
`models_answered` is the JSON list that actually replied. A mismatch means a
fallback model answered part of the sample, which makes the comparison unequal —
that is an operational failure, not a graded one.

## Rules the database enforces

These were prose, docstrings and scattered checks. As constraints they cannot be
skipped.

| Rule | Mechanism |
|---|---|
| An operational failure is never a wrong answer | A trial with `op_status <> 'ok'` can have no `grade` row at all (trigger) |
| `grade.outcome` is set exactly when a verdict exists | `CHECK ((outcome IS NULL) = (status NOT IN ('pass','fail')))` |
| Results from different conditions are never merged | `trial.substrate_id` must equal its wave's (trigger) |
| Evidence is never destroyed | `UPDATE` and `DELETE` abort on `trial`, `grade`, `spend`, `step_usage`; corrections insert a row with `supersedes` set |
| Arms are distinguishable at the row level | `PRIMARY KEY (wave_id, arm_id, task_id, run_idx)` |
| Images are pinned, not floating | `image.digest` is `NOT NULL` and must start `sha256:` |

Two rules the database cannot express are enforced in `store.py` instead, with
their own exception types: judge calibration validity (a gating judge needs a
non-expired calibration meeting the TNR/TPR floors) and arm balance (arms in a
wave must cover the same task/run pairs before paired statistics mean anything).

## Layout

```
ledger/
  schema.sql        DDL: tables, CHECK constraints, triggers, indexes
  ids.py            content-addressed ids; canonical JSON hashing
  models.py         one frozen dataclass per table, enums, TABLE_ORDER
  store.py          open/register/append, transactions, JSONL export
  blobs.py          content-addressed file store for large payloads
  load_report.py    existing JSON report -> ledger rows (pure, no DB)
  queries.py        pass rates, paired outcomes, cost, completeness
  stats.py          Wilson, McNemar, Cochran's Q, Holm, permutation
  tests/
```

Standard library only. It imports neither `agentic_v2` nor `agentic_evalkit`, so
the ledger is independently testable and the loader stays a pure function over
parsed JSON.

## Running the tests

`evals/` is outside every ARP gate — CI lints `agentic_v2/` and `tests/` only,
typechecks `agentic_v2/engine` and `contracts`, and measures coverage against
`source = ["agentic_v2"]`. Nothing here runs unless you run it:

```bash
python -m pytest evals/swe_ab/ledger/tests -q
python -m ruff check evals/swe_ab/ledger
python -m mypy --strict evals/swe_ab/ledger
```

Run from `agentic-workflows-v2/`. The repo's mypy config excludes `tests/`, so
type errors in this package's tests are invisible to that invocation; pass a
config override to check them too.

## What is tracked

The database itself is not committed. `store.export_jsonl` writes one
deterministically ordered `.jsonl` per table under `ledger/export/`, and that
export is what belongs in git — it diffs, and `import_jsonl` rebuilds the
database from it. Blobs stay on disk under their digest; rows carry a
`retention` of `durable` or `prunable` so transcripts can be deleted without
losing the numbers that go with them.

## Cutover

`../migrate_reports.py` and `../diff_verdicts.py` (one level up, alongside
`analyze.py` and `run_ab.py` — they read `reports/`, `dataset/` and
`workflows/`, none of which this package touches) load the campaign's report
files into the rows above and check the result against `analyze.py`'s own
arithmetic:

```bash
uv run python migrate_reports.py   # writes ledger/campaign.db, ledger/blobs/,
                                    # ledger/export/, ledger/export/pending_blobs.jsonl
uv run python diff_verdicts.py     # McNemar p / paired-bootstrap CI, ledger vs analyze.py
```

37 of the 42 files under `reports/` are migrated as of the last run
(2026-09-02; 5 excluded, each with a reason recorded in
`migrate_reports.EXCLUDED_REPORTS`) into 1,703 trials and 1,130 grades across
21 waves in 8 campaigns. `diff_verdicts.py` compares all 15 two-arm waves that
have an instance both arms verdicted on; all 15 agree with `analyze.py` exactly
on the discordant counts and McNemar's p, and within tolerance on the bootstrap
CI (order-sensitive by construction — see `diff_verdicts.py`'s module
docstring). `pending_blobs.jsonl` is 0 rows on this corpus: every one of the
813 spilled `answer_blob` references resolves against `artifacts/` on the
machine that ran the campaign, but the mechanism (and its `blob` tombstone
fallback for a digest that does not) is exercised in
`ledger/tests/test_migrate_reports.py` regardless.

Regenerating the export needs that machine's gitignored `artifacts/` and
`dataset/swebench_cases/` trees alongside the tracked `reports/`: without the
case trees the migration stops at the first instance whose `oracle.json` is
missing rather than inventing a Task row, and without `artifacts/` every
spilled answer becomes a `blob` tombstone plus a `pending_blobs.jsonl` row.
