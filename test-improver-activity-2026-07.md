# 🤖 Test Improver — monthly activity summary, July 2026

Rolling summary maintained by the Daily Test Improver workflow (adapted to this
local checkout). No commits, pushes, PRs, or issue comments are made — code
changes are left uncommitted for review.

Supersedes `test-improver-report-2026-07-31.md` (run 1), which contains
**incorrect coverage data**; see "Correction to run 1" below. That file can be
deleted once read.

---

## Run 2 — 2026-07-31

### Headline: two exported agents could not complete a single run

While writing coverage tests for `TestAgent`, its own `_parse_output` turned out
to raise on every input:

```
TestAgent:      ValidationError: 1 validation error for TestGenerationOutput
ArchitectAgent: ValidationError: 1 validation error for ArchitectureOutput
```

`TaskOutput.success` is declared **without a default**
(`agentic_v2/contracts/schemas.py:116`). `TestAgent._parse_output` and
`ArchitectAgent._parse_output` both construct their output model without
passing it, so `agent.run(...)` raised `ValidationError` for **any** task, for
both agents. `CoderAgent` (`success=bool(code)`), `ReviewerAgent` and
`OrchestratorAgent` all pass the field — these two were the outliers.

Why it survived: the existing suite (`tests/test_new_agents.py`) exercises only
the private helpers — `_format_task_message`, `_parse_test_files`,
`_count_tests`, `_generate_summary`. It never calls `_parse_output` or `run()`,
which is precisely where the two meet. 36 green tests, agent 100% unusable.

**Fix applied** (4 lines of behaviour, sibling-consistent):

| File | Change |
|---|---|
| `agents/test_agent.py` | `success=bool(test_files)` in `_parse_output` |
| `agents/architect.py` | `success=bool(tech_stack)` in `_parse_output` |

Both mirror `CoderAgent`'s existing `success=bool(code)` idiom: an output no
artifact could be recovered from is not a success. Verified `run()` now returns
for both agents.

### Also fixed: `TestGenerationOutput` missing `__test__ = False`

Every other class in `agents/test_agent.py` (`TestType`, `TestGenerationInput`,
`TestFile`, `TestAgent`) carries `__test__ = False` to keep pytest from
collecting it. `TestGenerationOutput` was the one omission, so importing it into
any test module emitted:

```
PytestCollectionWarning: cannot collect test class 'TestGenerationOutput'
because it has a __init__ constructor
```

One-line fix, no behaviour change.

### New test file

`agentic-workflows-v2/tests/test_test_agent_pipeline.py` — **65 tests**,
uncommitted. Covers the response-handling seam that had nothing on it:

- **`_call_model`** — both branches. The backend-less canned-response path is
  asserted for *internal consistency*: the stub must satisfy the agent's own
  `_is_task_complete`, or a keyless `run()` silently degrades to a
  max-iterations `RuntimeError`. The client path pins delegation, the
  `temperature=0.2` choice, the configured tier, and the
  `content`/`message`/neither response shapes.
- **`_parse_output`** — regression tests for the `success` bug above, plus
  aggregation and the `coverage_estimate` heuristic (its 40 floor, `40 + 3n`
  slope, and 95 cap — three magic numbers with nothing pinning them).
- **`_is_task_complete`** — all four language markers and the negative cases;
  both halves of the predicate are required.
- **`_parse_test_files`** — filename resolution fallbacks, malformed and
  single-line fences, prose between blocks.
- **`_infer_test_type`**, **`_count_tests`**, **`convert_test_types`**,
  **`_format_task_message`** branches (files-vs-code precedence, all five test
  types, mocking strategy, framework override).

**Measured impact:** `agents/test_agent.py` **75.96% → 97.61%** (+21.65 pp;
misses 29→2 statements, partial branches 11→3). `agents/architect.py` also
improves incidentally now that its `run()` path works. Suite-wide that is only
≈ +0.12 pp against the 21,922-statement / 6,282-branch gate scope — the value
here is the defect, not the number.

### Verification

| Gate | Result |
|---|---|
| New file standalone | ✅ 65 passed |
| With `test_new_agents.py`, `test_agents.py`, `test_agents_orchestrator.py` | ✅ 149 passed, **0 warnings** |
| Full unit suite, `-m "not integration and not slow"`, `--ignore=tests/e2e` | ✅ **4,267 passed**, 13 skipped, 2 xfailed, **0 failed** (7 foreground batches) |
| `ruff check` (incl. `--fix` no-op) on changed files | ✅ clean |
| `black --check` on changed files | ✅ clean |
| `mypy agentic_v2/engine agentic_v2/contracts` (strict CI form) | ✅ no issues, 26 files |

