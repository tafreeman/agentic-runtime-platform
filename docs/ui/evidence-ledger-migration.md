# Evidence Ledger migration record

**Status:** Complete  
**Baseline captured:** 2026-07-14  
**Authority:** [Evidence Ledger design system](evidence-ledger-design-system.md)

This record is the capability-preservation matrix and executable migration map
for the production ARP UI rewrite. It is updated as each vertical slice lands.

## Baseline

- `npm --prefix agentic-workflows-v2/ui test -- --run`: 49 files, 426 tests
  passed.
- `npm --prefix agentic-workflows-v2/ui run build`: passed; initial production
  bundle was 723.88 kB JavaScript (206.26 kB gzip) and 79.82 kB CSS (15.74 kB
  gzip). Vite reported the existing single-chunk warning.
- The live FastAPI OpenAPI document was generated from `create_app()` and
  reconciled with `ui/src/api/client.ts` and `ui/src/api/types.ts`.
- Existing uncommitted prototype files are the approved visual reference. The
  unrelated `.agentic_model_rankings.json` and `ai-firstify-assessment-report.md`
  files remain outside this migration.

## Architecture decision gate

React 19, Vite 8, React Router 7, TanStack Query 5, Tailwind 3, React Flow 12,
Vitest, and Playwright are retained. They already satisfy ARP's streaming,
canvas, caching, deep-link, testing, and Windows workflows. Replacing any of
them would add migration risk without a product benefit.

The owned component foundation is shadcn/ui using Radix primitives. The
official Vite installation supports an existing project and the shadcn Tailwind
guidance explicitly keeps existing Tailwind 3 applications supported. ARP will
therefore not combine this rewrite with an unrelated Tailwind 4 migration.
Only used primitives are committed under `ui/src/components/ui`; their tokens,
spacing, focus treatment, radii, and anatomy are customized for Evidence
Ledger. See [ADR-054](../adr/ADR-054-evidence-ledger-ui-and-model-packs.md).

Route-level lazy loading replaces the baseline single application chunk.
Server state remains in TanStack Query; local interaction state remains local
or URL-backed. React Flow remains the specialized DAG implementation and gains
Evidence Ledger styling plus a semantic list equivalent.

The implementation uses a strangler-fig migration: shared Evidence Ledger
foundations surround the working application, then each route crosses the
boundary with its capabilities and tests intact. Legacy aliases are removed
only after the final consumer migrates; there is never a second production app
or an untestable big-bang branch.

## Route and capability matrix

