# ADR-054: Evidence Ledger UI and versioned model packs

| Field | Value |
|---|---|
| **ID** | ADR-052 |
| **Status** | Accepted |
| **Date** | 2026-07-14 |
| **System** | React UI, server settings API, LangChain routing integration |
| **Extends** | ADR-002, ADR-012, ADR-014, ADR-043, ADR-050 |

## Context

ARP's production UI uses a terminal/Carbon visual system and direct HTML
controls across large page components. Provider endpoints and tier reranks are
already persisted in an instance-scoped JSON settings document. A run can set
one direct model override, but reusable routing intent has no stable identity,
version, workflow binding, or historical provenance.

The Evidence Ledger rewrite requires one light-first operational design system
and reusable model packs that remain meaningful after routing settings change.
It must preserve WebSocket execution, DAG authoring, type drift gates, deep
links, and environment-controlled routing precedence.

## Decision

1. Retain React, Vite, React Router, TanStack Query, Tailwind, React Flow,
   Vitest, and Playwright. Add shadcn/ui's owned Radix-based component source
   for shared interaction primitives and restyle it exclusively through
   Evidence Ledger semantic tokens. Tailwind 3 remains during this migration.
2. Make the warm-paper Evidence Ledger theme the default. A secondary theme is
   allowed only after the light system passes contrast and responsive review.
   Existing `b-*` token names may remain temporarily as documented aliases
   while old consumers migrate; their values resolve from canonical `el-*`
   tokens.
3. Lazy-load page routes. Heavy DAG/editor views remain specialized React Flow
   components with a semantic list alternative rather than being forced into a
   generic shadcn abstraction.
   The migration follows a strangler-fig pattern: the Evidence Ledger shell,
   tokens, and owned primitives wrap the existing application first; routes
   migrate as independently verified slices; compatibility aliases disappear
   only after their last consumer and regression tests have moved.
4. Store model packs in the existing instance-scoped UI settings document as
   immutable version records. Updating a pack appends a version; it never
   changes the meaning of a recorded run. Store global activation and workflow
   bindings as explicit `{id, version}` references.
5. Resolve routing in this order:
   - node/direct per-run model override;
   - deployment/environment model pin (unchanged ADR-043 authority);
   - explicitly selected run pack;
   - workflow-bound pack;
   - globally active pack;
   - existing UI tier override, probed default, and registry fallback.
6. Apply pack chains through execution-context-local routing state. Never
   mutate process-global tier state for one run, because concurrent runs may
   select different packs.
7. Persist the selected pack ID/version, source, immutable policy snapshot,
   requested chains, and resolved step model/provider data in the run record.
   Run detail reads recorded provenance rather than the current pack.
8. Provider credentials remain deployment-owned. The API and UI accept only
   environment-variable names. Provider probes return classified operational
   metadata and never echo secret values.

## Consequences

### Positive

- Routing intent becomes reusable, testable, shareable, and historically
  trustworthy.
- Concurrent runs can use different packs without cross-run state leakage.
- Existing environment pins and direct overrides keep their documented safety
  precedence.
- Route code splitting removes the baseline single-bundle architecture.
- Owned primitives provide consistent keyboard, focus, sheet/dialog, and
  notification behavior without shipping a generic component-demo style.

### Negative

- The settings document schema grows and requires additive migration defaults.
- Pack history is instance-scoped; multi-instance synchronization remains a
  separate deployment-store decision.
- Existing specialized controls migrate incrementally and require temporary
  compatibility token aliases.

## Rejected alternatives

- **Mutable named presets:** rejected because editing one would silently change
  historical run meaning.
- **Client-only packs:** rejected because run execution and provenance must be
  server-authoritative.
- **Process-global tier mutation per run:** rejected because concurrent runs
  would interfere.
- **Replace React Flow or TanStack Query:** rejected; neither replacement
  improves a required capability enough to justify migration risk.
- **Upgrade Tailwind during the rewrite:** rejected as unrelated risk. Current
  shadcn guidance continues to support existing Tailwind 3 applications.

## Verification

- Pydantic validation and settings persistence tests for every pack operation.
- Route tests for CRUD/versioning, validation, activation, workflow binding,
  dependency disclosure, archive, import/export, and provider probe outcomes.
- Concurrent execution-context tests proving pack isolation and precedence.
- Run-route tests proving recorded pack snapshot and resolved provenance.
- UI unit and Playwright journeys for provider, tier, pack, workflow launch,
  run provenance, keyboard, focus, and mobile behavior.
