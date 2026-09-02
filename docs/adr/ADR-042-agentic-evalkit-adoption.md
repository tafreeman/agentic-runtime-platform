# ADR-042: Adopt `agentic-evalkit` as ARP's Evaluation Framework (Sliced Migration)

**Status:** Proposed
**Date:** 2026-07-03
**Related:** `agentic-v2-eval/` (in-tree package being superseded),
`agentic_v2/scoring/step_scoring.py`, `agentic_v2/scoring/evalkit_bridge.py`
(new, this slice), `agentic_v2/models/llm.py`, ADR-032 (extract scoring
package), ADR-033 (eval-config root resolution), ADR-023 (ExecutionKit
external-package precedent)

> **Update 2026-08-09.** Two premises in this ADR have since changed. The
> original text is left as written, for the record.
>
> `agentic-evalkit` now has a public remote and is published to PyPI, so the
> install-mechanism ladder below reached **rung 3 (version-range pin) directly**
> — the git-pin rung was skipped. The extra pins `>=0.3.0,<0.4.0`.
>
> CI *does* now install it. The `evalkit-bridge-tests` job in `ci.yml` installs
> the `eval` extra, asserts `agentic_evalkit` genuinely imports, and runs
> `tests/test_evalkit_bridge.py` and `tests/contract/test_evalkit_boundary.py`.
> So "no public git remote today" and "CI for `agentic-workflows-v2` does not
> install `agentic-evalkit`" are both obsolete.
>
> Everything else stands, and still matters: the guarded import, the
> `RuntimeError`-rather-than-ImportError contract, and the one-way boundary are
> unchanged requirements.

## Context

`agentic-v2-eval` is ARP's in-tree evaluation package: rubric-YAML scoring
(`Scorer`), an LLM-as-judge, dataset adapters, sandboxed execution, and
multi-format reporting. It is a monorepo workspace member
(`[tool.uv.workspace] members` in the root `pyproject.toml`) installed
directly into CI (`.github/workflows/ci.yml`).

A standalone library, `agentic-evalkit`, has been built independently (see
`agentic-evalkit` in the wider workspace) as a general-purpose evaluation
framework: typed, frozen Pydantic contracts (`EvalSample`,
`NormalizedExecutionResult`, `GradeResult`), a structural `ExecutionTarget`
protocol with callable/subprocess/HTTP adapters, graders you can combine
(`Rubric`/`RubricCriterion`, `CompositeGrader`/`WeightedGrader`, schema and
judge graders), dataset presets, and multi-format reporting. It enforces its
own architectural boundary with an AST-based contract test: evalkit code may
never import `agentic_v2`, `tools`, or `executionkit`. It has **no public git
remote yet** — it exists only as a local checkout.

ARP already consumes one piece of evalkit's design lineage today in reverse:
`agentic_v2/models/llm.py` imports `LLMClientProtocol` **from**
`agentic_v2_eval.interfaces` (the in-tree package), not the other way
around — `agentic-v2-eval`'s own docs describe this as "exports
`LLMClientProtocol` -> consumed by agentic-workflows-v2." Any migration must
account for that existing ARP -> `agentic_v2_eval` dependency edge, not just
the `agentic_v2 -> agentic_v2_eval` scoring call sites.

We have a working precedent for absorbing an external, independently-versioned
library into ARP: ADR-023 moved `executionkit` from a co-located sibling path
to a published PyPI dependency (`[tool.uv.sources]` no longer points at a
local path; `ek = ["executionkit>=0.1.0,<0.3.0"]` is a normal version-pinned
extra). `agentic-evalkit` is earlier in that same lifecycle — pre-remote,
pre-publish — so the adoption path mirrors ADR-023's ladder but starts one
rung lower.

## Decision

Adopt `agentic-evalkit` as ARP's evaluation framework, **superseding**
in-tree `agentic-v2-eval`, via a sliced migration rather than a single
cutover PR. Each slice is independently mergeable and leaves CI green.

### Install-mechanism ladder

`agentic-evalkit`'s installation method advances as the library matures,
mirroring the ExecutionKit precedent (ADR-023):

