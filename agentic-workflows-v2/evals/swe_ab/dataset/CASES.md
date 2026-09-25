# The `arp-swe-own-code` eval set

Two lanes feed the same two arms. Both present a case the same way -- a bug
report, one file to repair, and a failing test -- so a workflow never knows
which lane it is running.

| Lane | `kind` | Cases | Where they come from | Graded by |
|---|---|---|---|---|
| Mined mutation | `MUT` | 132 | Our own repositories (`tools/mine_cases.py`) | The source repo's own pytest suite, in a throwaway worktree |
| SWE-bench | `SWEBENCH` | varies per wave | SWE-bench Verified instances (`tools/build_swebench_cases.py`) | The official SWE-bench Docker harness (`container_harness.py`) |

Ground truth in both lanes is **a test that has to go from failing to
passing**, never a gold-patch string. `reference` is `null` in every row on
purpose: two different correct repairs must score the same.

## Lane 1: mined mutation cases (`MUT`)

A case is one semantic mutation applied to a single function in a source file
the repo's own tests already cover. A mutation only becomes a case if running
the covering test file actually fails afterwards **and** the failure names a
concrete test. `tools/mine_cases.py` does this; nothing in it calls a model.

Why mutation rather than authored bugs: an authored bug is one we already know
how to describe, which leaks the answer into the prompt. A mutation carries the
symptom (the failing test) separately from the cause (the flipped operator),
which is the split the eval needs.

The four mutation operators, and how the 132 shipped cases divide between them:

| `mutation.kind` | What it does | Cases |
|---|---|---|
| `compare` | Flips a comparison (`Is` → `IsNot`, `Lt` → `LtE`, `Eq` → `NotEq`, …) | 58 |
| `offbyone` | Increments an integer literal | 34 |
| `not` | Drops a `not` (never inserts one) | 23 |
| `boolop` | Flips `And` ↔ `Or` | 17 |

### Source repos

| Repo | `source_repo` | Path | Cases |
|---|---|---|---|
| agentic-evalkit | `evk` | `C:/Users/tandf/source/agentic-evalkit` | 50 |
| executionkit | `ek` | `C:/Users/tandf/source/executionkit` | 37 |
| agentic-runtime-platform | `arp` | `C:/Users/tandf/source/agentic-runtime-platform/agentic-workflows-v2` | 30 |
| memoryctl | `memoryctl` | `C:/Users/tandf/source/repos/memoryctl` | 15 |
| financial-scenario-engine | — | — | excluded: TypeScript, single-language harness |

Each repo is graded in a throwaway git worktree pinned to the revision its
cases were mined at, never in the repo itself (`run_ab.prepare_grading_worktrees`).
A case file that mixes revisions for one repo is rejected rather than graded at
an arbitrary checkout.

### Case layout on disk

```
dataset/cases/<CASE_ID>/
  broken.py       # the mutated file -- what the agent is given
  gold.py         # the file before mutation, for diffing only; never graded against
  failure.txt     # the pytest failure excerpt the bug report is built from
  oracle.json     # metadata, below
```

Flat, four files. There is no `repo/` or `oracle/` subdirectory: the grader
writes the returned file over `target_file` inside a worktree of the real source
repo, runs `test_command`, then restores the original -- so a case never needs to
carry a source tree of its own.

`CASE_ID` is `<REPO>-MUT-<NNN>`, e.g. `EVK-MUT-001`, `MEMORYCTL-MUT-015`.

### `oracle.json`

```json
{
  "case_id": "EK-MUT-001",
  "kind": "MUT",
  "source_repo": "ek",
  "repo_path": "C:/Users/tandf/source/executionkit",
  "target_file": "executionkit/batches.py",
  "test_file": "tests/test_batches.py",
  "test_command": ["<repo venv python>", "-m", "pytest", "-x", "-q", "--no-cov",
                   "-m", "not live", "-p", "no:cacheprovider"],
  "failing_tests": ["tests/test_batches.py::TestConsensusBatch::test_majority_happy_path"],
  "max_changed_lines": 40,
  "mutation": {"line": 361, "kind": "compare", "what": "Is -> IsNot"},
  "contamination_risk": "medium"
}
```

`test_command` names the source repo's **own** interpreter, so a case is always
graded under the dependency set its repo actually pins.

## Lane 2: SWE-bench cases (`SWEBENCH`)

`tools/build_swebench_cases.py` maps a SWE-bench Verified instance onto the
same four inputs: problem statement, the file the gold patch touches, that
file's contents at `base_commit` (read out of the prebuilt instance image at
`/testbed`), and the first `FAIL_TO_PASS` test.

**This is the oracle-retrieval setting, and that is a real limitation.** The
model is told which file to fix. Full SWE-bench also requires *finding* it,
which is a large part of the benchmark's difficulty. Localisation is excluded
deliberately -- the question under test is whether a review loop improves
repair, not whether it improves search -- but a number produced this way is not
comparable to a SWE-bench leaderboard score and must never be reported as one.
Rows carry `"retrieval": "oracle"` so this cannot be lost downstream.

Wave indices live alongside this file as `cases.swebench.*.jsonl`; which waves
were drawn, and against which model, is recorded in `docs/EVIDENCE.md`.

## Row schema (`dataset/cases*.jsonl`)

One JSON object per line, read by EvalKit's `LocalDatasetProvider`:

```json
{
  "sample_id": "EVK-MUT-001",
  "input": {
    "bug_report": "<failing pytest output + one-line symptom, no cause>",
    "code_file": "src/agentic_evalkit/targets/subprocess.py",
    "repo_path": "<absolute path to the source repo>",
    "failing_test": "tests/unit/targets/test_subprocess.py::test_env_is_not_inherited"
  },
  "reference": null,
  "metadata": {
    "kind": "MUT",
    "source_repo": "evk",
    "contamination_risk": "medium",
    "max_changed_lines": 40,
    "test_file": "tests/unit/targets/test_subprocess.py"
  }
}
```

`SWEBENCH` rows carry the same shape with `kind: "SWEBENCH"`, plus
`instance_id`, `difficulty`, and `retrieval`.

### `contamination_risk`

A judgement about whether a public model could have memorised the fix. What is
actually recorded today:

- All 132 `MUT` cases: `medium`. The source repos are public on GitHub, but the
  mutation itself is synthetic and was never committed, so the *defect* cannot
  have been memorised even though the correct code may have been.
- `SWEBENCH` cases: `high`. SWE-bench Verified predates every model under test
  and its solutions are on the public web.

EvalKit records this on the run. Any headline number must be reported split by
it -- a score carried by `high` cases is not evidence of capability.

## Size and what it can prove

| Cases | What a paired A/B can detect (80% power, α=0.05) |
|---|---|
| 12 | ~35 percentage-point swing. Directional only. |
| 30 | ~22 pp. Weak evidence. |
| 60 | ~15 pp. Publishable-internally. |
| ~200 | ~8 pp. What this campaign's question actually needed. |

Reproduced from `docs/BEST-PRACTICES.md` §2, which is the source of record for
these figures; do not re-derive them here.

The shipped `MUT` set is 132 cases -- between the last two rows, so enough to
rule out a large effect and not enough to resolve a small one. It also runs
close to its ceiling (the full set scored 110/132 in Arm A and 120/132 in Arm
B), which costs more power than the raw `n` suggests: McNemar draws on
discordant pairs only, and agreeing pairs contribute nothing. See
`docs/CAMPAIGN-CLOSEOUT-2026-09.md` for what the campaign actually concluded.
