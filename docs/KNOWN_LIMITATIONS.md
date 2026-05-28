# Known Limitations

> **Audience:** Operators, auditors, and contributors reading failing CI or trying to understand why something "works but not quite."
> **Outcome:** After reading, you know what is intentionally unfinished and what the next sprint is expected to address.
> **Last verified:** 2026-05-21

This is an honest accounting. Every item here is real, reproducible, and has shipped into the current release. Nothing here is a guess. If you find a new limitation, add it — do not paper over it elsewhere.

Each item includes a **Status** (reflecting how we're treating it today) and an **Upstream fix** field pointing at the relevant ticket, workaround, or follow-up.

---

## 1. Typed gates that are not fully enforced

### 1.1 Python ↔ TypeScript wire format is manually mirrored (partial)

`agentic_v2/contracts/events.py` defines the execution-event discriminated union in Python; `ui/src/api/types.ts` mirrors it by hand. Drift is caught by reviewer eyeball, not by automation.

Sprint 1 (S1-1) extended the schema-drift CI gate to cover six HTTP response shapes — `DAGResponse`, `WorkflowInputSchemaResponse`, `WorkflowEditorStep`, `RunsSummaryResponse`, `ExecutionEvent`, and `StepResultRecord`. These six shapes now have committed JSON schema snapshots under `tests/schemas/` and the gate regenerates them in CI. Other endpoint payloads (beyond these six) remain hand-mirrored without an automated drift check.

- **Surface:** Any new event field in the uncovered endpoints requires an edit in both files.
- **Risk:** Silent shape mismatches between backend emit and frontend decode for endpoints not yet covered by the drift gate.
- **Workaround:** When editing `contracts/events.py` or `server/models.py`, grep `ui/src/api/types.ts` for the type name and update in the same PR.
- **Status:** Partially resolved by S1-1 (six shapes now gated). Remainder ratified as manual in [ADR-014](adr/ADR-014-pydantic-wire-format.md).
- **Upstream fix:** Future sprint — extend gate coverage to remaining endpoint payloads.

---

## 2. API quirks

### 2.1 LangChain adapter requires a separate extras install

Running `agentic run <workflow> --adapter langchain` requires that the package was installed with the `[langchain]` extras:

```bash
pip install -e ".[dev,server,langchain]"
```

A bare `pip install -e ".[dev,server]"` will succeed, but any `--adapter langchain` call fails at import time.

- **Surface:** `agentic_v2/langchain/` imports are guarded with `try/except ImportError`.
- **Risk:** Confusing first-run failure if a contributor installed minimal extras.
- **Workaround:** Install with `langchain` extras (included in `just setup`), or pass `--adapter native` explicitly.
- **Status:** The _late_ error has been resolved by S1-6: `AdapterRegistry.validate_selected()` now runs at FastAPI lifespan startup and raises `ConfigurationError` with an install hint before any request is processed. The optional-extras design is still correct; only the error timing improved. See [ADR-020](adr/ADR-020-langchain-adapter-eager-validation.md).
- **Upstream fix:** None further needed for the server path. CLI `agentic run --adapter langchain` surfaces the error at adapter resolution time (outside the FastAPI lifespan); may benefit from an explicit pre-flight check in a future sprint.

---

## 3. CI and environment dependencies

### 3.1 Placeholder mode exists but CI still validates provider integration

The runtime supports `AGENTIC_NO_LLM=1` for deterministic placeholder execution across both native and LangChain engines (committed in `c2aff71`, documented in [`docs/NO_LLM_MODE.md`](NO_LLM_MODE.md)). However, some end-to-end CI gates intentionally exercise GitHub Models through `GITHUB_TOKEN` to validate provider integration itself. The trade-off is ratified in [ADR-016](adr/ADR-016-github-token-as-default-e2e-llm.md).

- **Surface:** `ci.yml`, `nightly.yml`, `performance-benchmark.yml` (which require live provider credentials).
- **Zero-config alternative:** Set `AGENTIC_NO_LLM=1` to run workflows without any LLM provider. See [`docs/NO_LLM_MODE.md`](NO_LLM_MODE.md) for scope and limitations.
- **Risk:** A GitHub Models outage or rate-limit event fails the provider-integration CI jobs, but `AGENTIC_NO_LLM=1` jobs remain unaffected.
- **Workaround:** `agentic run test_deterministic` or `AGENTIC_NO_LLM=1 agentic run <workflow>` runs entirely without LLM calls — use for shape and flow testing.
- **Status:** Accepted for v0.3.0. Free LLM access in CI vs. provider dependency trade-off is explicit in ADR-016.
- **Upstream fix:** None — placeholder mode is live. Future work: extend mode to evaluation/rubric scoring.

### 3.2 Windows is a first-class target but has specific gotchas

Epic 3 hardened the Windows bring-up story. Known residual friction:

- `npx` is unreliable on Windows PATH; always use `npm` for running scripts.
- `jq` is not available; JSON parsing in scripts uses `python -c` or `grep`.
- `pnpm` fails with EPERM on mounted / shared drives; fall back to `npm`.
- PowerShell run from Git Bash mangles `$_` and `$_.Property` — wrap with `powershell.exe -NoProfile -Command '…'` and single quotes.

- **Surface:** Developer workflow scripts.
- **Status:** Documented here and in onboarding guidance. No single fix — all require awareness.

---

## 4. Operational gaps

### 4.1 Rate limiting is in-process only

The `slowapi` global rate limiter and the `AuthThrottle` per-IP auth throttle (both introduced in S1-2) store all counters in the server process's memory. In a multi-replica deployment (load balancer distributing across N instances), each replica maintains an independent counter, so the effective per-IP limits are multiplied by N.

- **Surface:** `agentic_v2/server/app.py` (slowapi setup), `agentic_v2/server/auth.py` (AuthThrottle).
- **Risk:** A determined caller can exceed the intended rate cap by distributing requests across replicas.
- **Workaround:** Run a single server replica, or enforce rate limits at the reverse proxy / API-gateway tier.
- **Status:** Accepted for Sprint 1. Sprint 2's T1-2 shipped the circuit-breaker Redis backend only; `slowapi` and `AuthThrottle` counters remain in-process.
- **Upstream fix:** Future sprint — add Redis backend for `slowapi` and `AuthThrottle`. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).

