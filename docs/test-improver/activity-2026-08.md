# 🤖 Test Improver — monthly activity summary, August 2026

Rolling summary maintained by the Daily Test Improver workflow (adapted to this
local checkout: no commits, pushes, PRs, or issue comments — changes are left
uncommitted for review). July's summary lives at the repo root
(`test-improver-activity-2026-07.md`); from August, everything lives in
`docs/test-improver/`.

---

## Run log

| Run | Date | Output | Status |
|---|---|---|---|
| 1 | 2026-08-01 08:21 | `tests/test_redis_circuit_breaker_resilience.py` (38 tests; `redis_state.py` 61.92%→97.15%) + report | ⏳ awaiting review |
| 2 | 2026-08-01 | `MockBackend` sampling-param capture (+4 src lines, +4 tests); `docs/index.md` test-count stat regenerated (4,154→4,156); `implementations/` success-audit clean; baseline re-measured | ⏳ awaiting review |
| 3 | 2026-08-01 | **`CoderAgent` could not handle C++** — unescaped `language` in the fence regex; 7-line fix + `tests/test_coder_agent_pipeline.py` (98 tests; `coder.py` 51.59%→**100.00%**); stat 4,156→4,240 | ⏳ awaiting review |

Full details per run: `2026-08-01-run-report.md`, `2026-08-01-run-report-2.md`,
`2026-08-01-run-report-3.md`.

## Current measured baseline (run 3, single-source)

- Unit suite (CI filter, `AGENTIC_NO_LLM=1`): **4,358 collected, 0 failed**, 53
  deselected. Measured with all five untracked test files collected and against
  a dirty working tree (16 modified files unrelated to this workflow).
- Coverage: **85.50%** on the gate scope at run 2 (21,928 stmts, gate 80.00);
  run 3 adds ≈ +0.23 pp from `coder.py` alone (not re-measured suite-wide).
- Suppression ratchet: all five counters at baseline. mypy strict scope clean.
- **Counting method changed** — see "Corrections ledger". Quote the single-pass
  `--co -q` number (12 s), never a sum over shards.

## Review queue (the current bottleneck)

Uncommitted work product accumulated across runs, oldest first:

1. `tests/test_audit_log_failure_paths.py` — 16 tests (Jul run 1); PR body drafted (`pr-body-audit-log.md`)
2. `agents/test_agent.py` + `agents/architect.py` — 11-line `success=` bug fix (Jul run 2); PR body drafted (`pr-body-agent-success-field.md`)
3. `tests/test_test_agent_pipeline.py` — 65 tests (Jul run 2)
4. `tests/test_runtime_docker.py` — DockerRuntime hardening tests
5. `tests/test_redis_circuit_breaker_resilience.py` — 38 tests (Aug run 1)
6. `agentic_v2/models/backends.py` + `tests/test_model_backends.py` — sampling-param capture (Aug run 2)
7. `agents/coder.py` 7-line `re.escape` fix + `tests/test_coder_agent_pipeline.py` — 98 tests (Aug run 3)

**Queue is now 7 deep, one below the workflow's "skip at 8 open PRs" guard.**
The next run should skip or stay minimal unless some of this has drained.

## Decisions awaiting a maintainer

1. **`redis` extra in `dev`** (Aug run 1 §4): the ~75 Redis tests run in CI only
   via fakeredis's transitive pin — same trap shape as the documented EK-extra
   blind spot. Cheapest durable fix in the queue.
2. **`vectorstore.delete` predicate interpolation** (Aug run 1 §5):
   `document_id` interpolated into a LanceDB delete filter — flagged, not fixed.
3. **`_parse_test_files` empty-prefix quirk** (Jul run 2): `typescript`/
   `javascript` fences yield a file literally named after the language; pinned
   as a characterisation test, fixing changes output filenames.
4. **`rag/vectorstore.py` policy**: omit + extra-installed job (the `ek`
   pattern) vs. accepting the drag.
5. **Does `--cov` misbehave in CI** the way it intermittently does in the
   sandbox? Every coverage number rides on this.