1. **Today (Slices A-B): local path dependency, dev-only.** Added as an
   optional `uv` workspace/path source for local development
   (`pip install -e '../agentic-evalkit'`, analogous to how `ek` was
   consumed before ADR-023's PyPI cutover). Not installed in CI.
2. **Once evalkit has a public remote (Slice C onward): pinned git
   dependency.** `agentic-evalkit @ git+https://github.com/<org>/agentic-evalkit@<SHA>`,
   pinned to a specific commit SHA (not a branch) for reproducibility — the
   same discipline ARP already applies to its own dependency pins
   (`ci-constraints.txt`).
3. **Once evalkit publishes to PyPI: version-range pin.** `agentic-evalkit>=X.Y,<Z`
   as a normal `[project.optional-dependencies]` extra, replacing the git
   pin — the end state ADR-023 already reached for `executionkit`.

### The hard dependency invariant

`agentic-evalkit` must never import `agentic_v2`, `tools`, or `executionkit`.
This is enforced **inside evalkit itself** by its own AST-based boundary
contract test, not by anything in this repository. The practical consequence
for ARP: all adaptation logic between the two systems must live on the ARP
side of the boundary. `agentic_v2/scoring/evalkit_bridge.py` (this slice) is
that adapter; evalkit's public API is never modified to accommodate ARP.

### Slice plan

- **Slice A — dependency.** Add `agentic-evalkit` as an optional, dev-only
  local-path dependency. No behavior change; nothing imports it yet.
- **Slice B — bridge (this ADR/PR).** Add
  `agentic_v2/scoring/evalkit_bridge.py`: rubric-YAML -> evalkit `Rubric`
  conversion, a `score_criteria` weighted-score function reproducing legacy
  `Scorer` semantics via evalkit's `Rubric` model, and a
  `workflow_callable_target` factory wrapping an ARP workflow-run coroutine as
  an evalkit `CallableTarget`. **Additive only** — `step_scoring.py` is
  untouched, nothing calls the bridge yet, and evalkit stays optional (not
  installed in CI).
- **Slice C — cutover.** Rewire `step_scoring.py` to call
  `evalkit_bridge.rubric_from_yaml_dict` / `score_criteria` instead of
  `agentic_v2_eval.rubrics.load_rubric` / `agentic_v2_eval.scorer.Scorer`,
  behind the same `_EVAL_AVAILABLE`-style guard (renamed to reflect the new
  optional dependency). Retire the direct `agentic_v2_eval` imports from
  `agentic_v2/scoring/`. `agentic_v2/models/llm.py`'s
  `agentic_v2_eval.interfaces.LLMClientProtocol` import is handled
  separately — see Risks below.
- **Slice D — deprecate and delete `agentic-v2-eval`.** Once Slice C ships
  and nothing under `agentic_v2/` imports `agentic_v2_eval` directly,
  `agentic-v2-eval` becomes a thin deprecated re-export shim (each public
  name re-exported from evalkit, with a `DeprecationWarning`) for one release
  window, then the package is deleted entirely: removed from
  `[tool.uv.workspace] members`, its directory deleted, its CI job
  (`.github/workflows/eval-package-ci.yml`) removed.
- **Slice E — CI cutover.** Once evalkit is the only evaluation dependency,
  update `.github/workflows/ci.yml` at its exact `agentic-v2-eval` references:
  - **Line 27** (`python-smoke` job): `pip install -e "agentic-v2-eval/[dev]" -c ci-constraints.txt`
    -> replaced with the evalkit install per the then-current rung of the
    install-mechanism ladder.
  - **Lines 167, 170, 175** (`test-coverage` job, "Report whole-repo coverage"
    step): the `pip install -e "agentic-v2-eval/[dev]"` install, the
    `agentic-v2-eval/tests` path fed to the whole-repo pytest invocation, and
    the `--cov=agentic-v2-eval/src/agentic_v2_eval` coverage target all need
    updating or removing once `agentic-v2-eval` no longer exists.
  - **`pyproject.toml` `[tool.uv.workspace] members`** (currently
    `["agentic-workflows-v2", "agentic-v2-eval"]`): drop `"agentic-v2-eval"`
    once Slice D deletes the package.

This ADR covers the *decision* and Slice A/B's scope in detail; Slices C-E
are recorded here as the committed plan but implemented in their own PRs.

### Why evalkit stays optional in ARP until the remote exists

`agentic-evalkit` has no public git remote today. A hard dependency on an
unpublished local checkout cannot be installed by CI (no clone target, no
package index entry), so:

- Slices A and B keep `agentic-evalkit` **optional** — guarded-import,
  mirroring the existing `_EVAL_AVAILABLE` pattern in `step_scoring.py`
  (`EVALKIT_AVAILABLE` here, deliberately public rather than
  underscore-prefixed since this module's whole purpose is to be
  evalkit-facing).
- CI for `agentic-workflows-v2` does not install `agentic-evalkit` and must
  stay green without it — every public function in `evalkit_bridge.py` raises
  a clear `RuntimeError` (not an import-time failure) when called with
  evalkit absent, and `tests/test_evalkit_bridge.py` uses
  `pytest.importorskip("agentic_evalkit")` at module level so the whole test
  file skips cleanly rather than erroring.
- The optional status is lifted only once the install-mechanism ladder
  reaches a rung CI can actually resolve (a real remote for the git pin, or a
  PyPI release).

## Consequences

- **`step_scoring.py`'s graceful-degradation contract is preserved
  unchanged in this slice.** Slice B adds a new module; it does not touch
  `step_scoring.py`'s existing `_EVAL_AVAILABLE` guard, `AGENT_RUBRIC_MAP`,
  or scoring behavior. Slice C is where that guard is repointed, and it must
  preserve the same "returns `None`/disables scoring when the dependency is
  absent" behavior `step_scoring.py` already has today — this ADR treats that
  as a hard requirement for Slice C's acceptance, not a nice-to-have.
- **Benchmark preset coverage gap.** evalkit's built-in dataset presets
  (`agentic_evalkit.datasets.presets`) currently number far fewer than ARP's
  benchmark surface via `tools.agents.benchmarks` (HumanEval, MBPP, SWE-bench,
  etc.) — 7 of ARP's 9 benchmark presets have no evalkit-side equivalent yet.
  Those 7 stay ARP-side (continue to load through the existing
  `tools.agents.benchmarks` lazy-import path) until evalkit's preset catalog
  grows to cover them; this is not blocking for Slices A/B, which touch
  rubric/criterion scoring and workflow execution wrapping only, not dataset
  loading.
- **`LLMClientProtocol` does not move.** `agentic_v2_eval.interfaces.LLMClientProtocol`
  is a small, ARP-consumed structural protocol (`generate_text(model_name,
  prompt, temperature, max_tokens, **kwargs) -> str`) that predates and is
  independent of evalkit's typed contracts (`EvalSample`,
  `NormalizedExecutionResult`, etc.) — it is a synchronous, string-in/string-out
  LLM-call shape, not an evaluation contract. It is **not** an ARP-internal
  utility as might be assumed by analogy with the rest of this migration —
  it is currently defined inside `agentic_v2_eval` and imported *by* ARP
  (`agentic_v2/models/llm.py`). Moving it into evalkit would import
  `agentic_v2_eval`'s only remaining ARP-facing export into a library whose
  entire premise is zero ARP awareness, which is backwards. When Slice D
  deletes `agentic-v2-eval`, `LLMClientProtocol` needs a landing spot
  decided explicitly (candidates: inline into `agentic_v2/models/llm.py`
  since ARP is its only consumer, or a small ARP-owned protocols module) —
  it does **not** default to moving into `agentic-evalkit`. Flagged here so
  Slice D does not silently drop or mis-home it.