### 4.2 Per-IP auth throttle shares the same multi-replica caveat

`AuthThrottle`'s per-IP 401-failure window is in-process for the same reason as §4.1. A distributed attacker who splits authentication-probe requests across replicas can stay under each replica's threshold while collectively exceeding the intended lockout threshold.

- **Surface:** `agentic_v2/server/auth.py` (`AuthThrottle` class).
- **Risk:** Brute-force auth attempts from a distributed source can evade per-replica lockout.
- **Workaround:** Same as §4.1 — single replica or ingress-level throttling.
- **Status:** Accepted for Sprint 1. Sprint 2's T1-2 covered the circuit-breaker Redis backend only; `AuthThrottle` remains in-process.
- **Upstream fix:** Future sprint — shared Redis store for `AuthThrottle`. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).

---

## 5. Documentation and process

### 5.1 Implementation plans for Epics 3, 5, and 6 are retrospective

Epics 1 and 2 have proper pre-implementation plan docs. Epics 3, 5, and 6 shipped without plan docs — the retrospective plans under [`implementation notes/retro-epic*`](https://github.com/tafreeman/agentic-runtime-platform/tree/main/docs/implementation notes) were written after the fact to preserve decision history. They are shorter and less exhaustive than the Epic 1/2 plans.

- **Risk:** Decision rationale may be under-documented compared to prospective plans.
- **Mitigation:** Three load-bearing decisions from Epic 6 are called out in [`retro-epic6-eval-depth.md`](implementation notes/retro-epic6-eval-depth.md).
- **Status:** Accepted; new epics are expected to ship with prospective plans going forward.

### 5.2 `Generated:` and `Last Updated:` dates in docs may lag

Per-package deep-dive docs under `docs/architecture-*.md` carry generation dates that were set during an initial documentation pass (2026-04-16 to 2026-04-18). Subsequent epic work may have moved details under them without updating the dates.

- **Status:** Accepted. Trust the current code over the doc when the date is older than 2 weeks; file an issue.
- **Upstream fix:** Future sprint — audit and either refresh or re-date.

---

## 6. How this list is maintained

- Any limitation discovered in the wild should be added here with a Status and a workaround. Do not hide limitations in issue trackers.
- When a limitation is fixed, remove the entry and link the fix from `CHANGELOG.md` under the release it shipped in.
- The "Last verified" date at the top of this document is refreshed whenever an entry is added, resolved, or materially changed.
