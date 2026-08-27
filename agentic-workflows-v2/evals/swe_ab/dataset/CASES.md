# The `arp-swe-own-code` eval set

Cases are mined from **our own repositories' real fix commits**, not written from
imagination and not drawn from a public benchmark. A case is a commit that (a)
changed exactly one source file, (b) added or changed at least one test, and (c)
whose message is a `fix(...)` or `test:` type. The parent commit becomes the
broken repo; the commit's own tests become the hidden oracle.

Why mined rather than authored: an authored bug is a bug we already know how to
describe, which leaks the answer into the prompt. A real fix commit carries the
symptom (the failing test) separately from the cause (the diff), which is exactly
the split the eval needs.

## Source repos

| Repo | Path | Notes |
|---|---|---|
| agentic-evalkit | `C:/Users/tandf/source/agentic-evalkit` | Python 3.11+, `uv run pytest` |
| executionkit | `C:/Users/tandf/source/executionkit` | Python, pytest |
| agentic-runtime-platform | `C:/Users/tandf/source/agentic-runtime-platform` | this repo; mine from `agentic-workflows-v2/` |
| financial-scenario-engine | `C:/Users/tandf/source/financial-scenario-engine` | TypeScript — **excluded from v1**, single-language harness |

## Case layout on disk

```
dataset/cases/<CASE_ID>/
  repo/                      # working tree at the PARENT commit, source only
    <module under repair>
    tests/                   # the public tests as they were BEFORE the fix
  oracle/
    oracle.json              # metadata, below
    hidden_tests/            # the fix commit's tests — never shown to the agent
    gold/                    # the fix commit's version of the source file
```

`CASE_ID` is `<REPO>-<KIND>-<NNN>`, e.g. `EVK-BF-001`.
`KIND` ∈ `BF` (bug fix), `FE` (feature), `RF` (refactor, behaviour-preserving),
`TS` (test authoring).

## `oracle.json`

```json
{
  "case_id": "EVK-BF-001",
  "source_repo": "agentic-evalkit",
  "fix_commit": "a720fbf",
  "parent_commit": "71a1f2a",
  "target_file": "src/agentic_evalkit/targets/subprocess.py",
  "failing_test": "tests/unit/targets/test_subprocess.py::test_env_is_not_inherited",
  "hidden_test_command": ["uv", "run", "pytest", "-q", "-m", "not live"],
  "max_changed_lines": 40,
  "license": "repo-internal",
  "contamination_risk": "low|medium|high"
}
```

`contamination_risk` is a judgement about whether a public model could have
memorised the fix: `high` for anything in a repo that is public on GitHub and
older than the model's cutoff, `low` for unreleased/private commits. EvalKit
records this on the run, and any headline number must be reported split by it —
a score carried by `high` cases is not evidence of capability.

## Row schema (`dataset/cases.jsonl`)

One JSON object per line, read by EvalKit's `LocalDatasetProvider`:

```json
{
  "sample_id": "EVK-BF-001",
  "input": {
    "bug_report": "<failing pytest output + one-line symptom, no cause>",
    "code_file": "src/agentic_evalkit/targets/subprocess.py",
    "repo_path": "<absolute path to dataset/cases/EVK-BF-001/repo>",
    "failing_test": "tests/unit/targets/test_subprocess.py::test_env_is_not_inherited"
  },
  "reference": null,
  "metadata": {
    "kind": "BF",
    "source_repo": "agentic-evalkit",
    "contamination_risk": "low",
    "max_changed_lines": 40
  }
}
```

`reference` is deliberately `null`: the ground truth is the hidden test suite,
not a gold string. Nothing in the grading path compares text to a gold patch —
two different correct patches must both score 1.0.

## Size and what it can prove

| Cases | What a paired A/B can detect (80% power, α=0.05) |
|---|---|
| 12 | ~35 percentage-point swing. Directional only. |
| 30 | ~22 pp. Weak evidence. |
| 60 | ~15 pp. Publishable-internally. |

v1 target: **30 cases**, split BF 15 / FE 8 / RF 5 / TS 2, with at least 10
`contamination_risk: low`. Run `attempts: 3` and report pass@1 alongside pass@3 —
a single-attempt score on a 8–30B model is mostly sampling noise.
