# 🤖 Daily Test Improver — run report

**Date:** 2026-08-01 · **Repo:** `agentic-runtime-platform` · **Branch:** `adr_016`
(`71ee65ae`)
**Outcome:** one test file added — `agentic-workflows-v2/tests/test_redis_circuit_breaker_resilience.py`
**AI transparency:** this report and the added tests were produced by an automated
assistant. No source file was modified; no branch, commit, or PR was created.

---

## 1. Commands discovered and validated

Everything below was executed and passed in a Linux sandbox against a Python
3.11.15 venv built from `pyproject.toml` + `ci-constraints.txt`. The repo's own
`.venv` is a Windows layout (`.venv/Scripts/python.exe`) and is not runnable
from the sandbox, so a throwaway venv was used; **the repo `.venv` was not
touched.**

| Purpose | Command | Result |
|---|---|---|
| Unit suite (CI's form) | `pytest tests/ -q -m "not integration and not slow" --ignore=tests/e2e --timeout=120` | ✅ ~3,997 passed, 0 failed |
| Coverage | `pytest … --cov=agentic_v2` then `coverage report --fail-under=80` | ✅ 83.72% (gate 80%) |
| No-credential baseline | `AGENTIC_NO_LLM=1` on every run above | ✅ green |
| Lint | `ruff check` + `ruff check --fix` drift check | ✅ clean, no autofix drift |
| Format | `black --check`, `isort --profile black --check-only` | ✅ unchanged |
| Suppression ratchet | `python scripts/check_suppression_ratchet.py` | ✅ no counter above baseline |

Two environment notes worth recording for future runs:

- **The sandbox kills background processes between shell calls** (each call gets
  its own PID namespace), so the full suite had to be run in 11 file-sharded
  slices with `--cov-append` against a shared `COVERAGE_FILE`. Per-slice
  `--cov-fail-under` warnings are expected and meaningless; only the final
  aggregate matters.
- **`--cov=agentic_v2.models.redis_state` (module-scoped) crashes** with
  `KeyError: 'pydantic.root_model'`. Use the package-scoped `--cov=agentic_v2`
  that CI uses, then filter with `coverage report --include=…`.

## 2. Opportunity identified

Ranked the measured modules by missed statements, discarding everything in
`[tool.coverage.run] omit` and everything gated behind an uninstalled optional
extra. The top candidates were:

| Module | Coverage | Missed | Verdict |
|---|---|---|---|
| `models/redis_state.py` | 61.92% | 84 | **selected** |
| `server/audit_log.py` | 61.95% | 88 | next candidate |
| `rag/vectorstore.py` | 48.45% | 72 | see §5 — not a real gap |
| `engine/runtime.py` | 59.30% | 60 | candidate |
| `integrations/metrics.py` | 43.65% | 68 | candidate |

`redis_state.py` was chosen on **value, not size**. Its uncovered lines were not
scattered — they formed two coherent, entirely unexercised contracts:

1. **The WATCH/MULTI/EXEC fallback CAS** (`_cas_via_watch`, lines 337–366) had
   **zero** coverage. `cas()` only uses the pre-registered Lua script while
   `_cas_sha` is set; after a `SCRIPT FLUSH` or a Redis failover it silently
   switches to this second, never-tested implementation of the same contract.
   Two implementations that nothing pins together will drift, and the failure
   mode is corrupted circuit-breaker counters across the worker fleet — during
   a failover, i.e. exactly when the breaker matters most.

2. **Graceful degradation.** The module docstring promises it "falls back
   gracefully to local state when Redis is unavailable," but essentially none of
   that machinery was tested: the error branches of `get`/`get_all`/`set`/`cas`/
   `delete`/`save_all_stats`/`_read_raw`/`health_check`, `_handle_connection_loss`,
   CAS retry exhaustion, corrupt-value handling, and `close`/`reconnect`. The
   circuit breaker sits in front of *every* provider call, so an exception
   escaping one of these paths converts "Redis is flaky" into "the router is
   down."

## 3. What was added

**`agentic-workflows-v2/tests/test_redis_circuit_breaker_resilience.py`** — 38
tests, 673 lines, five classes. No source changes, no new dependencies
(`fakeredis[lua]` is already in the `dev` extra), no network I/O, no credentials.

- `TestCasViaWatchFallback` (10) — the fallback CAS: new-key, matching, stale,
  and expect-none-but-exists cases; TTL is applied; a `WatchError` is treated as
  a lost race rather than propagated; two-worker counter merging works on this
  path too. Includes a **parity test** that runs the same four scenarios through
  both the `EVALSHA` and `WATCH` paths and asserts identical `(wrote, stored)`
  outcomes — this is what stops the two implementations drifting.
- `TestGracefulDegradation` (13) — every public method returns its documented
  fallback instead of raising when the client errors mid-flight. The important
  one: **a connection-class error disables the store, a plain command error must
  not.** Broadening `_handle_connection_loss` to all `RedisError` would let a
  single `WRONGTYPE` permanently drop every worker back to local state.
- `TestCorruptStateResilience` (4) — one poisoned key must not break reads of
  the healthy keys; `load_all_stats` drops records that fail `from_dict`
  (`KeyError` and `ValueError` both).
- `TestSaveStatsCasRetryExhaustion` (2) — under permanent contention the loop is
  bounded at `_CAS_MAX_RETRIES` and returns `None` so the caller keeps its
  baseline; a follow-up save then persists the whole delta rather than losing it.
- `TestConnectionLifecycle` (6) — `connect()` degrades instead of raising when
  the redis package is missing or the server is unreachable; `close()` releases
  client and pool and is idempotent; `reconnect()` restores both the connection
  and the CAS script.

### Measured impact

| | Before | After |
|---|---|---|
| `agentic_v2/models/redis_state.py` | **61.92%** (84 missed) | **97.15%** (7 missed) |
| Package total | 83.14% | 83.72% |

The 77 recovered statements in `redis_state.py` are directly attributable. The
only remaining misses are lines 35–41 (the `except ImportError` fallback, dead
whenever redis is installed) and one loop-exit branch at 254→251.

> Coverage was measured against a live working tree in which three unrelated
> source files were being edited concurrently, which accounts for the rest of
> the package-total movement. The module-level number is the reliable one.

### Verification beyond "the tests pass"

Coverage says lines executed, not that a regression would be caught, so three
mutations were injected into `redis_state.py` and reverted (md5-verified
byte-identical restore after each):

| Mutation | Caught by |
|---|---|
| `_handle_connection_loss` broadened to all `RedisError` | `test_command_error_keeps_the_store_connected` |
| `_cas_via_watch` stops refusing a stale expected value | `test_watch_fallback_rejects_mismatched_value`, `test_lua_and_watch_paths_agree[stale-expected]` |
| Retry exhaustion reports success instead of `None` | 3 tests across two classes |

The file also ran clean 3× consecutively (no ordering or timing flakiness) and
passes under CI's marker filter with `AGENTIC_NO_LLM=1`.

## 4. Test-infrastructure observation

**These ~75 Redis tests run in CI only by accident.** CI installs
`agentic-workflows-v2/[dev,server,mcp,langchain,tracing]` — never the `redis`
extra. `redis` arrives only as a transitive dependency of `fakeredis`
(`redis>=4.3`), which is in `dev`. Both existing and new tests are guarded by
`skipif(not _REDIS_AVAILABLE)`, so if fakeredis ever vendors its own client or
drops that pin, the entire Redis suite turns green-by-skipping and
`redis_state.py` coverage silently falls off a cliff with no failing job.

This is structurally the same trap as the documented EK-extra blind spot in
`.claude/rules/portfolio-context.md`, which previously let an ADR-047 regression
through. **Suggested fix:** add `redis[hiredis]` to the `dev` extra (it is
already pinned at 5.3.1 in `ci-constraints.txt`, so this changes nothing about
what CI resolves — it just makes the dependency intentional), or assert in
`tests/conftest.py` that `_REDIS_AVAILABLE` is true when a `CI` env var is set,
so accidental skipping fails loudly. Worth a maintainer decision before it is
implemented.

## 5. Note on `rag/vectorstore.py` (48.45%)

This module looks like the worst gap in the repo but mostly is not: lines
210–402 are the entire `LanceDBVectorStore` class, which only exists when
`lancedb` is importable, and `lancedb` ships in the optional `rag` extra that no
CI job installs. Closing it would mean adding a dependency to a CI job — out of
scope for an autonomous run.

One thing found while reading it that is *not* a coverage issue and does deserve
a look:

```python
# agentic_v2/rag/vectorstore.py:384
self._table.delete(f"doc_id = '{document_id}'")
```

`document_id` is interpolated straight into a LanceDB filter predicate. A
document id containing a single quote breaks the filter, and depending on how
ids are sourced this is predicate injection into a delete. Recommend
parameterising or validating `document_id` and adding a regression test with an
adversarial id. Flagged only — not fixed, since it is a source change in an
untestable-in-CI path.

## 6. Suggested next actions

1. **Review and merge** the new test file (no source changes; nothing to
   regress).
2. **Decide on the `redis` extra** (§4) — the cheapest durable fix in this report.
3. **Next coverage target:** `server/audit_log.py` at 61.95%. Same shape as this
   one — it is a security boundary whose failure paths are the untested part.
4. **Triage the `vectorstore.delete` interpolation** (§5).
5. **Working tree is dirty:** 16 files carry uncommitted edits and three test
   files are untracked (`test_audit_log_failure_paths.py`,
   `test_runtime_docker.py`, plus this run's). Worth a look before the next
   automated run measures a baseline against a moving tree.

### Housekeeping from this run

A `git checkout` used to revert a mutation left a stale `.git/index.lock`
(the FUSE mount denies `unlink`, so git aborted mid-operation). **It has been
removed and `git status` works normally.** No file content was affected — git
takes that lock before touching the working tree, so the aborted command was a
no-op. Future runs in this environment should avoid git write commands entirely
and restore files by copying from `git show HEAD:<path>`.
