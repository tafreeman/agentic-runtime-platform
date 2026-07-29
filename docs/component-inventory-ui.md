# UI component inventory — Evidence Ledger

**Source:** `agentic-workflows-v2/ui/src/`
**Audited:** 2026-07-28
**System:** [Evidence Ledger](ui/evidence-ledger-design-system.md)

This inventory describes the production component boundaries after the
Evidence Ledger strangler migration. A component is specialized when generic
abstraction would reduce semantic fidelity, accessibility, or performance.

## Application and layout

| Component | Responsibility |
|---|---|
| `App` | Lazy routes, Suspense, skip link, responsive shell, redirect, toaster |
| `AppErrorBoundary` | Last-resort render failure with safe recovery |
| `Sidebar` | Desktop evidence index and mobile bottom navigation |
| `ConsoleHeader` | Current section/path, health and search affordances |
| `CliStrip` | Intentionally dark command/status utility strip |
| `BTopBar` | Compact breadcrumb/action band retained as a specialized route header |

`BTopBar`, CLI text, and identifiers keep monospace because they represent
machine paths or commands. They consume canonical Evidence Ledger colors and
spacing through compatibility aliases; they do not define a separate theme.

## Routed pages

| Page | Capability boundary |
|---|---|
| `DashboardPage` | Aggregate health, recent evidence, first-run guidance |
| `RunsPage` | Bounded run ledger, filters, live tail, keyboard inspector |
| `RunDetailPage` | Permanent run evidence, DAG, I/O, evaluation, replay |
| `LivePage` | WebSocket execution, transport state, bounded event/output views |
| `WorkflowsPage` | Searchable workflow registry |
| `WorkflowDetailPage` | DAG, schema inputs, routing/runtime/evaluation launch |
| `WorkflowEditorPage` | Visual/YAML round trip, validation, diff, explicit save |
| `DatasetsPage` | Source/dataset/sample browsing and run deep link |
| `EvaluationsPage` | Scores, rubrics, judge/gate truth, replay comparison |
| `ModelFinderPage` | URL-backed Model Router workspace |
| `NotFoundPage` | Unknown-route recovery |

`SettingsPage` remains a direct-component compatibility wrapper for tests and
embedding. Production `/settings` redirects to the Providers tab; it is not a
second product surface. `PrototypeLabPage` is not imported by production.

## Model Router features

| Component | Real behavior |
|---|---|
| `ModelFinderPage` | Models, Providers, Tiers, Packs, Playground, Hardware tabs |
| `ProviderPanel` | Create/edit, env-name credential reference, toggle, probe, guarded delete |
| `TierBoard` | Reorder/reset chains, model capability metadata, dry-run explanation |
| `ModelPacksPanel` | Create/version/validate/activate/duplicate/import/export/archive/bind |
| `ChatPlaygroundPanel` | Abortable SSE chat with text/image input and text/image output |
| `ProviderProbeList` | All-provider status card grid plus searchable, collapsed live model catalog |
| finder/hardware panels | Live discovery, filters, recommendations, operator override |

## Runs and launch

| Component | Responsibility |
|---|---|
| `RunConfigForm` | Schema inputs, media, runtime, exact pack, direct model, eval/batch |
| `RunList` | Reusable bounded run rows |
| `RunDetailPanel` | Evidence tabs plus recorded routing provenance |
| `JsonViewer` | Bounded, escaped structured data |
| `DurationDisplay` | Human-readable timing |

`RunConfigForm` uses native file/select controls where native form semantics
are required. Their surfaces use the same tokens and visible focus rules as
owned inputs. This is a documented specialized-control exception, not an
independent visual foundation.

## DAG, live, evaluation, and data features

- DAG components retain React Flow for pan/zoom, nodes, edges, mini maps, and
  live status. Their list equivalents and inspectors remain semantic HTML.
- Live components reduce WebSocket events, expose transport and workflow state,
  bound history, and preserve reconnect/out-of-order behavior.
- Evaluation components render scorelines, rubric layers, gate failures,
  judge-skip truth, and comparable run evidence without fabricating confidence.
- Dataset components preserve server paging, source provenance, compatibility
  checks, and sample-to-run links.

## Shared state and evidence components

Existing `components/common/` and `components/states/` components remain
specialized composition helpers for scorelines, empty/loading/error states,
code/JSON evidence, and compact route headers. They inherit `el-*` values via
the compatibility token map. New generic interaction behavior must use an
owned primitive instead of adding another helper.

## Owned shadcn/ui primitives

The following source is committed and may be changed locally:

```text
accordion       alert-dialog    badge           button
checkbox        collapsible     command         dialog
dropdown-menu   input           popover         resizable
scroll-area     select          separator       sheet
skeleton        sonner          switch          table
tabs            textarea        tooltip
```

Evidence Ledger customizations include 2 px radii, 40 px standard controls,
warm raised input surfaces, ink text, orange focus treatment, hairline tables,
editorial dialog titles, and warm overlays. Radix supplies behavior; the repo
owns appearance and composition.

## Icons and feedback

Lucide supplies interface icons and is tree-shaken. Icons do not replace text
for primary actions and icon-only controls have accessible names. Sonner is the
single transient notification policy for mutation outcomes; persistent errors
remain in the page near their cause.

## Styling ownership

| Source | Purpose |
|---|---|
| `styles/tokens.css` | Canonical light/dark semantic values and temporary aliases |
| `styles/globals.css` | Typography, page canvas, focus, base browser behavior |
| `tailwind.config.js` | Semantic utility bridge for shadcn and application code |
| route/component CSS | Specialized graph/layout mechanics only |

New product code should use `el-*` or shadcn semantic classes. `b-*` is a
temporary strangler compatibility namespace and must not receive new visual
semantics.

## Test ownership

Component tests live in `ui/src/__tests__/`. Critical interaction coverage
includes loading/empty/error states, run keyboard flows, stream reduction,
workflow round trip, provider safeguards, tier mutation, pack lifecycle,
multimodal chat, exact pack launch, and provenance display. Cross-route browser
flows live under `ui/e2e/`.
