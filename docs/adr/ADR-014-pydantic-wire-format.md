# ADR-014: Pydantic Discriminated Union as the Execution Event Wire Format

**Status:** Accepted
**Date:** 2026-04-21
**Implements:** commit `36a60ab feat(contracts): pydantic wire format for execution events`
**Related:** Epic 2 (Observable Execution)

---

## Context

Before Epic 2, the workflow execution event stream — emitted over WebSocket at `/ws/execution/{run_id}` and over Server-Sent Events at `/sse/execution/{run_id}` — was a set of loosely structured Python dicts serialized as JSON. Producers wrote these dicts inline at the call site; consumers (the React UI, Python test assertions, and any third-party observer) inferred the shape by reading source or by trial and error.

This produced three recurring classes of bug:

1. **Silent field drift.** A producer would add a new field to a `step_end` event and the consumer would quietly ignore it. A producer would rename a field and the consumer would quietly receive `null`. Neither case failed loudly.

2. **Inconsistent event type strings.** `"step_complete"` vs. `"stepComplete"` vs. `"step_completed"` had all appeared in git history. The UI carried conditional code to handle each.

3. **Lost field-level typing across the wire.** Python producers had the benefit of local dataclass types; by the time the event reached the browser, every field was `any`. TypeScript consumers imported a hand-crafted `UnknownEvent` interface and narrowed by string matching on `type`.

Epic 2 needed to add several new event types (`workflow_start`, `workflow_end`, `evaluation_start`, `evaluation_complete`) and extend `step_complete` with additional evaluation fields. Layering those onto a dict-shaped stream would have multiplied the drift risk.

---

## Decision

Define the full execution event stream as a **Pydantic v2 discriminated union** in `agentic-workflows-v2/agentic_v2/contracts/events.py`:

- Each event type is a distinct Pydantic model with a literal `type` field acting as the discriminator.
- The server validates every event with `model_validate` / `model_dump` before emitting it on the WebSocket or SSE channel. A producer that tries to emit a malformed event raises a validation error at emit time, not at consume time.
- The union covers `workflow_start`, `step_start`, `step_end`, `step_complete`, `step_error`, `workflow_end`, `evaluation_start`, `evaluation_complete`.
- TypeScript interfaces in `agentic-workflows-v2/ui/src/api/types.ts` **mirror the union by hand**. The React client narrows on the `type` discriminator using TypeScript's discriminated-union semantics.
- The `contracts/` directory is **additive-only**: fields are added, never removed or renamed, so that older clients continue to deserialize newer events as long as they ignore unknown fields (standard Pydantic behavior).
- A schema-drift CI gate (`test(schemas): add schema-drift CI gate for contracts/ models`, commit `02efb3f`) snapshots the canonical JSON schema for the union and fails the build on any unreviewed change. Regenerating the snapshot is explicit, via `scripts/generate_schemas.py`.

---

## Consequences

### Positive

- Producers cannot emit a malformed event; validation is at the boundary.
- Consumers that import the Pydantic models (Python tests, downstream services) get static type checking across the stream.
- The schema-drift snapshot test forces every wire-format change through an explicit review.
- New event types are trivial additions — a new model, a new literal discriminator, a new schema snapshot entry.

### Negative

- The TypeScript mirror is manual. A change to `contracts/events.py` requires a coordinated edit in `ui/src/api/types.ts` — nothing catches drift at build time today. See [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §1.3. Automating this is a Sprint B candidate.
- Additive-only is a constraint, not a freebie. Teams that want to "clean up" old fields must wait for an explicit breaking-change milestone — and file a `MIGRATIONS.md` entry.
- Pydantic validation adds a small per-event cost. Benchmarked at roughly 30–50 µs per event on a tier-3 developer machine; immaterial compared to network and LLM latency.

### Alternatives considered

- **Protobuf / FlatBuffers.** Would eliminate the TS drift by generating both sides from a single `.proto`. Rejected for v0.3 because it introduces a build step and a new runtime dependency; the schema-drift CI gate addresses the worst-case risk cheaply. Revisit if the UI surface grows substantially.
- **JSON Schema as source of truth.** Considered. Rejected because Pydantic already emits JSON Schema and we wanted the ergonomics of dataclass-style producers at the emit site.

---

## Implementation references

- Contracts union: `agentic-workflows-v2/agentic_v2/contracts/events.py`
- TS mirror: `agentic-workflows-v2/ui/src/api/types.ts`
- Schema-drift gate: `scripts/generate_schemas.py`, snapshot under `tests/`
- Emit sites: `agentic-workflows-v2/agentic_v2/server/websocket.py`, `server/sse.py`
- Landing commit: `36a60ab`

---

## Review cadence

Re-evaluate at the v0.5 planning phase, or earlier if the TS drift issue (§1.3 of Known Limitations) produces a production-affecting bug.

---

## Addendum — Sprint 1, S1-1 (2026-05-14): Drift gate extended to HTTP response shapes

The schema-drift CI gate originally covered only the execution-event discriminated union (`contracts/events.py`) and `StepResultRecord`. Sprint 1 (S1-1) extended the gate to four additional HTTP response models defined in `agentic_v2/server/models.py`:

- **`DAGResponse`** — body of `GET /api/workflows/{name}/dag`
- **`WorkflowInputSchemaResponse`** — the `inputs` block embedded in `DAGResponse`
- **`WorkflowEditorStep`** — the per-step object in `GET /api/workflows/{name}/editor`
- **`RunsSummaryResponse`** — body of `GET /api/runs/summary`

Their JSON schemas are committed under `tests/schemas/` (`dag_response.schema.json`, `workflow_input_schema.schema.json`, `workflow_editor_step.schema.json`, `runs_summary.schema.json`) and are regenerated by `scripts/generate_schemas.py`. The `wire-format-drift` CI job now covers six schemas in total.

**Breaking change introduced in S1-1:** `DAGNodeModel.depends_on` and `WorkflowEditorStep.depends_on` no longer default to `[]`. Both fields are now required in the wire schema. Callers constructing these models from raw dicts must supply `depends_on` explicitly (even as an empty list) or Pydantic raises `ValidationError`. The server-side route handler for `GET /api/workflows/{name}/dag` was updated to always pass `depends_on=list(step.depends_on)`, so the server path is safe. TypeScript generated types in `ui/src/api/*.generated.ts` were updated to require the field.