Not run: UI (`vitest`), `agentic-v2-eval` (untouched by this change), `just docs`.

---

## Correction to run 1 (2026-07-31)

Run 1's §3 backlog was built on **faulty coverage data**. Both of its P1 items
were artifacts, and acting on either would have wasted a run:

| Run 1 claim | Reality (measured this run) |
|---|---|
| `agents/test_agent.py` — **0.00%**, "zero tests anywhere" | **75.96%**. `tests/test_new_agents.py` has ~190 lines of `TestAgent` tests. |
| `scoring/evalkit_bridge.py` — **0.00%**, "currently untested" | `tests/test_evalkit_bridge.py` exists with **17 tests**, including `Scorer` parity. It `importorskip`s `agentic_evalkit`, so it *skips* in CI — by design, per ADR-042. Not the same as untested. |

Likely cause: run 1 collected coverage in `--cov-append` batches to fit a
45-second sandbox cap; a batch that failed to record leaves a module reading 0%
rather than absent. **Do not act on a 0% row without confirming the module has
no test file** — `grep -rl <ModuleName> tests/` is a two-second check.

Run 1's audit-log work (`tests/test_audit_log_failure_paths.py`, 16 tests) was
re-run this session as part of the full sweep and is green; its numbers were not
independently re-verified.

---

## Environment notes (memory for future runs)

- **`--cov` / `pytest-cov` is broken in this sandbox.** Any run using it dies in
  `conftest.py` with `KeyError: 'pydantic.root_model'` from
  `contracts/chat.py:140` (`class ChatRequest(RootModel[ChatRequestValue])`).
  Plain `python -m coverage run -m pytest` works. Unverified whether CI is
  affected — worth a look, since it would make every coverage number suspect.
- Background processes (`nohup`, `setsid`, `disown`) **are reaped** shortly
  after the spawning call returns. Long runs must be foreground batches under
  45s; the full unit suite splits cleanly into 7.
- `COVERAGE_FILE` must point at a directory the run owns
  (`/tmp/covwork/.coverage`), else `erase()` fails with `PermissionError`.
- Env recipe: `uv venv --python 3.11` + root pkg, then
  `agentic-workflows-v2[dev,server,mcp,langchain,tracing]` and
  `agentic-v2-eval[dev]`, each `-c ci-constraints.txt`. ~90 s.
- Stale Windows `__pycache__` in the checkout surfaces `C:\Users\...` paths in
  Linux tracebacks with `???` source lines. `PYTHONPYCACHEPREFIX=/tmp/pycache`
  sidesteps it.

---

## Backlog — re-measure before acting

Run 1's table is not trustworthy (see correction). These are the items worth
confirming first, cheapest and most defensible at the top:

1. **`_parse_test_files` empty-prefix quirk.** `typescript`/`javascript` set
   `test_prefix = ""`, and every string satisfies `str.startswith("")`. The
   first branch of the filename resolution therefore always wins for those
   languages: a bare ` ```typescript ` fence yields a file literally named
   `typescript`, and the `generated.test.ts` fallback below it is **unreachable**.
   Pinned as a characterisation test (`test_empty_test_prefix_swallows_the_language_fence`)
   rather than fixed — it changes output filenames, so it is your call.
2. **Dead code in the same method.** `if i >= len(parts): break` cannot fire —
   `range(1, len(parts), 2)` already guarantees it. Likewise
   `convert_test_types`' non-`str` branch is unreachable, since `TestType`
   subclasses `str`.
3. **`MockBackend.call_history` drops sampling params.** It records `model`,
   `messages`, `tools`, `**kwargs` — but `max_tokens` and `temperature` bind to
   named parameters, so no test can assert on them through the backend. Adding
   them is a two-line test-infrastructure win.
4. **Audit whether other agents omit `success=`.** This run checked the five in
   `agentic_v2/agents/`; the `implementations/` subpackage is in
   `[tool.coverage.run] omit` and was not swept.
5. Re-measure the real coverage floor with `coverage run` (not `--cov`) before
   picking the next target.

## Suggested actions (human in the loop)

1. Review the 11-line production diff — it is the whole point of this run.
   Suggested split: `fix(agents): populate required success field in
   TestAgent/ArchitectAgent output` and `test(agents): cover TestAgent model-call
   and parsing pipeline`.
2. Decide on backlog item 1 (empty-prefix filename resolution).
3. Check whether `--cov` fails in CI the way it does here.
