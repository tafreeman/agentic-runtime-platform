# ADR-023 — Finishing Plan (Option A′: single `executionkit` package)

> **Created:** 2026-06-01
> **Status:** Plan — not yet executed. No code changes have been made under this plan.
> **Companion to:**
> - [`ADR-023-executionkit-runtime-contract-relationship.md`](ADR-023-executionkit-runtime-contract-relationship.md)
> - [`ADR-023-migration-plan.md`](ADR-023-migration-plan.md) (the original P0–P7 plan)
> - [`ADR-023-migration-notes.md`](ADR-023-migration-notes.md) (phase tracker + open decisions + blockers B-1/B-2)
> - [`ADR-023-preservation-matrix.md`](ADR-023-preservation-matrix.md)

---

## 0. Why this plan exists

ADR-023 Option A is **~80% written but not done**:

- All P0–P7 code exists **only in the working tree, uncommitted** — every `ek_*` module is untracked; `client.py`, `settings.py`, `tool_execution.py`, `agent_resolver.py`, `conftest.py` are modified-not-staged.
- **It does not run.** The `ek_*` modules import `executionkit` and `executionkit_contracts`, but neither is declared in `agentic-workflows-v2/pyproject.toml`, and there is no `.venv`. In a fresh environment the imports raise `ModuleNotFoundError`. This is the "failed when running" that caused testing to be deferred.
- **B-1 and B-2 are both still open** (documented in the migration-notes as blockers to default-on). The "48 tests green / 0 regressions" result was achieved with `AGENTIC_EK_PROVIDER` **OFF**, which never exercises the EK path — so that green run does not cover B-1 or B-2.
- The status docs contradict each other: the ADR-INDEX says "P5–P7 in progress"; the migration-notes say all phases "landed (default-on reverted)". Neither is fully accurate.

---

## 1. The decision this plan encodes

The original Option A introduced a separate **`executionkit-contracts`** package as a "zero-dependency seam" so the runtime could type against ExecutionKit's value types without dragging in the HTTP client / httpx / provider machinery.

**That premise is false for this codebase:**

- `executionkit`'s base `dependencies = []` (httpx is an optional extra).
- `executionkit.provider` probes httpx with `try/except` and falls back to stdlib `urllib` — importing the value types never requires httpx.
- The 9-class error tree is already re-exported from `executionkit.provider`, and `executionkit.errors` is stdlib-only.

So the contracts package solved a non-problem. Worse, the actual build made `executionkit-contracts` a **verbatim duplicate** of EK's types (its own files say "COPIED VERBATIM from executionkit.provider"), and `executionkit` was **never** refactored to import from it. The result is two parallel, identically-named class trees:

```
adapter raises  ──▶ executionkit_contracts.errors.ProviderError   (one class)
EK retry checks ──▶ executionkit.errors.ProviderError             (a DIFFERENT class)

isinstance(contracts_error, executionkit.errors.LLMError) == False
```

This dual-tree mismatch means EK's pattern/retry layer cannot classify the provider errors the runtime adapter raises — the **suspected root cause of B-2** (the EK-default-on hang).

### Option A′

> **Collapse to a single package: `executionkit`. Drop `executionkit-contracts` from the runtime.**
> One value-type set (`executionkit.provider.{LLMResponse, ToolCall}`), one error tree (`executionkit.errors.*`). This eliminates the dual-tree bug by construction and removes a duplicate-maintenance liability. The contracts seam's only legitimate justification — a published, independently-versioned stable ABI consumed by multiple external projects — does not apply to a single internal runtime↔engine bridge.

This is a deliberate **amendment** to ADR-023, recorded in F6 — not silent drift.

---

## 2. Canonical dependency

| Package | Canonical location | Install name | Notes |
|---|---|---|---|
| ExecutionKit (engine) | `C:\Users\tandf\source\executionkit` | `executionkit` | hatchling, dynamic version, GitHub `tafreeman/executionkit`, base `dependencies = []`, httpx via `[httpx]` extra. Provides `cost.CostTracker`, `patterns.base._TrackedProvider`, `patterns.react_loop.react_loop`, `patterns.structured.structured`, `provider.{LLMResponse, ToolCall, LLMProvider, ToolCallingProvider}`, `types.Tool`, `errors.*`. |

