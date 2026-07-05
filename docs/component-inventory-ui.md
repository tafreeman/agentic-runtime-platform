# UI component inventory: React dashboard

**Source root:** `agentic-workflows-v2/ui/src/`
**Component count:** 40+ (pages, layout, common primitives, DAG, runs, live, evaluations, datasets, states)
**Last audited:** 2026-07-05

This inventory maps the React dashboard that ships with the Agentic Runtime Platform UI, grouped by subsystem. It documents the primary components rather than every file — some smaller state, error, and dashboard helpers (for example `ConsoleStatus`, `ErrorBanner`, `InlineError`, `NotFoundPage`, `RunSummaryCards`, and `GettingStartedCard`) are not catalogued below. For each entry the record includes: source file, purpose, all props with types and whether they are required, internal sub-components, and which application pages consume the component.

---

## Table of contents

1. [Layout components](#layout-components)
2. [Common primitive components](#common-primitive-components)
3. [DAG visualization components](#dag-visualization-components)
4. [Run components](#run-components)
5. [Live execution components](#live-execution-components)
6. [Evaluation components](#evaluation-components)
7. [Dataset components](#dataset-components)
8. [State / error components](#state--error-components)
9. [Page components](#page-components)
10. [Component dependency matrix](#component-dependency-matrix)

---

## Layout components

### Sidebar

| Field | Value |
|---|---|
| **File** | `components/layout/Sidebar.tsx` |
| **Purpose** | 192 px fixed-width left navigation column. Renders 6 `NavLink` elements for all top-level routes. Displays the current theme toggle row at the bottom. Calls `useTheme()` to read and mutate the active theme. |
| **Props** | None |
| **Sub-components** | None (NavLink list is inline) |
| **Used by** | `App.tsx` — always rendered, never conditionally hidden |

Navigation links rendered:

| Label | Target |
|---|---|
| dashboard | `/` |
| workflows | `/workflows` |
| datasets | `/datasets` |
| evaluations | `/evaluations` |
| runs | `/runs` |
| live | `/live` |

Theme toggle buttons emit `applyTheme('dark' | 'paper' | 'bolt')`.

---

### BTopBar

| Field | Value |
|---|---|
| **File** | `components/layout/BTopBar.tsx` |
| **Purpose** | 36 px top breadcrumb bar rendered inside each page. Displays `PROMPTS : ~/<path>` in monospace with a blinking cursor. Accepts right-side slot children (back buttons, action buttons). |

| Prop | Type | Required | Description |
|---|---|---|---|
| `path` | `string` | yes | Breadcrumb path segment appended after `PROMPTS : ~/` |
| `children` | `ReactNode` | no | Rendered in the right gutter of the bar |

**Used by:** `WorkflowDetailPage`, `WorkflowEditorPage`, `RunDetailPage`, `LivePage`, `RunsPage`, `WorkflowsPage`, `DashboardPage`, `DatasetsPage`, `EvaluationsPage`

---

## Common primitive components

### BBox

| Field | Value |
|---|---|
| **File** | `components/common/BBox.tsx` |
| **Purpose** | Card primitive with an optional title bar. The title is prefixed with `▊` (block character). Accepts an optional right-slot for inline actions placed in the title bar. All content sections are passed as `children`. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `title` | `string` | no | Title text shown in the header band; if omitted, no header is rendered |
| `right` | `ReactNode` | no | Content placed in the right side of the title band |
| `children` | `ReactNode` | yes | Card body content |
| `className` | `string` | no | Additional Tailwind classes applied to the outer wrapper |

**Used by:** `DashboardPage`, `WorkflowDetailPage`, `RunDetailPage`, `LivePage`, `EvaluationsPage`, `WorkflowEditorPage`

---

### BPill

| Field | Value |
|---|---|
| **File** | `components/common/BPill.tsx` |
| **Purpose** | Compact inline status badge with six semantic tones. Renders a tinted rounded tag. `BPillTone` is exported as a named type for consumer re-use. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `tone` | `BPillTone` | yes | One of `ok`, `err`, `warn`, `info`, `dim`, `clay` |
| `children` | `ReactNode` | yes | Badge label text |
| `className` | `string` | no | Additional Tailwind classes |

**Tone to colour mapping:**

| Tone | Semantic meaning | CSS color |
|---|---|---|
| `ok` | success / passing | `--b-green` |
| `err` | failure / error | `--b-red` |
| `warn` | warning / partial | `--b-amber` |
| `info` | informational | `--b-blue` |
| `dim` | neutral / inactive | `--b-text-dim` |
| `clay` | in-progress / running | `--b-clay` |

**Used by:** `RunsPage`, `RunDetailPage`, `WorkflowsPage`, `EvaluationsPage`, `EvaluationRubricAccordion`, `RunList`, `RunDetail`, `LivePage`, `DashboardPage`

---

### BAsciiBar

| Field | Value |
|---|---|
| **File** | `components/common/BAsciiBar.tsx` |
| **Purpose** | Renders a pure-ASCII horizontal progress bar using `█` (filled) and `░` (empty) block characters. Value is a normalised 0–1 float; the bar is divided into discrete character cells. Colour is controlled via a CSS variable name. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `value` | `number` | yes | Progress from 0.0 to 1.0 |
| `width` | `number` | no | Total character width of the bar (default `20`) |
| `color` | `string` | no | CSS color name from the design token set, e.g. `'b-green'`, `'b-amber'`, `'b-red'` (default `'b-green'`) |

**Used by:** `RunDetailPage` (evaluation score bar), `EvaluationsPage` (workflow pass-rate bars), `EvaluationRubricAccordion` (criterion bars)

---

### BSpark

| Field | Value |
|---|---|
| **File** | `components/common/BSpark.tsx` |
| **Purpose** | Inline SVG sparkline chart. Renders a polyline path from a numeric series. Uses `preserveAspectRatio="none"` to fill all available space. Provides no axes, tooltips, or interactions — purely decorative. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `data` | `number[]` | yes | Series of values to plot |
| `width` | `number` | no | SVG width in pixels (default `64`) |
| `height` | `number` | no | SVG height in pixels (default `20`) |
| `color` | `string` | no | Stroke colour (default `currentColor`) |
| `className` | `string` | no | Additional classes |

**Used by:** `DashboardPage` (14-day activity sparklines per workflow)

---

### StatusBadge

| Field | Value |
|---|---|
| **File** | `components/common/StatusBadge.tsx` |
| **Purpose** | Fixed-width ASCII token badge for execution status. Renders one of five tokens: `[OK ]`, `[ERR]`, `[RUN]`, `[WARN]`, `[----]`. Monospace font guarantees column alignment in run tables. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `status` | `StepStatus \| string` | yes | Execution status string |
| `className` | `string` | no | Additional Tailwind classes |

**Status to token mapping:**

| Status value | Token | Colour |
|---|---|---|
| `success` | `[OK ]` | `--b-green` |
| `failed` / `error` | `[ERR]` | `--b-red` |
| `running` / `in_progress` | `[RUN]` | `--b-clay` (animated) |
| `skipped` / `cancelled` | `[WARN]` | `--b-amber` |
| `pending` / anything else | `[----]` | `--b-text-dim` |

**Used by:** `RunsPage`, `RunList`, `DashboardPage` (recent runs table)

---

### DurationDisplay

| Field | Value |
|---|---|
| **File** | `components/common/DurationDisplay.tsx` |
| **Purpose** | Formats a raw millisecond integer into a human-readable duration string. Handles `null` and `undefined` by rendering nothing (`null` return). |

| Prop | Type | Required | Description |
|---|---|---|---|
| `ms` | `number \| null \| undefined` | yes | Raw duration in milliseconds |
| `className` | `string` | no | Additional Tailwind classes |

**Formatting rules:**

| Input range | Output format | Example |
|---|---|---|
| `< 1 000` | `{n}ms` | `450ms` |
| `>= 1 000` and `< 60 000` | `{n.d}s` (1 decimal) | `4.2s` |
| `>= 60 000` | `{m}m {ss}s` | `1m 23s` |

**Used by:** `RunsPage`, `RunDetailPage`, `LivePage`, `RunList`, `RunDetail`, `DashboardPage`, `EvaluationsPage`

---

### JsonViewer

| Field | Value |
|---|---|
| **File** | `components/common/JsonViewer.tsx` |
| **Purpose** | Recursive, collapsible JSON tree renderer. Type-aware colouring: strings amber, numbers blue, booleans green, null dim. Long strings (> 200 chars) are truncated with an expand control. Objects and arrays show child counts when collapsed. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `data` | `unknown` | yes | Any JSON-serializable value |
| `defaultExpanded` | `boolean` | no | Expand all nodes on mount (default `false`) |
| `maxDepth` | `number` | no | Depth at which subtrees collapse by default |

**Used by:** `RunDetail` (step I/O tabs), `LiveStepDetails` (live step I/O panels)

---

## DAG visualization components

### WorkflowDAG

| Field | Value |
|---|---|
| **File** | `components/dag/WorkflowDAG.tsx` |
| **Purpose** | Primary interactive DAG canvas. Wraps `ReactFlowProvider` and renders the workflow as a directed graph. Used in three distinct modes: static preview (no `stepStates`), completed-run overlay (step states from run file), and live streaming (step states from WebSocket). |

| Prop | Type | Required | Description |
|---|---|---|---|
| `dagNodes` | `DAGNode[]` | yes | Workflow step nodes from the DAG API |
| `dagEdges` | `DAGEdge[]` | yes | Directed dependency edges |
| `stepStates` | `Map<string, StepState>` | no | Per-step live state; omit for static preview |
| `edgeCounts` | `Map<string, number>` | no | Message counts rendered on each edge label |
| `kickbackEdges` | `Set<string>` | no | Edge keys formatted as `"source->target"` that receive violet kickback styling |
| `onNodeClick` | `(stepName: string) => void` | no | Callback fired when a node is clicked |
| `selectedStep` | `string \| null` | no | Currently selected node; highlighted with a ring |

**Internal sub-component:** `WorkflowDAGInner` (the actual ReactFlow consumer, defined in the same file)

**Optimistic status promotion:** When a step is `pending` but all its direct predecessors are `success`, the component promotes that step's display status to `running`. This creates a visual "next up" indicator during live execution before the server event arrives.

**Auto-pan:** Maintains a `userInteractionRef` counter. When the running step changes, the viewport smoothly pans to centre that node unless the user has recently interacted (2-gesture threshold within 2 s; suppressed for 5 s after last interaction).

**Edge colour logic:**

| Condition | Colour | Animation |
|---|---|---|
| In `kickbackEdges` | Violet / purple | Dashed |
| Source success + target not pending | `--b-green` | Static |
| Source running | `--b-blue` | `b-dash-flow` (animated dash) |
| Default (pending) | `--b-text-dim` | Static |

**Used by:** `WorkflowDetailPage`, `WorkflowEditorPage`, `RunDetailPage`, `LivePage`

---

### BDagMini

| Field | Value |
|---|---|
| **File** | `components/dag/BDagMini.tsx` |
| **Purpose** | Static SVG thumbnail of a workflow DAG. Does not use React Flow. Calls `layoutDAG()` to obtain node positions and renders rectangles and lines directly as SVG elements. Useful for cards and list items where a full interactive canvas is too expensive. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `dag` | `DAGResponse` | yes | Full DAG definition to render |
| `width` | `number` | no | SVG viewport width (default `200`) |
| `height` | `number` | no | SVG viewport height (default `120`) |
| `className` | `string` | no | Additional classes |

Uses CSS variable colours (`--b-text-dim`, `--b-line`) so it inherits the active theme.

**Used by:** `WorkflowsPage` (workflow list cards), `DashboardPage` (workflows quick list)

---

### StepNode

| Field | Value |
|---|---|
| **File** | `components/dag/StepNode.tsx` |
| **Purpose** | `React.memo`-wrapped custom node renderer for `@xyflow/react`. Displays four distinct content regions within each DAG node rectangle. |

The component receives its payload via the `data` field on the React Flow `Node` object (`StepNodeData` type, defined in the same file):

| `data` field | Type | Description |
|---|---|---|
| `label` | `string` | Step display name |
| `agent` | `string \| null` | Agent name and tier |
| `description` | `string` | Step description |
| `status` | `StepStatus` | Current execution status |
| `durationMs` | `number \| null` | Elapsed duration |
| `tokensUsed` | `number \| null` | Accumulated token count |
| `modelUsed` | `string \| null` | Model identifier string |
| `modelInferred` | `boolean` | Whether the model was auto-selected |
| `isSelected` | `boolean` | Whether this node is currently selected |
| `isStreaming` | `boolean` | Whether the step is actively streaming |

**Four displayed regions:**

1. Status area (top-left): `StatusBadge` icon + step name
2. Agent / tier area (top-right): agent name with tier pill
3. Streaming bar: `StreamingBar` subcomponent (ASCII animation, visible during `running`)
4. Footer: token count, model name, `StepTimer` (250 ms interval while `running`)

**Sub-components (in same file, not exported):**

- `StepTimer` — calls `setInterval(250)` while status is `running`; displays elapsed time
- `StreamingBar` — 150 ms animation cycling through 3 ASCII frames to indicate streaming activity

**Used by:** `WorkflowDAG` (registered as `nodeTypes.step`)

---

### dagLayout

| Field | Value |
|---|---|
| **File** | `components/dag/dagLayout.ts` |
| **Purpose** | Pure utility module. Converts a `DAGResponse` into positioned React Flow `Node[]` and `Edge[]` arrays using Kahn's topological sort (BFS). Zero React dependencies. Fully deterministic given the same input. |

**Exported function:** `layoutDAG(dag: DAGResponse): { nodes: Node[], edges: Edge[] }`

**Layout constants:**

| Constant | Value | Notes |
|---|---|---|
| `NODE_WIDTH` | 240 px | Applied to all nodes as `style.width` |
| `NODE_HEIGHT` | 120 px | Applied to all nodes as `style.height` |
| `H_GAP` | 60 px | Horizontal spacing between nodes in the same tier |
| `V_GAP` | 80 px | Vertical spacing between tiers |

**Algorithm notes:** Nodes are sorted into tiers by maximum-depth BFS from sources. Nodes in the same tier are centred around x=0. The function does not handle cycles; cyclic input produces undefined layout results without throwing.

**Used by:** `WorkflowDAG`, `BDagMini`

---

## Run components

### RunConfigForm

| Field | Value |
|---|---|
| **File** | `components/runs/RunConfigForm.tsx` |
| **Purpose** | The workflow run submission form. The largest component in the codebase (~270 lines). Renders schema-driven input fields from `WorkflowInputSchema[]`, an advanced toggle section for evaluation configuration, and a submit button. On submit it calls `runWorkflow()` via `useMutation` and navigates to `/live/:runId`. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `workflowName` | `string` | yes | Workflow to run |
| `inputs` | `WorkflowInputSchema[]` | yes | Schema definition for workflow input fields |
| `onRunStarted` | `(runId: string) => void` | no | Callback fired after a successful run start |

**Exported type:** `RunConfigValues` — the shape of the form submission payload.

**Advanced section (collapsed by default):** runtime selection (subprocess / docker), container image, max_attempts, max_duration_minutes, evaluation toggle, rubric selection, dataset source, dataset_id, sample_index.

**Internal sub-components (not exported):**

- `CompactInputField` — renders one schema-defined field (text, number, boolean toggle, enum select)
- Lazy `useEvaluationDatasets()` query — fired only when the evaluation toggle is enabled

**Used by:** `WorkflowDetailPage`

---

### RunDetail (RunDetailSteps)

| Field | Value |
|---|---|
| **File** | `components/runs/RunDetail.tsx` |
| **Purpose** | Scrollable, accordion step list for a completed run. The selected step's panel expands to show three tabs: Output, Input, Metadata — each rendered via `JsonViewer`. The component is exported as `RunDetailSteps`. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `steps` | `StepResult[]` | yes | Ordered array of completed step records |
| `selectedStep` | `string \| null` | yes | Name of the currently expanded step (controlled) |
| `onSelectStep` | `(name: string \| null) => void` | yes | Callback to change selection |

Each row displays: `StatusBadge`, step name, `DurationDisplay`, model name, token count.

**Used by:** `RunDetailPage`

---

### RunList

| Field | Value |
|---|---|
| **File** | `components/runs/RunList.tsx` |
| **Purpose** | Compact run list with client-side status filter tabs. Each row links to `/runs/:filename`. Renders `BPill` (status) and `DurationDisplay`. Shows skeleton rows while loading. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `runs` | `RunSummary[]` | yes | Array of run summary objects |
| `isLoading` | `boolean` | no | Shows skeleton rows when true |
| `workflowFilter` | `string` | no | When set, only rows for this workflow name are shown |

**Filter tabs:** `all` / `success` / `failed` — client-side, no network call.

**Used by:** `WorkflowDetailPage` (run history sidebar)

---

## Live execution components

### LiveStepDetails

| Field | Value |
|---|---|
| **File** | `components/live/LiveStepDetails.tsx` |
| **Purpose** | Step list panel for `LivePage`. Displays all steps in the active run with live status from the WebSocket stream. Selecting a step expands its input/output and evaluation score sub-panel rendered via `JsonViewer`. Exports `formatDuration()` as a utility. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `steps` | `StepResult[]` | yes | Live step records accumulated by `useWorkflowStream` |
| `selectedStep` | `string \| null` | yes | Currently expanded step name (controlled) |
| `onSelectStep` | `(name: string \| null) => void` | yes | Selection callback |
| `dagNodes` | `DAGNode[]` | no | DAG nodes used to establish display order |

**Exported utility:** `formatDuration(ms: number): string` — same logic as `DurationDisplay` but returns a plain string (used in `StepNode`).

**Used by:** `LivePage`

---

### StepLogPanel

| Field | Value |
|---|---|
| **File** | `components/live/StepLogPanel.tsx` |
| **Purpose** | Collapsible, append-only execution event log rendered on `LivePage`. Each event is rendered as a timestamped line with type-specific colour. `keepalive` and `connection_established` events are filtered from display. Implements ARIA expand/collapse (`aria-expanded`, `aria-controls`). |

| Prop | Type | Required | Description |
|---|---|---|---|
| `events` | `ExecutionEvent[]` | yes | Append-only event array from `useWorkflowStream` |

**Event colour mapping:**

| Event type | Colour |
|---|---|
| `workflow_start` / `workflow_end` | `--b-text` (bright) |
| `step_start` | `--b-clay` |
| `step_end` / `step_complete` | `--b-green` |
| `step_error` | `--b-red` |
| `evaluation_start` / `evaluation_complete` | `--b-blue` |
| `error` | `--b-red` (bold) |

**Used by:** `LivePage`

---

### TokenCounter

| Field | Value |
|---|---|
| **File** | `components/live/TokenCounter.tsx` |
| **Purpose** | Accumulates token usage from all `step_end`, `step_complete`, and `step_error` events during an active execution. Displays total tokens used and the count of distinct model identifiers that contributed. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `events` | `ExecutionEvent[]` | yes | Full event array from `useWorkflowStream` |

Renders as a single-line monospace stat: `tokens {n} · {m} models`.

**Used by:** `LivePage`

---

### NodeConfigOverlay

| Field | Value |
|---|---|
| **File** | `components/live/NodeConfigOverlay.tsx` |
| **Purpose** | Slide-in panel for live runtime configuration overrides on a specific step. Sends updates over a secondary WebSocket connection via `useNodeConfigUpdate`. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `runId` | `string` | yes | Active run identifier |
| `stepName` | `string` | yes | Target step for configuration override |
| `onClose` | `() => void` | yes | Close callback |

**Configurable fields:** model selection, system_prompt textarea (with copy button), temperature (0.0–2.0), max_tokens, top_p (0.0–1.0), tool_names (comma-separated).

> **Status note:** This component is implemented but not wired to any page as of the current codebase. It is dead code pending integration.

**Used by:** (not currently wired)

---

## Evaluation components

### EvaluationRubricAccordion

| Field | Value |
|---|---|
| **File** | `components/evaluations/EvaluationRubricAccordion.tsx` |
| **Purpose** | Detailed evaluation breakdown panel for a single run. Fetches the full `RunEvaluationDetail` via `useRunEvaluationDetail(filename)`. Renders: overall score + grade + pass/fail pills, criteria table with per-criterion bars, score layers block, step scores section, hard gates grid, floor violations, and gate failures. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `filename` | `string` | yes | Run filename; passed to `useRunEvaluationDetail` |

**Internal sub-components (same file):**

- `gradeToTone(grade)` — maps grade letter (`A`–`F`) to `BPillTone`

**External sub-components used:**

- `CriterionRow` (`components/evaluations/CriterionRow.tsx`)
- `StepScoreDetails` (`components/evaluations/StepScoreDetails.tsx`)

**Used by:** `RunDetailPage` (score detail box), `EvaluationsPage` (expandable accordion row)

---

### CriterionRow

| Field | Value |
|---|---|
| **File** | `components/evaluations/CriterionRow.tsx` |
| **Purpose** | Single table row representing one evaluation criterion. Displays criterion name, raw score, weight, and an inline `BAsciiBar`. Expands to show `floor` threshold and `floor_violated` indicator when a floor is defined. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `criterion` | `EvaluationCriterionDetail` | yes | Full criterion data object |

**Used by:** `EvaluationRubricAccordion`

---

### StepScoreDetails

| Field | Value |
|---|---|
| **File** | `components/evaluations/StepScoreDetails.tsx` |
| **Purpose** | Renders the per-step score breakdown section of an evaluation. Each step score row shows step name, status badge, and numeric score. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `stepScores` | `EvaluationStepScore[]` | yes | Per-step score records from `RunEvaluationDetail` |

**Used by:** `EvaluationRubricAccordion`

---

## Dataset components

### DatasetBrowser

| Field | Value |
|---|---|
| **File** | `components/datasets/DatasetBrowser.tsx` |
| **Purpose** | Three-pane dataset exploration UI. Left pane: dataset list (repository + local). Middle pane: paginated sample index grid (`SampleIndexGrid`). Right pane: full sample detail (`DatasetDetailPane`). Manages selection state across all three panes. |

| Prop | Type | Required | Description |
|---|---|---|---|
| None | — | — | Fully self-contained; queries `useEvaluationDatasets()`, `useDatasetSamples()`, `useDatasetSampleDetail()` internally |

**Sub-components (separate files under `components/datasets/`):**

| Sub-component | File | Purpose |
|---|---|---|
| `SampleIndexGrid` | `components/datasets/SampleIndexGrid.tsx` | Paginated grid of sample summary cards for the selected dataset |
| `DatasetDetailPane` | `components/datasets/DatasetDetailPane.tsx` | Full sample detail view with field expansion and workflow preview |

**Used by:** `DatasetsPage`

---

## State and error components { #state--error-components }

### AppErrorBoundary

| Field | Value |
|---|---|
| **File** | `components/states/AppErrorBoundary.tsx` |
| **Purpose** | React class component error boundary wrapping the entire application. Catches render-time errors via `getDerivedStateFromError`. Renders `ErrorBanner` fallback with the caught error message. Does not report errors to any telemetry service. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `children` | `ReactNode` | yes | Subtree to protect |

**Used by:** `main.tsx` (wraps `<App>`)

---

### EmptyState

| Field | Value |
|---|---|
| **File** | `components/states/EmptyState.tsx` |
| **Purpose** | Decorative empty-state placeholder using `╔══════════════╗` ASCII box art. Displays a message and optional call-to-action. Also exports `EmptyStateWithHome`, a convenience wrapper with a "go to dashboard" link. |

| Prop | Type | Required | Description |
|---|---|---|---|
| `message` | `string` | yes | Primary empty-state message |
| `action` | `ReactNode` | no | CTA link or button |

**Used by:** `WorkflowsPage`, `RunsPage`, `DatasetsPage` (when lists are empty)

---

## Page components

All pages reside in `src/pages/`. None use `React.lazy`. None have authentication guards. All are registered in the flat `<Routes>` block in `App.tsx`.

---

### DashboardPage

| Field | Value |
|---|---|
| **File** | `pages/DashboardPage.tsx` |
| **Route** | `/` |
| **Purpose** | Aggregate statistics overview. Stat cards (via `BBox`), 14-day activity `BSpark` sparklines per workflow, status donut bars, recent runs table (`StatusBadge`/`DurationDisplay`), and a workflows quick list with `BDagMini` thumbnails. |
| **Props** | None (route component) |
| **Hooks** | `useRunsSummary()`, `useRuns()`, `useWorkflows()`, `useWorkflowDAG()` (per workflow), `useHotkeys()` |
| **Key components** | `BTopBar`, `BBox`, `BPill`, `BSpark`, `StatusBadge`, `DurationDisplay`, `BDagMini` |

---

### WorkflowsPage

| Field | Value |
|---|---|
| **File** | `pages/WorkflowsPage.tsx` |
| **Route** | `/workflows` |
| **Purpose** | Searchable list of all registered workflows. Each card shows workflow name, description, `BDagMini` thumbnail, and a `BPill` for the latest run status. Text search filters by name and description. |
| **Props** | None |
| **Hooks** | `useWorkflows()`, `useRuns()` |
| **Key components** | `BTopBar`, `BBox`, `BPill`, `BDagMini`, `EmptyState` |

---

### WorkflowDetailPage

| Field | Value |
|---|---|
| **File** | `pages/WorkflowDetailPage.tsx` |
| **Route** | `/workflows/:name` |
| **Purpose** | Static DAG preview, run configuration form, and recent run history sidebar. Supports batch run mode (run multiple inputs consecutively) with a progress counter. The edit button is only shown when `isWorkflowBuilderEnabled()` returns true. |
| **Props** | None |
| **Hooks** | `useWorkflowDAG()`, `useRuns()`, `useMutation(runWorkflow)` |
| **Key components** | `BTopBar`, `WorkflowDAG`, `RunConfigForm`, `RunList`, `BBox`, `BPill` |

---

### WorkflowEditorPage

| Field | Value |
|---|---|
| **File** | `pages/WorkflowEditorPage.tsx` |
| **Route** | `/workflows/:name/edit` |
| **Purpose** | Split-pane YAML workflow editor. Left half: `WorkflowDAG` (live DAG preview). Right half: raw YAML textarea and validation issue panel. Selecting a node opens `StepInspector` (inline, defined in the page file). Save and validate actions use `useMutation` hooks; on successful save the QueryClient cache for `workflow-dag` is invalidated. Rendered only when `isWorkflowBuilderEnabled()` is true; `App.tsx` wraps the route in a feature flag guard. |
| **Props** | None |
| **Hooks** | `useWorkflowEditor()`, `useMutation(saveWorkflow)`, `useMutation(validateWorkflow)`, `useQueryClient()` |
| **Key components** | `BTopBar`, `WorkflowDAG`, `BBox`, `BPill` |
| **Internal sub-component** | `StepInspector` — node config detail panel, defined inline in the page file |

---

### RunsPage

| Field | Value |
|---|---|
| **File** | `pages/RunsPage.tsx` |
| **Route** | `/runs` |
| **Purpose** | Full run history table with status filter tabs (all / success / failed / running) and client-side text search. Each row links to `/runs/:filename`. Polls every 5 s via `useRuns(refetchInterval: 5000)`. |
| **Props** | None |
| **Hooks** | `useRuns()` (5 s poll), `useRunsSummary()` |
| **Key components** | `BTopBar`, `BPill`, `StatusBadge`, `DurationDisplay`, `EmptyState` |

---

### RunDetailPage

| Field | Value |
|---|---|
| **File** | `pages/RunDetailPage.tsx` |
| **Route** | `/runs/:filename` |
| **Purpose** | Post-run detail view. WorkflowDAG canvas shows completed step states. Right sidebar contains: evaluation score box (if present), score detail accordion, steps accordion. `edgeCounts` and `kickbackEdges` are computed via `useMemo` from run data. |
| **Props** | None |
| **Hooks** | `useRunDetail(filename)`, `useWorkflowDAG(run?.workflow_name)` |
| **Key components** | `BTopBar`, `WorkflowDAG`, `BBox`, `BPill`, `BAsciiBar`, `DurationDisplay`, `RunDetailSteps`, `EvaluationRubricAccordion` |

---

### LivePage

| Field | Value |
|---|---|
| **File** | `pages/LivePage.tsx` |
| **Route** | `/live/:runId` |
| **Purpose** | Real-time execution monitoring. WorkflowDAG canvas receives live `stepStates` from `useWorkflowStream`. Right sidebar: `TokenCounter`, `LiveStepDetails`, `StepLogPanel`, inline `EvaluationCard` (defined in the page file). Auto-selects the current running step. |
| **Props** | None |
| **Hooks** | `useWorkflowStream(runId)`, `useWorkflowDAG(workflowName)` |
| **Key components** | `BTopBar`, `WorkflowDAG`, `BBox`, `TokenCounter`, `LiveStepDetails`, `StepLogPanel` |
| **Internal sub-component** | `EvaluationCard` — renders evaluation result when `workflow_end` includes evaluation data; defined inline in the page file |
| **Real-time** | Yes — WebSocket via `useWorkflowStream`; auto-panning DAG |

---

### DatasetsPage

| Field | Value |
|---|---|
| **File** | `pages/DatasetsPage.tsx` |
| **Route** | `/datasets` |
| **Purpose** | Dataset exploration shell. Renders `DatasetBrowser` and passes the dataset count as a subtitle. All data logic is delegated to `DatasetBrowser`. |
| **Props** | None |
| **Hooks** | `useEvaluationDatasets()` (for count display in subtitle only) |
| **Key components** | `BTopBar`, `DatasetBrowser` |

---

### EvaluationsPage

| Field | Value |
|---|---|
| **File** | `pages/EvaluationsPage.tsx` |
| **Route** | `/evaluations` |
| **Purpose** | Evaluation results dashboard. 20-bucket score histogram, workflow pass-rate `BAsciiBar` rows, expandable evaluation table. Expanding a row renders an inline `EvaluationRubricAccordion`. Filtering by workflow via URL search params. |
| **Props** | None |
| **Hooks** | `useRuns()`, `useRunEvaluationDetail()` (per expanded row) |
| **Key components** | `BTopBar`, `BBox`, `BPill`, `BAsciiBar`, `DurationDisplay`, `EvaluationRubricAccordion` |

---

## Component dependency matrix

The table below maps each page to the shared components it directly renders. Transitive dependencies (e.g., `EvaluationRubricAccordion` → `CriterionRow`) are not shown.

| Component | Dashboard | Workflows | WF Detail | WF Editor | Runs | Run Detail | Live | Datasets | Evaluations |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `BTopBar` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `BBox` | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | | ✓ |
| `BPill` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `BAsciiBar` | | | | | | ✓ | | | ✓ |
| `BSpark` | ✓ | | | | | | | | |
| `StatusBadge` | ✓ | | | | ✓ | ✓ | | | |
| `DurationDisplay` | ✓ | | ✓ | | ✓ | ✓ | ✓ | | ✓ |
| `JsonViewer` | | | | | | ✓ | ✓ | | |
| `WorkflowDAG` | | | ✓ | ✓ | | ✓ | ✓ | | |
| `BDagMini` | ✓ | ✓ | | | | | | | |
| `RunConfigForm` | | | ✓ | | | | | | |
| `RunDetail` | | | | | | ✓ | | | |
| `RunList` | | | ✓ | | | | | | |
| `LiveStepDetails` | | | | | | | ✓ | | |
| `StepLogPanel` | | | | | | | ✓ | | |
| `TokenCounter` | | | | | | | ✓ | | |
| `EvaluationRubricAccordion` | | | | | | ✓ | | | ✓ |
| `DatasetBrowser` | | | | | | | | ✓ | |
| `EmptyState` | | ✓ | | | ✓ | | | ✓ | |