- **New module, no wiring yet.** `agentic_v2/scoring/evalkit_bridge.py` and
  `tests/test_evalkit_bridge.py` ship in this slice; no existing ARP code
  path changes behavior. The bridge is exercised only by its own tests until
  Slice C.
- **Score parity is exact, not approximate, for the ported aggregation.**
  `evalkit_bridge.score_criteria` reproduces `agentic_v2_eval.scorer.Scorer.score(...)
  .weighted_score` bit-for-bit (verified against the legacy `Scorer` across
  every ARP rubric YAML that defines `criteria`, including missing-criterion,
  zero-weight-criterion, and out-of-range-value edge cases). This required
  computing the weighted mean directly from the converted `Rubric`'s
  criteria rather than driving evalkit's `CompositeGrader`, because
  `CompositeGrader`'s aggregation excludes a missing/non-definitive
  criterion's weight from *both* the numerator and denominator, while legacy
  `Scorer` fixes the denominator over *all* criteria weights up front and
  excludes a missing criterion from the numerator only — the two are not
  interchangeable for that case. See `evalkit_bridge.score_criteria`'s
  docstring for the full derivation.
- **Rubric shape is lossy in one direction.** ARP's rubric YAML carries
  fields evalkit's `Rubric`/`RubricCriterion` has no slot for: per-level
  rubric text (`levels: {5: "...", ..., 0: "..."}`, documentation only —
  `Scorer` never reads it), rubric-level `thresholds` (`pass`/`excellent`/
  `warning` — a caller concern, not a per-criterion concept), and
  `metadata`. None of these affect `score_criteria`'s numeric output;
  `rubric_from_yaml_dict`'s docstring documents each dropped field and why.

## Alternatives considered

- **Single-PR cutover (dependency + bridge + step_scoring rewire + delete
  agentic-v2-eval all at once)** — rejected: too large to review safely, and
  couples "add an optional dependency" with "delete a package `models/llm.py`
  still imports from," which would break the build mid-PR. The ADR-032
  scoring-package extraction and ADR-023 EK migration both took a staged
  approach for the same reason; this repo's own history favors slices over
  big-bang migrations.
- **Wire `step_scoring.py` directly to evalkit in this slice (skip the
  bridge)** — rejected: `step_scoring.py`'s `Scorer(rubric_data).score(scores)
  .weighted_score` call site is small and stable; rewriting it to speak
  evalkit's richer, execution-result-shaped grading API directly (rather than
  through an adapter) would spread evalkit-specific object construction
  through scoring call sites instead of concentrating it in one bridge
  module, making the eventual `agentic-v2-eval` deletion (Slice D) touch more
  files instead of fewer.
- **Drive `score_criteria` through evalkit's `CompositeGrader`/`WeightedGrader`
  instead of computing the weighted mean directly** — rejected: as detailed
  in Consequences, `CompositeGrader`'s missing-component semantics
  (exclude from numerator *and* denominator) diverge from legacy `Scorer`'s
  (exclude from numerator only) whenever a criterion is missing from the
  input scores, which would silently change scoring behavior for exactly the
  case Slice C's callers (e.g. `step_scoring.score_step`, which always scores
  every criterion in `scorer.criteria` today but need not forever) most need
  to be safe against.
- **Require evalkit unconditionally starting now, add it to CI immediately**
  — rejected: evalkit has no public remote; CI cannot install an unpublished
  local-only checkout. This would either break CI outright or force a
  path-hack that only works on the author's machine — neither is acceptable
  for a shared repo.