6. **`refine()` cannot extract punctuated-language fences** (Aug run 3 §5.1):
   the no-language pattern is `\w+`, so refining C++/C#/Objective-C silently
   yields `success=False, code=""` while `run()` now handles them. Fixing it
   broadens what counts as a fence info string repo-wide.
7. **`_extract_code_fallback` emits unparseable code** (Aug run 3 §5.2): only
   the first line is dedented, so a uniformly-indented block becomes an
   `IndentationError` — and `_parse_output` still stamps it `success=True,
   confidence=0.9`, the same as a clean fenced extraction.
8. **The keyless stub is Python-only** (Aug run 3 §5.4): `AGENTIC_NO_LLM=1`
   exercises `CoderAgent` for Python and nothing else, because the canned
   response hard-codes a ```python fence and the completion predicate is
   language-aware.

## Corrections ledger

- Jul run 1's backlog (two "0%" P1s) was built on faulty shard data — corrected
  in the July summary.
- Aug run 1 named `audit_log.py` 61.95% as next target — stale; it measures
  **84.91%** with the July tests collected (run 2 §4). Its test count (~3,997)
  also missed files that the canonical filter finds (4,269).
- Standing rule: **never act on a coverage row without confirming the module's
  test-file situation** (`grep -rl <module> tests/`).
- **Every historical test count in this file was a shard sum and none
  reconciled** (4,267 / 4,269 / ~3,997). Run 3 measured both ways: 4,260
  collected without the new file, 4,358 with — a clean +98, while the shard sum
  over-counted by 11. **Standing rule: quote the single-pass `--co -q` figure.**

## Backlog (re-measured 2026-08-01, run 3)

`agents/coder.py` **closed at 100.00%** (was the standing P1).
P1 `integrations/metrics.py` 59.12%, `server/routes/runs.py` 66.79% ·
P2 `models/weight_integrity.py` 72.50%, `server/middleware/rate_limit.py`
60.78% · P3 `spa.py` 53.33%, `build_ops.py` 65.40%, `engine/executor.py`
69.27% (edge cases only), `reviewer.py` 66.07% / `orchestrator.py` 72.68%.
Known non-gaps: `evalkit_bridge.py` (ADR-042 skip-by-design),
`rag/vectorstore.py` (uninstalled extra). Full table in run report 3 §7.

## Environment memory (sandbox)

- Recipe: `uv venv --python 3.11` + root pkg +
  `agentic-workflows-v2[dev,server,mcp,langchain,tracing]` +
  `agentic-v2-eval[dev]`, each `-c ci-constraints.txt`; seconds on a warm uv
  cache.
- Hard 45 s per shell call, background processes reaped → run the suite in
  ~10 alphabetical/directory shards with `--cov=agentic_v2 --cov-append`,
  `COVERAGE_FILE=/tmp/covwork/.coverage`, `PYTHONPYCACHEPREFIX=/tmp/pycache`.
  Package-scoped `--cov` works; module-scoped crashes
  (`KeyError: 'pydantic.root_model'`). Per-shard fail-under noise is
  meaningless; only the final `coverage report` matters.
- A shard killed at 45 s writes no coverage (pytest-cov writes at session end) —
  safe to split and re-run.
- **No git write commands** (FUSE mount denies `unlink`; a July `checkout` left
  a stale `index.lock`). Restore files by copying from `git show HEAD:<path>`.
- `scripts/generate_doc_stats.py` hangs here (`Path.rglob` → `os.scandir` stall
  on the FUSE mount; `du`/`tar` and `grep -r` over `tests/` stall the same way
  while `find` is fine). Replicate its backend-test count with
  `find … -name 'test_*.py'` + the same AST predicate, and edit the generated
  literal directly. Any run that adds/removes tests MUST do this or it leaves
  `just docs` red. Run 3 recomputed the pre-change value as 4,156 — exactly the
  committed literal — so the replication is confirmed correct.
- `black` warns "cannot parse code formatted for Python 3.15" and then
  misreports; pass `--target-version py311` to get a usable check.
- Sharding note: the suite splits cleanly into 9 foreground batches under 45 s
  — the 12 test directories in 3 batches, then `ls tests/test_*.py` in slices
  of 40/30/30/30/20/17. Use shards to prove nothing fails; use a single
  `--co -q` pass (12 s) for the count.