Four other copies exist on disk and are **not** canonical: `_audit\executionkit`, `github-audit\executionkit`, and two under `_archive\2026-05-29\`. `executionkit-contracts` (`C:\Users\tandf\source\executionkit-contracts`) is **not** declared by the runtime under Option A′.

**Dependency form is to be confirmed before installing** (editable path-dep for local finishing vs VCS-pinned wheel for reproducibility). The deep relative path across the `_audit\` boundary is fragile; a tagged VCS dependency on `tafreeman/executionkit` is the reproducible long-term form.

---

## 3. Target end-state

- One value-type set + one error tree, both from `executionkit`.
- `agentic_v2.models` and `agentic_v2.engine` depend on **`executionkit` only**.
- The `AGENTIC_EK_PROVIDER` opt-in path runs end-to-end; the default is set deliberately (not reverted-by-accident).
- ADR-023 amended to Option A′; ADR-INDEX and migration-notes reconciled; all work committed.

---

## 4. Phases

### F0 — Environment + single-dependency declaration (the unblock)
- Create `.venv` (none exists).
- Add `executionkit` (path/editable) to `pyproject.toml` — e.g. an `ek` optional extra plus a `[tool.uv.sources]` path entry. Pull httpx via `executionkit[httpx]` or the runtime's existing httpx dependency.
- Install `.[dev,server,langchain]` + the `ek` extra.
- **Gate:** `python -c "import executionkit"` and `from agentic_v2.models.ek_provider import SmartRouterProvider` both succeed; `executionkit_contracts` is **not** on the path.

### F1 — Collapse imports to `executionkit` (core of Option A′)
Pure import repoint — no logic change:

| File | Change |
|---|---|
| `agentic_v2/models/ek_adapters.py` (lines 29–38) | `executionkit_contracts.errors` → `executionkit.errors`; `executionkit_contracts.responses` → `executionkit.provider`; fix docstring refs (lines 6, 13) |
| `agentic_v2/models/ek_provider.py` (lines 51–52) | `ProviderError` ← `executionkit.errors`; `LLMResponse` ← `executionkit.provider` |
| `agentic_v2/engine/ek_step_delegation.py` (line 68) | drop `ContractsResponse`; use the single `executionkit.provider.LLMResponse` |
| `agentic_v2/engine/ek_step_delegation.py` (~140, ~218) | **delete the two `cast(...)` hacks** — with one type there is no boundary to bridge |
| `tests/models/test_ek_adapters.py`, `tests/models/test_ek_provider.py`, `tests/models/test_ek_provider_wrapper.py`, `tests/engine/test_step_tool_path.py`, `tests/engine/test_step_ek_delegation.py`, `tests/conftest.py` | repoint imports; update skip-guard messages to reference only `executionkit` |

- **Gate:** `mypy --strict agentic_v2/models agentic_v2/engine` clean **with the casts removed**; all imports resolve.

### F2 — Flag-OFF green floor
- Full `pytest tests/ -q` with `AGENTIC_EK_PROVIDER` unset; confirm the documented "0 regressions" floor still holds after the import collapse. Record the floor as the oracle for later phases.

### F3 — Fix B-1 (lru_cache test-isolation leak)
- `tests/conftest.py` `ek_flag_on` / `ek_flag_off` fixtures: call `get_settings.cache_clear()` on teardown **after** `monkeypatch` undo (bracket both sides), mirroring the `_force_no_llm_env` autouse pattern.
- **Gate:** EK flag tests pass in **full-suite order**, not just in isolation.

### F4 — Verify B-2 is resolved by the collapse; fix any residual
- The collapse removes the suspected root cause: `SmartRouterProvider` now raises `executionkit.errors.*` — the **same tree** EK's `_TrackedProvider` / `react_loop` / retry classify against — so 429 / 401 / 5xx are recognized instead of leaking as unclassified exceptions that can spin.
- **Reproduce before declaring victory:** `pytest -x --timeout=10 --timeout-method=thread` flag-ON under `AGENTIC_NO_LLM=1`; capture the first blocking test's stack. If still hanging, localize residual causes — the `SmartRouterProvider.complete` fallback loop under MockBackend (`get_model_for_tier` re-selection / `_is_model_ready_for_attempt` settling), and the `supports_tools: Literal[True]` vs `bool`-property nuance in react_loop's refusal path.
- **Gate:** flag-ON unit suite completes in time comparable to flag-OFF (minutes, not >600s).

### F5 — Close the usage-normalization drift (now points at the engine)
- Phase-1 promised a `FinishReason` enum plus Gemini-camelCase and Anthropic-cache usage normalization. `executionkit.provider.LLMResponse` has **none** of these (OpenAI/Anthropic snake_case only).
- Recommend **accept + document**: Phase-3 backend canonicalization already emits `prompt_tokens` / `completion_tokens` before the adapter, so the engine's existing branches cover it. Verify with a fixture test; if a gap is proven, add the branch **additively** to `executionkit.provider.LLMResponse`.

### F6 — Default-on decision + docs/ADR reconciliation
- Only after F2–F4 are green: decide the `AGENTIC_EK_PROVIDER` default. Keep **opt-in** unless the flag-ON full suite is green and stable.
- **Amend ADR-023 to Option A′** (single package; contracts seam dropped, with the httpx-premise rationale). Update the ADR-INDEX row 023 and reconcile it with the migration-notes (currently contradictory). Resolve or explicitly defer the still-`pending owner` decision-log items (#1 Gemini-usage location — now moot under one type; #3 cache-hit accounting; #4 model-field; #6 ollama-thinking).
- Record the fate of the `executionkit-contracts` repo (retire / dormant) so it is not mistaken for live.

### F7 — Commit
- Run pre-commit (black, isort, ruff, docformatter, mypy, pydocstyle, detect-secrets) first.
- Stage the `ek_*` modules + wiring edits + tests + fixtures + docs.
- Conventional commit, e.g. `feat(models): ADR-023 Option A′ ExecutionKit bridge (single package, opt-in)`.

---

## 5. Risks

1. **Do not assume the collapse alone fixes B-2.** F4 reproduces the hang before declaring it resolved. Error-tree unification is the *likely* cause, not a certainty.
2. **The additive-only freeze now applies to `executionkit.provider`** (one tree, enforced once). The `executionkit-contracts/tests/test_shapes_frozen.py` guard becomes irrelevant to the runtime; the equivalent guard should live in / already exist in EK.
3. **`supports_tools: Literal[True]`** on EK's `ToolCallingProvider` vs the runtime's `bool` property — verify `react_loop` reads the *value* (F-04 refusal for Gemini) and is not satisfied by mere attribute presence under `runtime_checkable`.
4. **Cross-`_audit\` path-dep is non-portable.** Pin the one canonical `executionkit`; the four stale copies are not it.

---

## 6. Testing strategy (tiered)

- **Floor:** flag-OFF full suite — regression oracle (F2).
- **Opt-in:** flag-ON suite — tool_calls / finish_reason / usage survive end-to-end.
- **Targeted:**
  - B-1 full-suite-order reproduction (F3).
  - B-2 timeout reproduction under `AGENTIC_NO_LLM=1` (F4).
  - **New isinstance test:** an httpx-429 raised by `SmartRouterProvider` is caught as an `executionkit.errors`-retryable error by an EK pattern — locks in the collapse's payoff.

---

## 7. What changed vs the original migration plan

- Two-package dependency model → **one** (`executionkit` only).
- "Fix dual error-tree" → **F1 collapse imports** (eliminates the bug by construction) + **F4 verify B-2 gone**.
- The two `cast(...)` boundary hacks in `ek_step_delegation.py` become explicit deletions.
- F5 usage-normalization drift now targets the engine's `LLMResponse`, not the contracts copy.
- Added an explicit **ADR-023 → Option A′ amendment** (F6).

---

## 8. Suggested execution order

The natural first checkpoint is **F0 + F1** (unblock + collapse), since everything downstream depends on imports resolving. The exact `executionkit` dependency form (editable path-dep vs VCS-pinned wheel) is confirmed with the owner before installing.
