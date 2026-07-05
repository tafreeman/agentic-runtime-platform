# Migrations

> **Audience:** Contributors resolving build breaks after pulling `main`, and downstream consumers of this repo's packages.
> **Outcome:** After reading, you know which imports broke, what replaces them, and whether any code change is required.
> **Last verified:** 2026-07-05

This document tracks breaking changes since v0.3.0. One entry per migration, newest first. Every entry names what broke, how to detect the break, and the exact replacement path. If a migration is additive-only and safe, it does not belong here — note it in `CHANGELOG.md` instead.

---

## 1. `AGENTIC_SANITIZER_FAIL_OPEN` truthiness narrowed to exactly `"1"` (2026-05-09)

### What changed

The sanitization middleware's fail-open switch no longer accepts the broad boolean synonyms. Prior to 2026-05-09, `AGENTIC_SANITIZER_FAIL_OPEN` accepted `"true"` and `"yes"` as truthy in addition to `"1"`. The current implementation (`server/middleware/__init__.py:_fail_open_enabled()`) uses a strict equality check: **only the exact string `"1"` enables fail-open**. Any other value — including `"true"` and `"yes"` — is treated as fail-closed.

### What breaks

Deployments that set `AGENTIC_SANITIZER_FAIL_OPEN=true` or `AGENTIC_SANITIZER_FAIL_OPEN=yes` silently switch to fail-closed behavior: requests are rejected with HTTP 503 when the sanitizer is unavailable and HTTP 500 on sanitizer errors, instead of passing through unsanitized.

### Replacement

Update deployment scripts to `AGENTIC_SANITIZER_FAIL_OPEN=1` (and only for debugging — never in production). Full variable documentation: [`configuration.md`](configuration.md#agentic_sanitizer_fail_open--breaking-change).

---

## 2. `presentation/` system extracted to standalone repo (2026-04-22)

### What changed

The presentation / deck / slide builder subsystem was extracted from this monorepo into a separate repository.

- **Commit in this repo:** `764d86b refactor: extract presentation/ to standalone repo`.
- **Files removed from this repo:** 245. The deck builder, its TypeScript sources, the layout registry, and the docs have all moved. The active tree no longer carries the extracted presentation sources or generated theme artifacts.
- **New home:** separate repository; check that repository changelog for the first tracked release.

### Why

The presentation system was accreting mass unrelated to the core agentic-workflows-v2 platform: React slide layouts, theme collection scripts, deck export tooling, and a growing body of TypeScript components. Keeping it co-resident made both CI and docs confusing — contributors landing on this repo for the runtime had to page past deck concerns. The extraction is deliberate and permanent.

### What breaks

1. **Imports referencing `presentation/…`** from any tool, script, or doc in this repo will fail. There were no runtime imports from the core packages into `presentation/`, so `agentic-workflows-v2`, `agentic-v2-eval`, and `tools` are unaffected.

2. **Docs that referenced deck or theme concepts.** Any doc that linked into `presentation/`, referenced `raw-themes/`, or described a deck layout family (`verge-pop`, `engineering`, `onboarding`, `handbook`, etc.) is stale with respect to the new structure. The stale-docs audit (see [`ROADMAP.md`](ROADMAP.md)) is sweeping these; if you land before it does, delete or fix as you find them.

3. **Tokens and components previously available under `presentation/src/tokens/`** are no longer importable from here. If you need slide tokens or layouts, pull them from the new repo.

### How to detect the break

```bash
# Returns paths if any stale reference remains
# (this file documents the migration, so it is excluded from its own check)
grep -rn "presentation/" --include="*.md" --include="*.py" --include="*.ts" --include="*.tsx" \
    --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="dist" \
    --exclude="MIGRATIONS.md" .
```

A clean result is zero matches. As of 2026-04-22 the sweep is in progress; expect isolated stragglers in `docs/` until the stale-docs audit lands.

### Replacement

- **Building a deck:** use the presentation system's new home, a private standalone repository.
- **Referencing theme data from here:** do not. If a workflow genuinely needs theme data, copy it into the workflow's input payload rather than re-introducing a cross-repo dependency.
- **Referencing a layout family name in a persona or prompt:** remove the reference. No agent in this repo authors presentation content.

### Rollback posture

This extraction is not reversible without significant rework. Theme data that lived in `raw-themes/` was preserved in the private standalone repository and is not duplicated here. Do not try to re-import the folder from git history — the history remains in this repo's log, but the active tree is intentionally free of it.

---

## 3. `AgentProtocol.run` signature tightened from `Any` to `object` (2026-04-21)

### What changed

The `run` method on `AgentProtocol` (in `agentic-workflows-v2/agentic_v2/core/protocols.py`) no longer accepts or returns `Any`. Signature is now:

```python
async def run(self, input_data: object, ctx: Optional[ExecutionContext] = None) -> object:
    ...
```

- **Commit:** `19eee83` (plan), implemented across Epic 1.
- **Motivation:** Type checkers were treating agent I/O as opaque; tightening to `object` preserves permissiveness at call sites while forcing downstream consumers to narrow intentionally.

### What breaks

Code that implemented `AgentProtocol` with `-> Any` or `input_data: Any` will now emit a mypy error in strict mode. Runtime behavior is unchanged — `object` accepts every value.

### Replacement

Change the signature in your implementation:

```python
# Before
async def run(self, input_data: Any, ctx: Optional[ExecutionContext] = None) -> Any:
    ...

# After
async def run(self, input_data: object, ctx: Optional[ExecutionContext] = None) -> object:
    ...
```

If you need to type-narrow `input_data` inside your implementation, use `isinstance` or `TypedDict` casts — do not revert to `Any`.

### Out of scope

`ExecutionEngine.execute` still carries `workflow: Any` because its multi-line signature is not caught by the single-line grep gate the story used. This is explicitly deferred; see the Epic 1 plan doc.

---

## 4. Event wire format — `contracts/events.py` discriminated union (2026-04-21)

### What changed

Execution events previously were emitted as loosely structured dicts. They are now a Pydantic v2 discriminated union declared in `agentic-workflows-v2/agentic_v2/contracts/events.py`, covering:

- `workflow_start`, `step_start`, `step_end`, `step_complete`, `step_error`, `workflow_end`
- `evaluation_start`, `evaluation_complete`

Both WebSocket broadcasts (`/ws/execution/{run_id}`) and SSE streams validate emitted events against this union before sending.

- **Commit:** `36a60ab feat(contracts): pydantic wire format for execution events`.
- **Ratifying ADR:** [ADR-014](adr/ADR-014-pydantic-wire-format.md).

### What breaks

External consumers of the WebSocket or SSE stream that previously accepted loose dicts may encounter:

1. A stricter set of required fields per event type.
2. A `type` field that is now a literal discriminator, not an arbitrary string.

### Replacement

- **Python clients:** import the union and use `model_validate` / `model_dump` on messages.
- **TypeScript / JS clients:** use the mirrored interfaces in `ui/src/api/types.ts`. These are kept by hand — see [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) §1.1.
- **Evaluation-related fields:** `EvaluationCompleteEvent` now includes `passed`, `pass_threshold`, and a full `criteria` list (Epic 6 additive extension). Existing code that ignored unknown fields is fine; code that matched on a fixed shape may need updating.

---

## How this document is maintained

- Every breaking change gets an entry here in the PR that lands the break.
- Entries are newest-first; do not reorder or coalesce.
- When an entry references a replacement path, the path must be real — if the replacement is not yet written, delay the migration.
- Non-breaking additive changes belong in `CHANGELOG.md`, not here.
