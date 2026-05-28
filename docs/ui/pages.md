# UI Pages Reference

**Source root:** `agentic-workflows-v2/ui/src/pages/`
**Router:** react-router-dom v7 (`BrowserRouter`, flat `<Routes>` block in `App.tsx`)
**Page count:** 9 (8 primary + 1 feature-flagged)

This document describes each application page: its route, purpose, which components it renders, which API calls it makes, and whether it includes real-time streaming features.

---

## Route Map

| Page | Route | Real-time |
|---|---|---|
| [DashboardPage](#dashboardpage) | `/` | No |
| [WorkflowsPage](#workflowspage) | `/workflows` | No |
| [WorkflowDetailPage](#workflowdetailpage) | `/workflows/:name` | No |
| [WorkflowEditorPage](#workfloweditorpage) | `/workflows/:name/edit` | No |
| [RunsPage](#runspage) | `/runs` | Polling (5 s) |
| [RunDetailPage](#rundetailpage) | `/runs/:filename` | No |
| [LivePage](#livepage) | `/live/:runId` | Yes — WebSocket |
| [DatasetsPage](#datasetspage) | `/datasets` | No |
| [EvaluationsPage](#evaluationspage) | `/evaluations` | No |

`WorkflowEditorPage` is only rendered when the `__AGENTIC_ENABLE_WORKFLOW_BUILDER__` feature flag is true. `App.tsx` wraps the route in a `isWorkflowBuilderEnabled()` guard; without the flag the route returns `null`.

---

## DashboardPage

**Route:** `/`
**File:** `pages/DashboardPage.tsx`

### Purpose

The landing page. Displays aggregate statistics across all runs, per-workflow activity sparklines, a recent runs table, and a workflow quick-access grid. Designed to give an at-a-glance health overview of the entire system.

### Layout

```
┌──────────────────────────────────────────────┐
│ BTopBar (dashboard)                          │
├──────────────────────────────────────────────┤
│ Stat cards row (BBox × 4)                    │
│  total runs │ success rate │ avg dur │ tokens │
├────────────────────────┬─────────────────────┤
│ 14-day activity area   │ Workflows quick list │
│ (BSpark per workflow)  │ (BDagMini thumbnails)│
├────────────────────────┴─────────────────────┤
│ Recent runs table (StatusBadge, BPill, Dur.) │
└──────────────────────────────────────────────┘
```

### API Calls

| Hook | Query key | Endpoint | Notes |
|---|---|---|---|
| `useRunsSummary()` | `['runs-summary']` | `GET /api/runs/summary` | Stat card data |
| `useRuns()` | `['runs']` | `GET /api/runs` | Recent runs table |
| `useWorkflows()` | `['workflows']` | `GET /api/workflows` | Workflow list for quick grid |
| `useWorkflowDAG(name)` | `['workflow-dag', name]` | `GET /api/workflows/:name/dag` | One call per workflow for `BDagMini` |

All queries use the default `staleTime: 10 000 ms` and no `refetchInterval`.

### Key Components

- `BTopBar` — page breadcrumb
- `BBox` — stat card wrappers
- `BSpark` — per-workflow 14-day sparklines (`useMemo` over bucketed run counts)
- `BAsciiBar` — status distribution bars (success / failed / running ratio)
- `StatusBadge` — recent run status tokens
- `DurationDisplay` — run duration formatting
- `BDagMini` — workflow thumbnail SVGs in quick list

### Keyboard Shortcuts

| Key | Action |
|---|---|
| `/` | Focus the filter input (bound via `useHotkeys`) |
| `Escape` | Blur active filter input |

### Real-time Features

None. Data is fetched once on mount with default stale-time caching.

---

## WorkflowsPage

**Route:** `/workflows`
**File:** `pages/WorkflowsPage.tsx`

### Purpose

Browsable, searchable list of all registered workflows. Each card shows the workflow name, description, a `BDagMini` thumbnail, and a `BPill` for the most recent run status (resolved by iterating `useRuns()` results).

### Layout

```
┌──────────────────────────────────────────┐
│ BTopBar (workflows)   [search input]     │
├──────────────────────────────────────────┤
│ Grid of workflow cards                   │
│  ┌──────────────┐  ┌──────────────┐      │
│  │ BDagMini     │  │ BDagMini     │  ... │
│  │ name + desc  │  │ name + desc  │      │
│  │ BPill status │  │ BPill status │      │
│  └──────────────┘  └──────────────┘      │
└──────────────────────────────────────────┘
```

### API Calls

| Hook | Query key | Endpoint |
|---|---|---|
| `useWorkflows()` | `['workflows']` | `GET /api/workflows` |
| `useRuns()` | `['runs']` | `GET /api/runs` |
| `useWorkflowDAG(name)` | `['workflow-dag', name]` | `GET /api/workflows/:name/dag` |

DAG queries are issued once per unique workflow name to provide `BDagMini` thumbnails.

### Key Components

- `BTopBar` — page breadcrumb with inline `/` search shortcut label
- `BDagMini` — static workflow DAG thumbnail
- `BPill` — latest run status indicator
- `EmptyState` — shown when no workflows are registered

### Real-time Features

None.

---

## WorkflowDetailPage

**Route:** `/workflows/:name`
**File:** `pages/WorkflowDetailPage.tsx`

### Purpose

Detail view for a single workflow. Provides a static DAG preview, a run configuration form, and a scrollable recent-run history sidebar. Supports batch run mode: when more than one dataset sample is selected in `RunConfigForm`, the page iterates through submissions and shows a progress counter.

### Layout

```
┌──────────────────────────────────────────────────┐
│ BTopBar (workflows/:name)  [Edit button?]         │
├────────────────────────────┬─────────────────────┤
│                            │ RunList sidebar       │
│   WorkflowDAG (static)     │ (recent runs)        │
│                            │                      │
├────────────────────────────┤                      │
│   RunConfigForm            │                      │
└────────────────────────────┴─────────────────────┘
```

The Edit button is conditionally rendered: `isWorkflowBuilderEnabled() && <Link to="edit">`.

### API Calls

| Hook | Query key | Endpoint | Notes |
|---|---|---|---|
| `useWorkflowDAG(name)` | `['workflow-dag', name]` | `GET /api/workflows/:name/dag` | DAG structure and input schema |
| `useRuns()` | `['runs']` | `GET /api/runs` | History sidebar data |
| `useMutation(runWorkflow)` | — | `POST /api/run` | Form submission; navigates to `/live/:runId` on success |
| `useEvaluationDatasets()` | `['eval-datasets']` | `GET /api/eval/datasets` | Loaded lazily when eval toggle enabled in RunConfigForm |

### Key Components

- `BTopBar` — breadcrumb with optional Edit link
- `WorkflowDAG` — static preview (no `stepStates`)
- `RunConfigForm` — full submission form
- `RunList` — recent run history
- `BBox` — section wrappers

### Real-time Features

None on this page. After form submission the page navigates to `LivePage`.

---

## WorkflowEditorPage

**Route:** `/workflows/:name/edit`
**File:** `pages/WorkflowEditorPage.tsx`
**Feature flag:** Only rendered when `isWorkflowBuilderEnabled()` returns `true`

### Purpose

Split-pane workflow editor. Left pane is a live DAG preview (re-renders as YAML is edited). Right pane contains a raw YAML textarea, a validation issue list, and save/validate action buttons. Clicking a node in the DAG opens a `StepInspector` panel showing that step's current config.

### Layout

```
┌──────────────────────────────────────────────────────┐
│ BTopBar (workflows/:name/edit)  [Save] [Validate]     │
├────────────────────────────┬─────────────────────────┤
│                            │ YAML textarea            │
│   WorkflowDAG (live        │                          │
│   preview from parsed      │ Validation issues list   │
│   YAML)                    │ (BPill err/warn)         │
│                            │                          │
│   [StepInspector overlay   │                          │
│    when node selected]     │                          │
└────────────────────────────┴─────────────────────────┘
```

### API Calls

| Hook | Query key | Endpoint | Notes |
|---|---|---|---|
| `useWorkflowEditor(name)` | `['workflow-editor', name]` | `GET /api/workflows/:name/editor` | Loads workflow YAML source |
| `useMutation(validateWorkflow)` | — | `POST /api/workflows/:name/validate` | Lint-only, no save |
| `useMutation(saveWorkflow)` | — | `PUT /api/workflows/:name` | Saves YAML; on success invalidates `workflow-dag` and `workflow-editor` query keys |

After a successful save `queryClient.invalidateQueries(['workflow-dag', name])` is called to refresh the DAG preview and any other pages showing that workflow.

### Key Components

- `BTopBar` — breadcrumb with Save and Validate buttons
- `WorkflowDAG` — live preview (props derived from parsed YAML, not the saved API response)
- `BBox` — section containers
- `BPill` — validation issue severity badges
- `StepInspector` — inline sub-component (not exported); shows selected node's fields from the parsed YAML

### Real-time Features

None. The DAG preview is driven by local YAML parse state, not a WebSocket.

---

## RunsPage

**Route:** `/runs`
**File:** `pages/RunsPage.tsx`

### Purpose

Complete run history table. Supports status filtering via tabs (all / success / failed / running) and client-side text search over run_id and workflow_name. Rows link to `/runs/:filename` for full detail. Data refreshes on a 5-second polling interval.

### Layout

```
┌──────────────────────────────────────────────┐
│ BTopBar (runs)   [search input]              │
├──────────────────────────────────────────────┤
│ Filter tabs: all · success · failed · running│
├──────────────────────────────────────────────┤
│ Runs table                                   │
│  run_id │ workflow │ status │ steps │ dur    │
│  ...    │ ...      │ BPill  │ ...   │ Dur.   │
└──────────────────────────────────────────────┘
```

### API Calls

| Hook | Query key | Endpoint | Notes |
|---|---|---|---|
| `useRuns()` | `['runs']` | `GET /api/runs` | `refetchInterval: 5000` (5 s polling) |
| `useRunsSummary()` | `['runs-summary']` | `GET /api/runs/summary` | Summary stats row at top |

`useRuns` is the only hook in the application that uses `refetchInterval`. Polling is unconditional (not paused when tab is hidden or user is inactive).

### Key Components

- `BTopBar` — breadcrumb with search input
- `BPill` — per-run status badge
- `StatusBadge` — fixed-width ASCII status tokens
- `DurationDisplay` — run duration
- `EmptyState` — shown when no runs match the active filter

### Real-time Features

Soft real-time via 5-second polling. Not a WebSocket — the entire run list is re-fetched on interval.

---

## RunDetailPage

**Route:** `/runs/:filename`
**File:** `pages/RunDetailPage.tsx`

### Purpose

Static post-run analysis page. Renders the completed run's workflow as a DAG with per-step status overlays. The right sidebar shows evaluation results (if the run requested evaluation) and an expandable step accordion. `edgeCounts` and `kickbackEdges` are derived from run data via `useMemo`.

### Layout

```
┌─────────────────────────────────────────────────────┐
│ BTopBar (runs/:filename)  [← back button]           │
├────────────────────────────────┬────────────────────┤
│                                │ [Evaluation box]    │
│   WorkflowDAG                  │   score + grade     │
│   (stepStates from run data)   │   BAsciiBar         │
│                                │                     │
│                                │ [Score detail box]  │
│                                │  EvalRubricAccordion│
│                                │                     │
│                                │ [Steps box]         │
│                                │  RunDetailSteps     │
└────────────────────────────────┴────────────────────┘
```

### API Calls

| Hook | Query key | Endpoint | Notes |
|---|---|---|---|
| `useRunDetail(filename)` | `['run', filename]` | `GET /api/runs/:filename` | Full run data including steps |
| `useWorkflowDAG(name)` | `['workflow-dag', name]` | `GET /api/workflows/:name/dag` | DAG structure for the canvas |
| `useRunEvaluationDetail(filename)` | `['run-eval', filename]` | `GET /api/runs/:filename/evaluation` | Only fetched if `run.extra?.evaluation` is non-null |

### Computed State (useMemo)

Two values are computed from the raw run data rather than fetched:

**`stepStates`** — a `Map<string, StepState>` built from `run.steps[]`, including status, duration, model, tokens, and `model_inferred` flag from metadata.

**`edgeCounts`** — a `Map<string, number>` counting active traversals per edge. An edge is counted only when: the source step has `status === 'success'` AND the target step has `status !== 'pending'`.

**`kickbackEdges`** — a `Set<string>` of edge keys (`"source->target"`) where the source matches `/(review|test)/i` and the target matches `/(rework|developer|generate|fix)/i`. These edges receive violet styling in the DAG canvas.

### Key Components

- `BTopBar` — breadcrumb with ESC back button
- `WorkflowDAG` — completed-run overlay mode
- `BBox` — evaluation and steps section containers
- `BPill` — run status and evaluation pass/fail
- `BAsciiBar` — evaluation score bar
- `DurationDisplay` — run and per-step durations
- `RunDetailSteps` — expandable step accordion with I/O viewers
- `EvaluationRubricAccordion` — detailed criterion breakdown

### Real-time Features

None. This page displays completed run data only.

---

## LivePage

**Route:** `/live/:runId`
**File:** `pages/LivePage.tsx`

### Purpose

Real-time execution monitoring page. The central feature of the application. Consumes a WebSocket stream via `useWorkflowStream(runId)` and drives a live DAG canvas, step detail panel, token counter, and execution event log. Auto-selects the currently running step.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│ BTopBar (live/:runId)                                    │
├────────────────────────────────────┬────────────────────┤
│                                    │ TokenCounter        │
│   WorkflowDAG                      │                     │
│   (live stepStates from WS)        │ LiveStepDetails     │
│   auto-panning                     │ (step list +        │
│                                    │  expand panels)     │
│                                    │                     │
│                                    │ StepLogPanel        │
│                                    │ (event log)         │
│                                    │                     │
│                                    │ [EvaluationCard]    │
│                                    │ (when WF ends with  │
│                                    │  eval data)         │
└────────────────────────────────────┴────────────────────┘
```

### API Calls

| Hook | Query key | Endpoint | Notes |
|---|---|---|---|
| `useWorkflowDAG(name)` | `['workflow-dag', name]` | `GET /api/workflows/:name/dag` | Loaded once; workflow name comes from `workflow_start` event |

The live step data does NOT come from a REST endpoint. It is built entirely from WebSocket events by the `useWorkflowStream` hook.

### WebSocket

`useWorkflowStream(runId)` connects to:

```
ws[s]://<host>/ws/execution/<runId>
```

The hook returns `WorkflowStreamState`:

| Field | Type | Description |
|---|---|---|
| `status` | `'idle' \| 'connecting' \| 'running' \| 'completed' \| 'error'` | Connection / run lifecycle status |
| `stepStates` | `Map<string, StepState>` | Mutable step state map; updated on each event |
| `steps` | `StepResult[]` | Ordered step accumulation (completed steps appended) |
| `events` | `ExecutionEvent[]` | Append-only event log |
| `workflowName` | `string \| null` | Extracted from `workflow_start` event |
| `evaluation` | `EvaluationResult \| null` | Populated by `evaluation_complete` event |
| `error` | `string \| null` | Set on transport error or `error` event |

**Reconnection:** Exponential backoff — 1 s, 2 s, 4 s, 8 s, 16 s (5 retries, 31 s total). After exhausting retries the hook sets `status: 'error'` and stops reconnecting.

**Auto-select running step:** `LivePage` watches `stepStates` for the first entry with status `running` and calls `setSelectedStep(name)` to drive `LiveStepDetails` selection and the DAG `selectedStep` prop.

### Key Components

- `BTopBar` — breadcrumb
- `WorkflowDAG` — live mode (auto-pan, optimistic status promotion)
- `TokenCounter` — cumulative token display
- `LiveStepDetails` — scrollable step sidebar
- `StepLogPanel` — timestamped event log
- `EvaluationCard` — inline sub-component (not exported); rendered when `evaluation` is non-null

### Real-time Features

Full real-time via WebSocket. The page is the primary consumer of the streaming execution pipeline.

---

## DatasetsPage

**Route:** `/datasets`
**File:** `pages/DatasetsPage.tsx`

### Purpose

Dataset browser shell. The page itself is thin — it renders `DatasetBrowser` and passes total dataset count as a subtitle to `BTopBar`. All selection, pagination, and detail logic is encapsulated in `DatasetBrowser`.

### Layout

```
┌──────────────────────────────────────────────────┐
│ BTopBar (datasets · N datasets)                  │
├──────────────────────────────────────────────────┤
│ DatasetBrowser (3-pane)                          │
│  dataset list │ sample grid │ sample detail       │
└──────────────────────────────────────────────────┘
```

### API Calls

All queries are delegated to `DatasetBrowser` and its internal hooks:

| Hook | Endpoint | Notes |
|---|---|---|
| `useEvaluationDatasets()` | `GET /api/eval/datasets` | Dataset list (repository + local + eval sets) |
| `useDatasetSamples(source, id, offset, limit)` | `GET /api/eval/datasets/sample-list` | Paginated sample index |
| `useDatasetSampleDetail(source, id, index)` | `GET /api/eval/datasets/sample-detail` | Full sample field data |

`DatasetsPage` itself calls `useEvaluationDatasets()` once at the top level to extract the total count for the subtitle.

### Key Components

- `BTopBar` — breadcrumb with dataset count subtitle
- `DatasetBrowser` — full 3-pane dataset UI (contains `SampleIndexGrid` and `DatasetDetailPane`)

### Real-time Features

None.

---

## EvaluationsPage

**Route:** `/evaluations`
**File:** `pages/EvaluationsPage.tsx`

### Purpose

Evaluation results overview. Displays a 20-bucket score distribution histogram, per-workflow pass-rate rows with `BAsciiBar`, and an expandable evaluation table. Expanding any row loads and renders an inline `EvaluationRubricAccordion`. URL search params support workflow-name filtering.

### Layout

```
┌──────────────────────────────────────────────────────┐
│ BTopBar (evaluations)  [workflow filter select]      │
├──────────────────────────────────────────────────────┤
│ Score histogram (20 buckets, BAsciiBar × 20)         │
├──────────────────────────────────────────────────────┤
│ Workflow pass-rate section                           │
│  workflow A  [█████████░░░] 82%  (BAsciiBar)         │
│  workflow B  [██████░░░░░░] 64%                      │
├──────────────────────────────────────────────────────┤
│ Evaluations table                                    │
│  run_id │ workflow │ score │ grade │ BPill pass/fail │
│  ▶ [expand row → EvaluationRubricAccordion]          │
└──────────────────────────────────────────────────────┘
```

### API Calls

| Hook | Query key | Endpoint | Notes |
|---|---|---|---|
| `useRuns()` | `['runs']` | `GET /api/runs` | Filters to runs with `evaluation_score != null` |
| `useRunEvaluationDetail(filename)` | `['run-eval', filename]` | `GET /api/runs/:filename/evaluation` | Fired lazily when a table row is expanded |

Score histogram and pass-rate bars are computed client-side via `useMemo` from the `runs` array — no separate aggregation endpoint.

### Key Components

- `BTopBar` — breadcrumb with workflow filter
- `BBox` — section wrappers
- `BPill` — per-run pass/fail badges
- `BAsciiBar` — score histogram cells and pass-rate bars
- `DurationDisplay` — run duration in table rows
- `EvaluationRubricAccordion` — lazy-loaded detail accordion per expanded row

### Real-time Features

None.
