# ADR-034: Path-First File I/O Contracts for Multi-Step Workflows

**Status:** Proposed
**Date:** 2026-05-24
**Related:** ADR-014 (wire-format contract discipline)

---

## Context

Several runtime workflows chain multiple LLM/tool-driven steps where one step generates code artifacts and downstream steps (tests/review/assembly) consume them. In practice, handoffs can drift when only semantic keys are exchanged (for example, `api_code` vs `backend_code`) and no canonical file path contract exists.

Current pain points:

- Output key drift can break downstream step inputs even when content exists.
- Downstream tool usage (`read`, `search`, `test`, `assemble`) is less deterministic without an explicit artifact location.
- Retry/rework loops can accidentally overwrite or ambiguously reference artifacts.
- Run observability is harder when artifacts are not tied to a stable run-scoped path.

The platform already has capable expression resolution (`coalesce(...)`) and structured outputs, but it needs a consistent file artifact contract at workflow boundaries.

---

## Decision

Adopt a **path-first I/O contract** for file-bearing workflow steps.

1. For every file-producing output, define an explicit `*_path` field (for example `backend_code_path`, `frontend_code_path`, `migrations_path`, `integration_tests_path`).
2. Keep content fields (for example `backend_code`) as optional compatibility payloads, but treat `*_path` as authoritative for downstream file/tool operations.
3. Use run-scoped artifact layout rooted at:
   - `artifacts/{workflow_name}/{run_id}/backend/`
   - `artifacts/{workflow_name}/{run_id}/frontend/`
   - `artifacts/{workflow_name}/{run_id}/migrations/`
   - `artifacts/{workflow_name}/{run_id}/tests/`
4. Each workflow step consuming generated files should prefer path inputs first, then optional content fallback only where necessary.
5. For migration safety, use bounded compatibility expressions (`coalesce(old_key, new_key)`) during transition windows, then remove aliases when all producers/consumers align.
6. Apply this pattern to `fullstack_generation` first, then roll out to other code-producing workflows.

---

## Contract Shape (Authoring Standard)

For file-bearing artifacts, steps should expose both:

- `artifact_path`: canonical file location for downstream steps/tools
- `artifact_content` (optional): inline payload for non-file-aware consumers

Example canonical keys:

- `backend_code_path`
- `frontend_code_path`
- `migrations_path`
- `integration_tests_path`
- `review_report_path` (when persisted as file)

The `*_path` keys are the required interoperability surface for multi-step workflows.

---

## Consequences

### Positive

- Deterministic step handoffs for file operations.
- Reduced breakage from output-key naming drift.
- Better retry/idempotency behavior with run-scoped locations.
- Improved debugging and auditability (artifact-to-run traceability).

### Negative

- Slightly larger workflow schemas (extra path fields).
- Temporary dual-key complexity during migration (`coalesce` aliases).
- Requires discipline to keep path contracts consistent across workflows.

---

## Alternatives Considered

| Alternative | Disposition |
| --- | --- |
| Content-only contracts (`*_code` only, no file path fields) | Rejected — brittle for tool-driven downstream steps and harder to audit. |
| Auto-discovery by scanning artifact directories | Rejected — ambiguous and non-deterministic under retries/concurrency. |
| Step-local ad hoc naming without run scope | Rejected — collision risk and weak traceability. |

---

## Rollout Plan

1. **Phase 1 (pilot):** Apply path-first contract to `fullstack_generation`.
2. **Phase 2:** Validate with targeted workflow tests + sample runs.
3. **Phase 3:** Extend pattern to other file-producing workflows.
4. **Phase 4:** Remove temporary compatibility aliases once all consumers are aligned.

---

## Implementation references

- Workflow definition pilot target: `agentic-workflows-v2/agentic_v2/workflows/definitions/fullstack_generation.yaml`
- Expression/evaluation support: `agentic-workflows-v2/agentic_v2/engine/expressions.py`
- Step mapping and context handoff: `agentic-workflows-v2/agentic_v2/engine/step.py`

---

## Review Cadence

Re-evaluate after pilot rollout on `fullstack_generation` and at completion of cross-workflow migration.
