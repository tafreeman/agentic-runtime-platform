# UI architecture — Evidence Ledger

> **Scope:** `agentic-workflows-v2/ui/`
> **Current:** 2026-07-28
> **Decision:** [ADR-054](adr/ADR-054-evidence-ledger-ui-and-model-packs.md)

The dashboard is the evidence and control surface for workflow execution. It
uses a light-first editorial system: warm paper, ink typography, hairline
structure, restrained orange emphasis, and semantic green/red states. The
former terminal vocabulary remains only where it communicates genuine CLI,
log, identifier, or machine-output semantics.

## Stack and boundaries

| Concern | Implementation | Boundary |
|---|---|---|
| Application | React 19 + TypeScript 6 | Components never execute runtime work directly |
| Build | Vite 8 + route-level dynamic imports | Every page is an independent production chunk |
| Navigation | React Router 7 | Shareable view state uses paths/query parameters |
| Server state | TanStack Query 5 | No duplicate application-wide server cache |
| UI primitives | Owned shadcn/ui source + Radix | Customized to Evidence Ledger, not a stock theme |
| Workflow graph | React Flow 12 | Specialized canvas with semantic list equivalents |
| Styling | Tailwind 3 + semantic CSS variables | Canonical `el-*` tokens; temporary `b-*` aliases |
| Live execution | WebSocket reducer | Bounded retry/history and terminal-state handoff |
| Playground | Fetch streaming over SSE | Abortable text and image input/output |
| Verification | Vitest + Playwright | Contract tests live with the Python API |

React Flow is intentionally specialized: spatial DAG interaction cannot be
replaced by a generic card or table without losing capability. Existing raw
workflow-schema controls and virtualized/log views also remain specialized
where native browser semantics or performance are stronger. Shared buttons,
inputs, text areas, tabs, tables, menus, dialogs, sheets, switches, alerts,
tooltips, skeletons, scroll areas, and notifications use owned primitives in
`src/components/ui/`.

## Bootstrap and shell

`main.tsx` creates one query client and renders:

```text
StrictMode
└── QueryClientProvider
    └── BrowserRouter
        └── AppErrorBoundary
            └── App
                ├── skip link
                ├── Sidebar / mobile bottom navigation
                ├── ConsoleHeader
                ├── lazy route boundary
                ├── CLI status strip
                └── Toaster
```

The desktop shell has a 216 px evidence index. Below the `md` breakpoint it
becomes a five-item bottom navigation and reserves room above the CLI strip.
The main landmark is focusable and every routed page has a Suspense fallback.
Warm paper is the default theme; warm charcoal remains an optional operator
preference.

## Routing

All page modules are loaded with `React.lazy` in `App.tsx`.

| Route | Product area |
|---|---|
| `/` | Overview |
| `/runs`, `/runs/:filename` | Run ledger and permanent evidence |
| `/live/:runId`, `/live/latest` | Live execution |
| `/workflows`, `/workflows/:name` | Workflow registry and launch |
| `/workflows/:name/edit` | Feature-gated visual/YAML editor |
| `/datasets` | Dataset/sample evidence |
| `/evaluations` | Evaluated runs, rubric layers, comparison |
| `/models?tab=...` | Model Router: models, providers, tiers, packs, playground, hardware |
| `/settings` | Compatibility redirect to `/models?tab=providers` |

The former `/prototypes` production route was removed. Prototype source files
may exist as untracked design evidence, but no production module imports them.

## Design system

`src/styles/tokens.css` is the canonical semantic layer. Representative light
values are paper `#F2EFE8`, surface `#F8F5EF`, raised `#FFFDFA`, ink `#1B1B18`,
and accent `#EF5A36`. Status is never encoded by color alone. Georgia supplies
editorial display headings; Geist supplies interface text; monospace is
reserved for IDs, versions, commands, JSON/YAML, and telemetry.

The migration follows a strangler-fig pattern. Canonical `el-*` values already
surround every production route. The old `b-*` names resolve to those values
while route-specific controls move onto owned primitives. This compatibility
layer prevents two apps or a capability-losing big-bang rewrite and can be
removed only after its final consumer is migrated.

See [the design-system specification](ui/evidence-ledger-design-system.md) and
[migration record](ui/evidence-ledger-migration.md).

## Data and mutation model

- Queries and invalidation use TanStack Query keys scoped to the resource.
- Transient form, selection, and stream state stays local.
- Shareable tab/filter/selection state is URL-backed where implemented.
- Mutations display success/error notifications and invalidate the narrowest
  affected keys.
- Lists and event streams retain existing pagination, disclosure, or bounded
  history; the UI does not fabricate client pagination over incomplete data.
- Provider credentials are never accepted as values. Only environment-variable
  names cross the wire.

## Model Router and execution provenance

The Model Router consolidates the previous finder and settings surfaces. It
supports provider creation/editing, safe enable/disable, classified probes,
tier chains with dry-run routing, immutable model packs, model discovery,
hardware fit, and the chat playground.

Model packs are exact `{id, version}` references. The API resolves them in this
order after higher-authority direct/environment pins: run selection, workflow
binding, global activation, then existing settings/defaults. Resolution is held
in a `ContextVar`, so concurrent runs cannot mutate each other's routing.
Completed run records retain the source, immutable pack snapshot, requested
override, and every resolved step model/provider.

## Multimodal playground

`POST /api/chat` accepts either legacy string content or ordered text/image
parts. Images must be bounded PNG, JPEG, WebP, or GIF data URLs; SVG and remote
input URLs are rejected. The UI supports up to four local previews and five
MiB per image. Output uses a typed `media` SSE event and renders only validated
raster data/HTTPS URLs. Streaming remains abortable, model content is rendered
as text, and error bodies never expose provider credentials.

## Type and contract discipline

Pydantic owns wire contracts. `scripts/generate_schemas.py` writes checked-in
JSON snapshots and the UI generator writes TypeScript contract files. Chat
message parts and `ChatMediaEvent` participate in the ADR-014 drift gate.
Hand-authored API view types may narrow generated schemas when the generator's
tuple expansion is less useful, but drift tests still prove the wire shape.

## Accessibility and performance

- A skip link targets the focusable main landmark.
- Owned Radix primitives provide dialog/sheet focus containment and escape
  behavior.
- Focus rings use a visible orange semantic token.
- Forms retain native labels, required state, keyboard operation, and live
  mutation/stream statuses.
- The DAG exposes an equivalent list/table path for non-spatial use.
- Routes are lazy chunks; graph/editor code is not in the entry bundle.
- Live event lists, run windows, samples, and JSON views keep their existing
  bounds rather than growing without limit.

## Development and verification

```powershell
npm --prefix agentic-workflows-v2/ui test -- --run
npm --prefix agentic-workflows-v2/ui run build
npm --prefix agentic-workflows-v2/ui run test:e2e
.venv\Scripts\python.exe -m pytest agentic-workflows-v2/tests -q
```

The visual acceptance viewports are 1440×900, 1280×720, 1024×768, and
390×844. Browser evidence and gate results are recorded in the migration
record.
