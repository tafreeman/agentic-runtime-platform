# UI architecture — Agentic Runtime Platform dashboard

> **Scope:** `agentic-workflows-v2/ui/`
> **Stack:** React 19 · Vite 8 · TanStack Query 5 · @xyflow/react 12 · react-router-dom 7 · Tailwind CSS 3 · TypeScript 6
> **Themes:** dark (default) · paper (warm cream) · bolt (cobalt blue)

---

## Table of contents

1. [Executive summary](#executive-summary)
2. [Technology stack](#technology-stack)
3. [Application bootstrap](#application-bootstrap)
4. [Routing architecture](#routing-architecture)
5. [Layout system](#layout-system)
6. [Design system](#design-system)
7. [Theme system](#theme-system)
8. [DAG rendering engine](#dag-rendering-engine)
9. [Real-time architecture — WebSocket](#real-time-architecture)
10. [Data layer — TanStack Query](#data-layer)
11. [Keyboard shortcuts](#keyboard-shortcuts)
12. [Accessibility](#accessibility)
13. [Feature flags](#feature-flags)
14. [Error handling](#error-handling)
15. [Build and development](#build-and-development)

---

## Executive summary

The dashboard is a single-page application that serves as the observability and control plane for the multi-agent workflow runtime. It covers six top-level domains:

| Domain | Description |
|--------|-------------|
| **Dashboard** | Aggregate run metrics, 14-day activity histogram, recent run table |
| **Workflows** | Searchable registry; per-workflow DAG viewer and run launcher |
| **Live** | Real-time execution monitor driven by a WebSocket stream |
| **Runs** | Historical run archive with status filtering and score display |
| **Datasets** | Three-pane browser for evaluation datasets and sample inspection |
| **Evaluations** | Score distribution histogram, per-workflow pass rates, rubric accordion |

The application uses a **terminal/ASCII design language** throughout: monospace fonts, bracket-styled status tokens (`[OK ]`, `[ERR]`, `[RUN]`), thin borders, and a muted colour palette. Three themes — dark, paper, and bolt — are applied by toggling the `data-theme` attribute on `<html>`.

All data fetching goes through **TanStack Query** backed by a thin REST API client. Live execution state is streamed over a **WebSocket connection** whose events are reduced by the `useWorkflowStream` hook. The DAG canvas is rendered by **@xyflow/react** with a custom `StepNode` that reflects live execution status.

---

## Technology stack

```
agentic-workflows-v2/ui/
├── React 19.2         — UI rendering, StrictMode, concurrent features
├── react-router-dom 7 — SPA routing (BrowserRouter, declarative routes)
├── TanStack Query 5   — server state, caching, polling
├── @xyflow/react 12   — interactive DAG canvas (ReactFlow provider pattern)
├── Vite 8             — dev server (HMR), production build (Rollup)
├── Tailwind CSS 3     — utility-first styling, CSS variable token bridge
├── TypeScript 6       — strict mode, all function signatures typed
├── Vitest 4           — unit and component tests
├── Playwright         — E2E tests
└── lucide-react ^1.22 — icon library (SVG, tree-shakeable)
```

### Notable version choices

**React 19** — Hooks-first throughout; no class components except `AppErrorBoundary` (required by React's error boundary API).

**react-router-dom v7** — Declarative `<Routes>/<Route>` only; no data router loaders are used. Navigation is `useNavigate()` plus `<Link>`.

**@xyflow/react v12** — The v12 API requires wrapping inner components in `ReactFlowProvider`. The inner component uses `useReactFlow()` to access `fitView`. See [DAG Rendering Engine](#dag-rendering-engine).

**TypeScript 6, strict mode** — The type system is the schema contract boundary. Event types are generated from the Python Pydantic contract and live in `api/events.generated.ts`. All API types live in `api/types.ts`.

---

## Application bootstrap

**File:** `agentic-workflows-v2/ui/src/main.tsx`

The component tree on startup:

```
StrictMode
  └─ QueryClientProvider (queryClient)
       └─ BrowserRouter
            └─ AppErrorBoundary
                 └─ App
```

The `QueryClient` is created once at module scope with global defaults:

| Option | Value | Rationale |
|--------|-------|-----------|
| `refetchOnWindowFocus` | `false` | Prevents flicker when switching browser tabs during a live run |
| `retry` | `1` | One automatic retry on transient failures; avoids infinite retry loops |
| `staleTime` | `10_000 ms` | 10 s cache window keeps the UI responsive without excessive network traffic |

The `AppErrorBoundary` wraps the entire tree so any unhandled render-time exception shows the ASCII `[!]` error layout rather than a blank screen.

---

## Routing architecture

**File:** `agentic-workflows-v2/ui/src/App.tsx`

All routes are defined in a flat `<Routes>` block. The outer shell is a fixed `flex h-screen overflow-hidden` container: the 192 px `Sidebar` on the left, and a `<main>` flex-1 region on the right.

```
Route                          Component
/                              DashboardPage
/workflows                     WorkflowsPage
/workflows/:name               WorkflowDetailPage
/workflows/:name/edit          WorkflowEditorPage   [feature-flagged]
/runs                          RunsPage
/runs/:filename                RunDetailPage
/live/:runId                   LivePage
/datasets                      DatasetsPage
/evaluations                   EvaluationsPage
*                              NotFoundPage
```

The `/workflows/:name/edit` route is guarded by `isWorkflowBuilderEnabled()`. When the flag is off the route is not registered at all, so a direct URL hit falls through to `NotFoundPage`.

The `<main>` element carries `id="main-content"` and `tabIndex={-1}`. The skip-link in `App.tsx` (`href="#main-content"`) is visually hidden until keyboard-focused, satisfying WCAG 2.1 SC 2.4.1.

---

## Layout system

### Sidebar (`components/layout/Sidebar.tsx`)

A 192 px fixed-width column that owns navigation and theme controls.

**Navigation links** (rendered by `NavLink` with `isActive` callback):

| Label | Route | Icon |
|-------|-------|------|
| dashboard | `/` | LayoutDashboard |
| workflows | `/workflows` | Workflow |
| live | `/live/latest` | Radio |
| runs | `/runs` | List |
| datasets | `/datasets` | Database |
| evals | `/evaluations` | Trophy |

Active links receive `border-l-2 border-b-clay bg-b-clay-soft text-b-clay`. All links have `focus:ring-1 focus:ring-b-clay/50` for keyboard navigation. The footer renders theme toggle buttons: `[dark]`, `[paper]`, `[bolt]`.

### BTopBar (`components/layout/BTopBar.tsx`)

A 36 px breadcrumb bar rendered at the top of each page. Displays `PROMPTS : ~/<path>` in monospace with a blinking cursor (`animate-b-blink`). A right-slot `children` prop receives action buttons.

### Page layout contract

Every page follows a consistent three-zone structure:

```
┌─────────────────────────────────────────────┐
│  BTopBar (36 px)                            │
├─────────────────────────────────────────────┤
│  Optional header band (workflow name, etc.) │
├─────────────────────────────────────────────┤
│  Scrollable or split content area (flex-1)  │
└─────────────────────────────────────────────┘
```

Two-panel pages (WorkflowDetail, RunDetail, LivePage, WorkflowEditor) split the content area horizontally: a main canvas region on the left and a fixed-width sidebar panel (~430–450 px) on the right.

---

## Design system

The UI implements a custom ASCII-influenced design language called **Direction B**. It lives entirely in CSS custom properties defined in `src/styles/tokens.css` and is wired into Tailwind through semantic class names prefixed with `b-`.

### BBox (`components/common/BBox.tsx`)

The primary card/panel primitive. A `rounded-[4px] border border-b-line bg-b-bg1` container with an optional titled header bar (`bg-b-bg2`) and optional right slot.

```tsx
<BBox title="recent runs" right={<Link>[view all]</Link>}>
  ...content...
</BBox>
```

The title bar uses a `▊` glyph in `text-b-green` as a visual prefix, followed by monospace uppercase text at 11 px with 0.5 px letter spacing.

### BPill (`components/common/BPill.tsx`)

An inline status badge with six tones:

| Tone | Visual | Usage |
|------|--------|-------|
| `ok` | green border/bg | success, pass |
| `err` | red border/bg | failed, fail |
| `warn` | amber border/bg | skipped, C-grade |
| `info` | blue border/bg | informational |
| `dim` | text-dim, transparent | pending, neutral |
| `clay` | clay border/bg | running, active |

Renders as `rounded-sm border px-[7px] py-[2px] font-mono text-[10px] uppercase tracking-[0.5px]`.

### BAsciiBar (`components/common/BAsciiBar.tsx`)

A fixed-width ASCII progress bar using `█` (filled) and `░` (empty) block characters. Accepts `value` (0–1), `width` (character count, default 20), and a `color` token.

Example: `████████████░░░░░░░░` — 60%.

Used in EvaluationsPage workflow pass rates, RunDetailPage evaluation score, and `EvaluationRubricAccordion` criterion rows.

### BSpark (`components/common/BSpark.tsx`)

An inline SVG sparkline. Takes an array of numeric values, normalises them to the visible height, and renders a `<polyline>` with `preserveAspectRatio="none"` so it fills its container width. Used in the four stat cards on DashboardPage.

### StatusBadge (`components/common/StatusBadge.tsx`)

A fixed-width ASCII status token used in live step lists:

| Status | Glyph | Style |
|--------|-------|-------|
| pending | `[----]` | text-dim |
| running | `[RUN]` | clay + animate-pulse |
| success | `[OK ]` | green |
| failed | `[ERR]` | red |
| skipped | `[WARN]` | amber |
| cancelled | `[----]` | text-dim |

### DurationDisplay (`components/common/DurationDisplay.tsx`)

Formats a millisecond integer: `< 1 s → "42ms"`, `< 60 s → "1.4s"`, `>= 60 s → "2m 03s"`. Returns `--` for null/undefined.

### JsonViewer (`components/common/JsonViewer.tsx`)

A collapsible tree viewer for arbitrary JSON. Features:
- Collapsible objects/arrays with chevron toggle buttons
- Long strings truncated at 200 chars with expand button
- Type-coloured values: strings green-400, numbers blue-400, booleans amber-400, nulls/undefined grey
- `maxDepth` prop (default 4) limits auto-expansion depth

---

## Theme system

**Files:** `src/hooks/useTheme.ts`, `src/styles/tokens.css`

Themes are applied by setting `document.documentElement.dataset.theme` to `"dark"`, `"paper"`, or `"bolt"`. The value is persisted to `localStorage` under key `ui_theme`.

| Theme | Background | Primary accent | Context |
|-------|-----------|----------------|---------|
| `dark` | `rgb(8 8 12)` | Clay orange `rgb(217 119 87)` | Default; low-light |
| `paper` | `rgb(250 247 238)` | Rust orange `rgb(184 74 28)` | Warm light; print-like |
| `bolt` | `rgb(255 255 255)` | Cobalt blue `rgb(47 93 255)` | Corporate / high-contrast |

All colours are defined as **RGB triplets without the `rgb()` wrapper** so they compose with Tailwind's opacity modifier:

```css
/* tokens.css */
--b-clay: 217 119 87;

/* In Tailwind */
bg-b-clay/10   →   background: rgb(217 119 87 / 0.1)
```

The `useTheme()` hook returns `[theme, setTheme]`. `applyTheme(theme)` is exported for non-React contexts (tests).

**Scrollbar theming:** `--b-scroll-thumb` defines the scrollbar color across all three themes via `scrollbar-color` CSS property (applied globally in `tokens.css`).

**Shared animations defined in tokens.css:**
- `b-dash-flow` — animated SVG stroke-dashoffset for flowing edge lines
- `b-pulse-slow` — 0.4 opacity oscillation for running indicators
- `b-blink` — 50% duty-cycle blink for the BTopBar cursor

**Contrast compliance:** `--b-text-dim` is audited against each theme's `--b-bg1`. Comments in `tokens.css` record dates and ratios: 5.03:1 (dark, audited 2026-04-22), 7.45:1 (paper, audited 2026-04-21). Both exceed WCAG AA 4.5:1.

---

## DAG rendering engine

### Component hierarchy

The DAG canvas appears on four pages: WorkflowDetailPage, WorkflowEditorPage, RunDetailPage, and LivePage.

```
WorkflowDAG (ReactFlowProvider wrapper)
  └─ WorkflowDAGInner (uses useReactFlow)
       ├─ StepNode (custom node — memo-ised)
       ├─ dagLayout.ts (pure layout function)
       ├─ Background (dot grid)
       ├─ Controls
       └─ MiniMap

BDagMini (static SVG thumbnail — no xyflow dependency)
```

### Layout algorithm (`components/dag/dagLayout.ts`)

`layoutDAG(nodes, edges)` computes positions using **Kahn's topological sort**:

1. Build in-degree map and children adjacency list from edges.
2. Enqueue zero-in-degree nodes at level 0.
3. BFS: `childLevel = max(currentLevel + 1, existingChildLevel)`.
4. Group nodes by level; centre-align each level horizontally.

Constants: `NODE_WIDTH = 240`, `NODE_HEIGHT = 120`, `H_GAP = 60`, `V_GAP = 80`.

These constants are duplicated in `BDagMini` (`NODE_W = 240`, `NODE_H = 120`) to keep thumbnail geometry consistent with the full canvas.

### WorkflowDAG component (`components/dag/WorkflowDAG.tsx`)

Props:

| Prop | Type | Purpose |
|------|------|---------|
| `dagNodes` | `DAGNode[]` | Static DAG structure from the API |
| `dagEdges` | `DAGEdge[]` | Dependency edges |
| `stepStates` | `Map<string, StepLiveState>` | Optional live or historical step status |
| `edgeCounts` | `Map<string, number>` | Edge traversal counts (label on repeated runs) |
| `kickbackEdges` | `Set<string>` | Review→rework edges rendered violet |
| `onNodeClick` | `(stepName: string) => void` | Selection callback |
| `disconnected` | `boolean` | Pauses live animations when WebSocket is disconnected |

**Optimistic running status:** When `stepStates` is provided but a node shows `"pending"` and all its dependencies are `"success"` or `"skipped"`, the `effectiveStepStates` computation promotes that node to `"running"`. This closes the visual gap between the backend starting a step and the `step_start` WebSocket event arriving.

**Auto-pan behaviour:** While a workflow runs, the camera pans to the currently running node(s) with an 800 ms smooth transition. A `userInteractedRef` tracks manual pan/zoom gestures. Two or more gestures within a 2 s window sets `userInteracted = true` and suppresses auto-pan for 5 s. On workflow completion, `fitView({ padding: 0.15, duration: 800 })` is called.

**Edge colour table:**

| Condition | Stroke colour | Animated |
|-----------|--------------|---------|
| Source success + target running | Blue `#3b82f6` | Yes |
| Source success (target not running) | Faint green `#22c55e40` | No |
| Source failed | Faint red `#ef444440` | No |
| Kickback edge (traversed) | Violet `#a855f7` | No |
| Default/pending | Gray `#374151` | No |

**MiniMap node colours:** running = blue, success = green, failed = red, skipped = amber, default = gray.

### StepNode (`components/dag/StepNode.tsx`)

A memo-ised custom xyflow node registered as type `"step"`. Four visual regions:

1. **Status + name + tier** — `[OK ]`/`[RUN]`/`[ERR]` glyph with CSS-variable colour, truncated step name, optional tier pill in `b-purple`.
2. **Token counts** — `in: N` / `out: N` or `tokens: N` when present; a `StepTimer` sub-component shows live elapsed time (`setInterval` 250 ms) while running, then final duration.
3. **Streaming bar** — an 8-cell ASCII animation (`▮▮▮▮▯▯▯▯` cycling at 150 ms) shown while `status === "running" && !disconnected`.
4. **Error line** — up to 60 px scrollable error text shown when `status === "failed"`.

### BDagMini (`components/dag/BDagMini.tsx`)

A static SVG thumbnail. Shares `layoutDAG` for positions but renders plain `<rect>` and `<line>` SVG elements. Colours use `rgb(var(--b-*))` CSS variables for full theme support. Has no xyflow dependency — suitable for places where the full canvas overhead is unnecessary (e.g., the WorkflowDetailPage right sidebar).

---

## Real-time architecture

### WebSocket connection (`api/websocket.ts`)

`connectExecutionStream(runId, onEvent, options)` opens a WebSocket to `ws[s]://<host>/ws/execution/<runId>`.

**Dev environment note:** `VITE_API_PROXY_TARGET` is read to build a direct WebSocket URL to the backend, bypassing the Vite proxy. Vite's HTTP proxy drops WebSocket upgrade headers, so direct connection is required in development.

**Reconnection:** Exponential backoff with configurable parameters (defaults: `maxRetries = 5`, `retryDelayMs = 1000`). Retry sequence: 1 s, 2 s, 4 s, 8 s, 16 s (31 s total). Malformed JSON frames are logged (first 200 chars) and dropped; the stream continues.

### useWorkflowStream hook (`hooks/useWorkflowStream.ts`)

The primary consumer of the WebSocket stream for live execution. Returns `WorkflowStreamState`:

```
WorkflowStreamState
  stepStates:      Map<string, StepState>
  events:          ExecutionEvent[]
  workflowStatus:  "connecting" | "running" | "evaluating" | "completed" | "failed" | "error"
  evaluation:      EvaluationResult | null
  error:           string | null
```

**Event state machine:**

| Event | State change |
|-------|-------------|
| `workflow_start` | status → `"running"` |
| `step_start` | stepStates: insert `{status:"running", startTime, input}` |
| `step_end` | stepStates: update with final status, duration, model, tokens |
| `step_complete` | Same as `step_end`; merges `outputs` field alias |
| `step_error` | stepStates: force `status:"failed"` |
| `workflow_end` | status → normalised terminal (`"completed"` or `"failed"`) |
| `evaluation_start` | status → `"evaluating"` |
| `evaluation_complete` | evaluation → populated; status → `"completed"` (unless `"failed"`) |
| `error` | error → populated; status → `"error"` |
| `keepalive` / `connection_established` | Ignored |

Terminal status normalisation: `"success"` / `"completed"` / `"ok"` → `"completed"`, `"failed"` / `"error"` → `"failed"`, anything else → `"error"`.

The hook resets all state (new `Map()`, empty events array, null evaluation) each time `runId` changes.

### useNodeConfigUpdate hook (`hooks/useNodeConfigUpdate.ts`)

A secondary WebSocket hook used by `NodeConfigOverlay`. Connects to the same execution endpoint and sends `{type: "node_config_update", step_name, config}` messages to override LLM parameters for a running step. Parameters supported: `model`, `system_prompt`, `temperature`, `max_tokens`, `top_p`, `tool_names`. Reconnects with a 3 s fixed delay on close.

### Event type contract

WebSocket event types are **auto-generated** from the Python Pydantic contract:

- **Source model:** `agentic_v2/contracts/events.py`
- **JSON Schema:** `agentic-workflows-v2/tests/schemas/events.schema.json`
- **Generated TS:** `agentic-workflows-v2/ui/src/api/events.generated.ts`
- **Regenerate:** `npm run generate:types`

A CI job (`wire-format-drift`) blocks any PR that modifies the Python contract without regenerating the TypeScript mirror. Hand-written client-only events (`keepalive`, `connection_established`, transport-level `error`) are defined in `api/types.ts` as `ChannelEvent` and excluded from generation.

---

## Data layer

### REST API client (`api/client.ts`)

A minimal typed wrapper around `fetch`. Base URL is `/api`; the Vite dev proxy forwards to port 8010.

Non-2xx responses throw `Error("API {status}: {text}")` which TanStack Query surfaces through `isError` / `error`.

Full endpoint table — see [API Integration doc](./ui/api-integration.md).

### TanStack Query hooks

| Hook | File | Poll? | Notes |
|------|------|-------|-------|
| `useWorkflows` | `useWorkflows.ts` | No | Query key `["workflows"]` |
| `useWorkflowDAG` | `useWorkflows.ts` | No | Disabled when `name` is undefined |
| `useWorkflowEditor` | `useWorkflows.ts` | No | Disabled when `name` is undefined or `enabled=false` |
| `useEvaluationDatasets` | `useWorkflows.ts` | No | — |
| `useRuns` | `useRuns.ts` | **5 s** | `refetchIntervalInBackground: false` |
| `useRunDetail` | `useRuns.ts` | No | Disabled when `filename` is undefined |
| `useRunsSummary` | `useRuns.ts` | No | — |
| `useRunEvaluationDetail` | `useRuns.ts` | No | Lazy; disabled when `filename` is undefined |
| `useDatasetSamples` | `useDatasets.ts` | No | Disabled when source or ID is null |
| `useDatasetSampleDetail` | `useDatasets.ts` | No | Disabled when any param is null |

`useRuns` is the only polling hook. All others rely on the global 10 s stale time for passive freshness.

---

## Keyboard shortcuts

**File:** `src/hooks/useHotkeys.ts`

Global bindings are registered via `useHotkeys(handlers: HotkeyMap)` on `window`. The hook cleans up on unmount. Modifier-key combos (Ctrl, Alt, Meta) are ignored.

| Key | Action | Input guard? |
|-----|--------|-------------|
| `n` | Trigger "new" action | Yes — suppressed when input focused |
| `f` or `/` | Focus filter input | Yes — suppressed when input focused |
| `j` | Move selection down | Yes |
| `k` | Move selection up | Yes |
| `Escape` | Dismiss/clear | No — always fires |

The `isInputFocused()` guard checks `activeElement.tagName` (`input`, `textarea`, `select`) and `isContentEditable`.

Page-level hotkey bindings:
- **DashboardPage:** `filter` focuses the run filter input; `escape` clears and blurs it
- **WorkflowsPage:** `/` key bound inline with `window.addEventListener` to focus the workflow search input

---

## Accessibility

**Skip link:** `<a href="#main-content">` is `.sr-only` until keyboard-focused via `Tab`. Uses `focus:not-sr-only` with Tailwind to surface a visible `focus:bg-b-bg1 focus:text-b-clay` chip.

**Main landmark:** `<main id="main-content" tabIndex={-1}>` is the skip-link target. `tabIndex={-1}` allows programmatic focus without entering the natural tab order.

**ARIA on SVGs:** `BDagMini` applies `role="img"` and `aria-label="Workflow DAG thumbnail"` to its root `<svg>`. The empty-state SVG uses `aria-label="Empty workflow"`.

**Form labels:** All inputs in `RunConfigForm` use `<label htmlFor>` associations. Controls without visible labels (dataset selects) use `aria-label` attributes.

**Focus rings:** Consistent `focus:ring-1 focus:ring-b-clay/50 focus:outline-none` on all interactive elements (nav links, buttons, form controls, DAG nodes).

**StepLogPanel:** The collapse toggle uses `aria-expanded={expanded}` and `aria-controls={panelId}` (WCAG 4.1.2 Name, Role, Value).

**Contrast:** `--b-text-dim` against `--b-bg1`: 5.03:1 dark, 7.45:1 paper — both exceed WCAG AA 4.5:1.

---

## Feature flags

**File:** `src/config/featureFlags.ts`

Feature flags are injected at build time as Vite `define` globals (`__AGENTIC_*__`).

```typescript
export function isWorkflowBuilderEnabled(): boolean {
  return parseBooleanFlag(__AGENTIC_ENABLE_WORKFLOW_BUILDER__);
}
```

`parseBooleanFlag` accepts `"1"`, `"true"`, `"yes"`, `"on"` (case-insensitive). Set via environment variable: `AGENTIC_ENABLE_WORKFLOW_BUILDER=1 npm run dev`.

| Flag constant | Guard location | Effect when disabled |
|---------------|----------------|---------------------|
| `AGENTIC_ENABLE_WORKFLOW_BUILDER` | `App.tsx`, `WorkflowDetailPage.tsx` | Route not registered; edit button hidden |

---

## Error handling

### AppErrorBoundary (`components/states/AppErrorBoundary.tsx`)

A class component wrapping the entire tree. `getDerivedStateFromError` captures the message; renders `ErrorBanner` centred on `bg-b-bg0`.

### EmptyState (`components/states/EmptyState.tsx`)

Terminal-style empty state with Unicode box-drawing art and `$ no <entity> yet`. `EmptyStateWithHome` is a convenience wrapper with a `[→ dashboard]` link.

### Inline Error Patterns

| Pattern | Example location |
|---------|----------------|
| Red border strip at page bottom | WorkflowDetailPage mutation error |
| Red border strip at page top | LivePage WebSocket error |
| Conditional render with monospace text | DatasetsPage API error |
| Centered `$ failed to load dag` text | WorkflowDetailPage DAG loading error |

---

## Build and development

### Dev server

```bash
# Backend (from agentic-workflows-v2/)
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010

# Frontend (from agentic-workflows-v2/ui/)
npm run dev   # Vite dev server on :5173
```

Vite proxies `/api` → `http://localhost:8010/api`. WebSocket connections bypass the proxy by using `VITE_API_PROXY_TARGET` directly.

### Production build

```bash
npm run build   # TypeScript typecheck + Vite/Rollup bundle
```

> **Rollup `.ts` resolution caveat:** Vite dev auto-resolves `.js` imports to `.ts` files. Rollup (production) does not. Any file renamed `.js` → `.ts` requires all import paths to be updated.

### Type generation

```bash
npm run generate:types   # Regenerate events.generated.ts from JSON Schema
```

### Testing

```bash
npm run test         # Vitest unit + component tests
npm run test:e2e     # Playwright E2E
```