| Route/surface | Current behavior confirmed in code | Preserve | Refine | New contract needed | Explicitly excluded | Verification |
|---|---|---|---|---|---|---|
| `/` Overview | Real run summary, recent runs, agents/models, workflow access, filtering, partial errors, first-run guidance | All live metrics, deep links, health, shortcuts | Evidence scoreline, recent-run ledger, attention rail, freshness | None; unbacked cost/latency trends remain absent | Fake executive copy, decorative charts, KPI-card mosaic | Dashboard unit states; desktop/mobile browser journey |
| `/runs` | 50-row disclosed window, summary, status/workflow/text filters, live tail, j/k/Enter/Escape, inspector, CLI parity | Existing window truth, keyboard flow, stale retry, identifiers | Sortable warm-paper ledger, URL filters, responsive sheet inspector | Server cursor pagination and export are deferred until a bounded contract exists | Client-only pagination, fabricated columns, bulk deletion | Runs unit/keyboard tests; filter-to-detail journey |
| `/runs/:filename` | Metadata, DAG, step selection, I/O, YAML, evaluation layers, replay safety, CLI parity | Full evidence and replay guard | Evidence tabs, provenance strip, synchronized selected step, bounded viewers | Add recorded routing-pack snapshot to run provenance | Editing completed evidence; unsafe replay; invented reasoning | Run-detail unit and browser replay tests |
| `/live/:runId`, `/live/latest` | Bounded-retry WebSocket, DAG state, events, tokens, output, evaluation, latest-run gate | Transport behavior, terminal deep link, no-run state | Separate transport/workflow state, follow-live control, event filters, bounded log, responsive inspector | No cancellation contract in current backend | Fake pause/resume/cancel, unbounded events, forced selection changes | Stream/reconnect unit and Playwright tests |
| `/workflows` | Registered workflows, search, latest run, deep links, empty/error states, `/` shortcut | All discovery and navigation behavior | Ledger rows, validation/default-pack status where real, URL search | Default-pack binding is supplied by model-pack settings | Fake tags/descriptions, YAML editing on index, DAG card grid | Workflows unit tests; browser search/open |
| `/workflows/:name` | DAG, schema-driven inputs/media, runtime profile, evaluation datasets/batch, model override, history, run launch | All input types, safety limits, dataset deep link, live navigation | Inputs/Routing/Runtime/Evaluation disclosure, routing preview, pack selection | Run request accepts pack reference; pack resolution endpoint | Silent pack application, raw media persistence, unbounded fan-out, fake cost | Run-config and workflow-run tests; pack launch journey |
| `/workflows/:name/edit` | Feature gate, visual/YAML modes, dirty protection, validation/save, node/edge inspectors, catalogs, query invalidation | Round trip, explicit save, read-only state, all node fields | Evidence canvas/inspector, pack binding, problems drawer, keyboard-accessible graph alternative | Workflow pack binding uses instance-scoped pack API | Multiplayer, browser Python, IDE/file explorer, implicit repository writes | Editor unit tests; validate/save/reload browser journey |
| `/datasets` | Repository/local sources, paged samples, field/meta detail, compatibility preview, sample-to-run link | Paging, typed state handling, deep link | Three-level evidence workspace, URL selection, clearer provenance | Existing dataset contracts only; registration/refresh stays absent | Dataframe editor, silent large downloads, false cache/validity claims | Dataset unit and Playwright journey |
| `/evaluations` | Evaluated-run scorecard, distributions, workflow pass rate, rubric detail, rerun evaluation, ephemeral comparison | Scores, judge/gate truth, comparison, invalidation | Runs/Comparisons/Rubrics tabs, provenance, URL filters, inspector detail | No persisted comparison/benchmark history currently exists | Fake history, incomparable rankings, unsupported confidence, hidden judge skip | Evaluation unit and comparison browser tests |
| `/models` | Finder, hardware, live probe/catalog, playground, recommendations | Catalog, search, hardware override, probe and chat behavior | Model Router tabs: Models, Providers, Tiers, Packs, Playground, Hardware | Provider edit/probe and versioned model-pack APIs | Secrets, billing/signup, unsupported pricing/quality claims | Model Router unit tests; provider/tier/pack journeys |
| `/settings` | Provider and tier panels | All capabilities consolidated under Model Router | Redirect to `/models?tab=providers` | None | Empty compatibility page | Router unit assertion and browser redirect |
| unknown routes/states | App error boundary, not-found, page-local loading/empty/error states | Safe next action and retry | One consistent Evidence Ledger state family | None | Browser alerts/confirms | State component tests; unknown-route browser check |
| `/prototypes` | Three mock-only visual concepts outside the app shell | Design evidence in documentation | Remove from production routing after migration | None | Mock metrics in production bundle | Build route audit; source import audit |

## Contract gap classification

### Required in this rewrite

- Immutable, named, versioned model packs with validation, duplication,
  activation, workflow binding, archival, import/export, and dependency views.
- Optional run pack selection and workflow-bound/global resolution while
  preserving environment-pin precedence and direct-model override priority.
- Per-run immutable pack snapshot and resolved model/provider provenance.
- Provider edit through the existing full-replacement settings contract and a
  focused provider probe result with timestamp, latency, model count, and
  classified failure.

### Deliberately not claimed

- Cursor pagination or server export for runs.
- Run cancellation.
- Persisted evaluation comparison history.
- Dataset registration/import/refresh.
- Cost estimates, pricing enforcement, or statistically supported trends.
- Secret storage or provider account management.

These items require independent backend, authorization, retention, or data
quality decisions and are not approximated in the browser.

## Completion evidence

- Production build passed with route-level chunks; the application entry is
  254.91 kB JavaScript (78.15 kB gzip) and the main stylesheet is 77.02 kB
  (14.53 kB gzip).
- UI unit/integration coverage passed: 50 files, 436 tests.
- Playwright passed: 19 tests, with the single provider-dependent case skipped
  by design. The suite owns its no-LLM backend and uses four workers.
- Runtime coverage passed: 3,924 tests, 41 skipped, and two expected failures.
- Evaluation-package coverage passed: 273 tests. Cross-package E2E passed:
  five tests, 11 skipped by their declared environment gates.
- Documentation references and generated statistics passed, as did every
  pre-commit hook and `git diff --check`.
- Production-browser review passed at 1440x900, 1280x720, 1024x768, and
  390x844 with no console warnings or errors. The review also caught and fixed
  a short-viewport Model Router scroll boundary and a live-stream terminal
  event race by reconciling against the immutable run record.
