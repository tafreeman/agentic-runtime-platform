# UI API integration reference

**Source root:** `agentic-workflows-v2/ui/src/`
**Data layer:** TanStack Query v5 (REST) + native WebSocket (streaming execution)
**Backend base URL:** `/api` (proxied by Vite dev server; production: same-origin)

This document describes how the React UI communicates with the backend. It covers the REST API client, all TanStack Query hooks (query keys, endpoints, caching), the WebSocket execution stream (connection lifecycle, event types, error handling), and the secondary WebSocket for live node config overrides.

---

## Table of contents

1. [REST API client](#rest-api-client)
2. [TanStack Query configuration](#tanstack-query-configuration)
3. [Query hooks reference](#query-hooks-reference)
4. [Mutation hooks reference](#mutation-hooks-reference)
5. [WebSocket: execution stream](#websocket-execution-stream)
6. [WebSocket: node config updates](#websocket-node-config-updates)
7. [TypeScript contract: event types](#typescript-contract-event-types)
8. [Error handling patterns](#error-handling-patterns)
9. [Caching and invalidation](#caching-and-invalidation)

---

## REST API client

**File:** `api/client.ts`

All HTTP calls funnel through a single `fetchJSON<T>` helper:

```
fetchJSON<T>(path: string, options?: RequestInit): Promise<T>
```

- Prefixes all paths with `/api`
- Throws `Error` if `response.ok` is false (status >= 400), using the response body text as the error message where available
- Returns the parsed JSON body typed as `T`

### Complete API function inventory

| Function | Method | Endpoint | Return type |
|---|---|---|---|
| `fetchWorkflows()` | GET | `/api/workflows` | `{ workflows: string[] }` |
| `fetchWorkflowDAG(name)` | GET | `/api/workflows/:name/dag` | `DAGResponse` |
| `fetchWorkflowEditor(name)` | GET | `/api/workflows/:name/editor` | `WorkflowEditorDocument` |
| `saveWorkflow(name, req)` | PUT | `/api/workflows/:name` | `WorkflowEditorSaveResponse` |
| `validateWorkflow(name, req)` | POST | `/api/workflows/validate` | `WorkflowEditorValidateResponse` |
| `fetchRuns()` | GET | `/api/runs` | `RunSummary[]` |
| `fetchRunDetail(filename)` | GET | `/api/runs/:filename` | `RunDetail` |
| `fetchRunsSummary()` | GET | `/api/runs/summary` | `RunsSummary` |
| `fetchRunEvaluationDetail(filename)` | GET | `/api/runs/:filename/evaluation` | `RunEvaluationDetailResponse` |
| `runWorkflow(req)` | POST | `/api/run` | `WorkflowRunResponse` |
| `fetchAgents()` | GET | `/api/agents` | `AgentInfo[]` |
| `fetchEvaluationDatasets()` | GET | `/api/eval/datasets` | `EvaluationDatasetsResponse` |
| `fetchDatasetSamples(source, id, offset, limit)` | GET | `/api/eval/datasets/sample-list` | `DatasetSampleListResponse` |
| `fetchDatasetSampleDetail(source, id, index)` | GET | `/api/eval/datasets/sample-detail` | `DatasetSampleDetailResponse` |

---

## TanStack Query configuration

**File:** `main.tsx`

The `QueryClient` is created once at application bootstrap:

```
new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,        // 10 seconds — data stays fresh
      retry: 1,                 // one retry on failure
      refetchOnWindowFocus: false,
    },
  },
})
```

**Design decisions:**

- `staleTime: 10_000` prevents duplicate in-flight requests when multiple components on the same page subscribe to the same query key. Data that is less than 10 seconds old is served from cache without a network call.
- `retry: 1` reduces noise from transient backend errors while still surfacing persistent failures quickly.
- `refetchOnWindowFocus: false` was disabled because the application is frequently used alongside a terminal — refetching on every focus switch creates unnecessary load.

---

## Query hooks reference

All query hooks are defined in `hooks/useWorkflows.ts`, `hooks/useRuns.ts`, and `hooks/useDatasets.ts`.

### useWorkflows

**File:** `hooks/useWorkflows.ts`

```
useWorkflows(): UseQueryResult<string[]>
```

| Field | Value |
|---|---|
| Query key | `['workflows']` |
| Fetcher | `fetchWorkflows()` |
| Endpoint | `GET /api/workflows` |
| staleTime | Default (10 s) |
| refetchInterval | None |
| Used by | `WorkflowsPage`, `DashboardPage` |

The endpoint returns `{ workflows: string[] }`; the hook unwraps the `workflows` array, so consumers receive a bare `string[]` of workflow names.

---

### useWorkflowDAG

**File:** `hooks/useWorkflows.ts`

```
useWorkflowDAG(name: string | undefined): UseQueryResult<DAGResponse>
```

| Field | Value |
|---|---|
| Query key | `['workflow-dag', name]` |
| Fetcher | `fetchWorkflowDAG(name)` |
| Endpoint | `GET /api/workflows/:name/dag` |
| Enabled | Only when `name` is non-empty |
| staleTime | Default (10 s) |
| Used by | `WorkflowDetailPage`, `WorkflowEditorPage`, `RunDetailPage`, `LivePage`, `WorkflowsPage` (via BDagMini), `DashboardPage` (via BDagMini) |

---

### useWorkflowEditor

**File:** `hooks/useWorkflows.ts`

```
useWorkflowEditor(name: string): UseQueryResult<WorkflowEditorDocument>
```

| Field | Value |
|---|---|
| Query key | `['workflow-editor', name]` |
| Fetcher | `fetchWorkflowEditor(name)` |
| Endpoint | `GET /api/workflows/:name/editor` |
| Used by | `WorkflowEditorPage` |

Returns the full YAML source (`WorkflowEditorDocument.source`) and parsed step definitions. The `read_only` field indicates whether the backend allows saving.

---

### useEvaluationDatasets

**File:** `hooks/useWorkflows.ts`

```
useEvaluationDatasets(): UseQueryResult<EvaluationDatasetsResponse>
```

| Field | Value |
|---|---|
| Query key | `['eval-datasets']` |
| Fetcher | `fetchEvaluationDatasets()` |
| Endpoint | `GET /api/eval/datasets` |
| Used by | `RunConfigForm` (lazy, when eval toggle enabled), `DatasetsPage` |

`EvaluationDatasetsResponse` contains three lists: `repository` datasets, `local` datasets, and `eval_sets` (named collections).

---

### useRuns

**File:** `hooks/useRuns.ts`

```
useRuns(): UseQueryResult<RunSummary[]>
```

| Field | Value |
|---|---|
| Query key | `['runs']` |
| Fetcher | `fetchRuns()` |
| Endpoint | `GET /api/runs` |
| **refetchInterval** | **5 000 ms (5 seconds)** |
| Used by | `RunsPage`, `WorkflowDetailPage`, `WorkflowsPage`, `DashboardPage`, `EvaluationsPage` |

This is the only query in the application with a polling interval. The 5-second refresh keeps run lists current during active workflow executions without requiring a full WebSocket connection. The interval runs unconditionally regardless of window focus.

---

### useRunDetail

**File:** `hooks/useRuns.ts`

```
useRunDetail(filename: string | undefined): UseQueryResult<RunDetail>
```

| Field | Value |
|---|---|
| Query key | `['run', filename]` |
| Fetcher | `fetchRunDetail(filename)` |
| Endpoint | `GET /api/runs/:filename` |
| Enabled | Only when `filename` is defined |
| Used by | `RunDetailPage` |

Returns the complete `RunDetail` including the full `steps[]` array with per-step I/O.

---

### useRunsSummary

**File:** `hooks/useRuns.ts`

```
useRunsSummary(): UseQueryResult<RunsSummary>
```

| Field | Value |
|---|---|
| Query key | `['runs-summary']` |
| Fetcher | `fetchRunsSummary()` |
| Endpoint | `GET /api/runs/summary` |
| Used by | `DashboardPage`, `RunsPage` |

Aggregate statistics: `total_runs`, `success`, `failed`, `avg_duration_ms`, `workflows[]`, `tokens_30d`.

---

### useRunEvaluationDetail

**File:** `hooks/useRuns.ts`

```
useRunEvaluationDetail(filename: string | undefined): UseQueryResult<RunEvaluationDetailResponse>
```

| Field | Value |
|---|---|
| Query key | `['run-eval', filename]` |
| Fetcher | `fetchRunEvaluationDetail(filename)` |
| Endpoint | `GET /api/runs/:filename/evaluation` |
| Enabled | Only when `filename` is defined |
| Used by | `RunDetailPage` (conditional on `run.extra?.evaluation`), `EvaluationsPage` (lazy per expanded row) |

Returns the full `RunEvaluationDetail` with criteria, score layers, hard gates, floor violations, and step-level scores.

---

### useDatasetSamples

**File:** `hooks/useDatasets.ts`

```
useDatasetSamples(
  source: string | null,
  id: string | null,
  offset: number,
  limit: number
): UseQueryResult<DatasetSampleListResponse>
```

| Field | Value |
|---|---|
| Query key | `['dataset-samples', source, id, offset, limit]` |
| Endpoint | `GET /api/eval/datasets/sample-list?dataset_source=&dataset_id=&offset=&limit=` |
| Enabled | Only when both `source` and `id` are non-null |
| Used by | `DatasetBrowser` (SampleIndexGrid) |

Paginated. The query key includes `offset` and `limit` so each page is independently cached.

---

### useDatasetSampleDetail

**File:** `hooks/useDatasets.ts`

```
useDatasetSampleDetail(
  source: string | null,
  id: string | null,
  index: number | null
): UseQueryResult<DatasetSampleDetailResponse>
```

| Field | Value |
|---|---|
| Query key | `['dataset-sample-detail', source, id, index]` |
| Endpoint | `GET /api/eval/datasets/sample-detail?dataset_source=&dataset_id=&sample_index=` |
| Enabled | Only when all three params are non-null |
| Used by | `DatasetBrowser` (DatasetDetailPane) |

Returns full sample fields, `workflow_preview`, and `dataset_meta`.

---

## Mutation hooks reference

Mutations are created inline within page components using `useMutation` from TanStack Query. They are not extracted into custom hooks.

### runWorkflow

**Used in:** `WorkflowDetailPage`

```
useMutation({
  mutationFn: runWorkflow,        // POST /api/run
  onSuccess: (data) => {
    navigate(`/live/${data.run_id}`)
  }
})
```

Payload type: `WorkflowRunRequest`

```typescript
{
  workflow: string;
  input_data: Record<string, unknown>;
  run_id?: string;
  evaluation?: WorkflowEvaluationRequest;
  execution_profile?: ExecutionProfileRequest;
}
```

Response type: `WorkflowRunResponse` — `{ run_id: string, status: StepStatus }`.

On success the page navigates to `/live/:run_id`. In batch mode the page runs the mutation sequentially for each sample, incrementing a progress counter in between.

---

### validateWorkflow

**Used in:** `WorkflowEditorPage`

```
useMutation({
  mutationFn: (req) => validateWorkflow(name, req),   // POST /api/workflows/validate
})
```

Payload: `WorkflowEditorMutationRequest` — `{ source: string }` (the raw YAML text).

Response: `WorkflowEditorValidateResponse` — `{ valid, issues[], workflow? }`.

Issues are displayed inline as a list of `BPill`-tagged error/warning messages. Does not update the cache.

---

### saveWorkflow

**Used in:** `WorkflowEditorPage`

```
useMutation({
  mutationFn: (req) => saveWorkflow(name, req),       // PUT /api/workflows/:name
  onSuccess: () => {
    queryClient.invalidateQueries(['workflow-dag', name])
    queryClient.invalidateQueries(['workflow-editor', name])
  }
})
```

On success, two query keys are invalidated: `workflow-dag` and `workflow-editor` for the current workflow name. This triggers a refetch of the DAG preview and the editor source.

---

## WebSocket: execution stream

**File:** `api/websocket.ts`
**Consumer hook:** `hooks/useWorkflowStream.ts`

### Connection URL

```
ws[s]://<host>/ws/execution/<runId>
```

The protocol (`ws://` or `wss://`) mirrors the page's `http`/`https`. In the development environment, if `VITE_API_PROXY_TARGET` is set, the URL is constructed directly from that target — because Vite's HTTP proxy does not forward the WebSocket `Upgrade` header on all platforms.

### connectExecutionStream

```typescript
connectExecutionStream(
  runId: string,
  onEvent: (event: ExecutionEvent) => void,
  onClose: (code: number, reason: string) => void,
  onError: (error: Event) => void
): () => void   // returns a disconnect function
```

The function opens a native browser `WebSocket`, attaches message/close/error handlers, and returns a cleanup function that calls `ws.close()`. JSON parsing errors are caught and suppressed to prevent a single malformed frame from tearing down the connection.

### Reconnection logic

The reconnection loop is implemented inside `useWorkflowStream`, not in `connectExecutionStream`:

```
attempt 0: wait 1 s
attempt 1: wait 2 s
attempt 2: wait 4 s
attempt 3: wait 8 s
attempt 4: wait 16 s
attempt 5: stop — set status 'error'
```

Total maximum wait before giving up: 31 seconds.

Reconnection is only attempted when the WebSocket closes with a non-normal code (code !== 1000) or on a transport error. A normal close (code 1000) is treated as a deliberate server termination and does not trigger reconnect.

### useWorkflowStream

**File:** `hooks/useWorkflowStream.ts`

```typescript
useWorkflowStream(runId: string | null): WorkflowStreamState
```

Manages the full lifecycle of one execution WebSocket connection. Returns a `WorkflowStreamState` snapshot that is updated via `useReducer` on each incoming event.

**State shape:**

```typescript
interface WorkflowStreamState {
  status: 'idle' | 'connecting' | 'running' | 'completed' | 'error';
  stepStates: Map<string, StepState>;   // mutable map; all steps
  steps: StepResult[];                  // append-only; completed steps
  events: ExecutionEvent[];             // append-only; every event received
  workflowName: string | null;          // from workflow_start
  evaluation: EvaluationResult | null;  // from evaluation_complete
  error: string | null;                 // transport or event error
}
```

**Event state machine transitions:**

| Event received | State changes |
|---|---|
| `connection_established` | `status → 'connecting'` |
| `workflow_start` | `status → 'running'`; `workflowName` set |
| `step_start` | `stepStates[step] = { status: 'running', startTime }` |
| `step_end` | `stepStates[step] = { status, duration, model, tokens }`; step appended to `steps[]` |
| `step_complete` | Same as `step_end`; additionally sets `outputs` if present |
| `step_error` | `stepStates[step] = { status: 'failed', error }`; step appended to `steps[]` |
| `workflow_end` | `status → 'completed'` (or `'error'` if `status === 'failed'`) |
| `evaluation_start` | No state change (informational) |
| `evaluation_complete` | `evaluation` set from event payload |
| `error` (wire) | `error` field set; `status → 'error'` |
| `keepalive` | Ignored — not added to `events[]` |
| `connection_established` | Filtered from displayed events in `StepLogPanel` |

**`stepStates` is a `Map`, not plain state.** It is mutated in place within the reducer and a new `Map` reference is created on each step state change to trigger React re-renders. This avoids copying the entire map on every event while still satisfying React's referential equality check.

### StepState type

```typescript
interface StepState {
  status: StepStatus;
  durationMs?: number;
  modelUsed?: string;
  tokensUsed?: number;
  modelInferred?: boolean;
  error?: string;
  startTime?: number;       // Date.now() from step_start
}
```

---

## WebSocket: node config updates

**File:** `api/websocket.ts` (secondary connection)
**Consumer hook:** `hooks/useNodeConfigUpdate.ts`

A secondary WebSocket connection intended to allow live runtime configuration overrides on a running step, separate from the execution stream to avoid mixing control messages with event telemetry.

> **Not implemented on the backend.** The server registers only the execution-stream route (`/ws/execution/{run_id}` in `server/websocket.py`); there is no `/ws/node-config/` route. The client hook below exists but is unused — connecting to the URL shown would fail. This section documents the intended client-side contract for a feature that is not yet wired up end to end.

### Connection URL

The hook targets the following URL, which the backend does **not** currently serve:

```
ws[s]://<host>/ws/node-config/<runId>
```

### useNodeConfigUpdate

```typescript
useNodeConfigUpdate(
  runId: string | null,
  stepName: string | null
): {
  sendUpdate: (config: NodeConfigUpdate) => void;
  isConnected: boolean;
}
```

Connects when both `runId` and `stepName` are non-null. Reconnects on close with a fixed 3-second delay (not exponential — config updates are low-frequency advisory messages). Does not queue messages while disconnected.

**Outbound message shape:**

```json
{
  "type": "node_config_update",
  "step_name": "<step>",
  "config": {
    "model": "...",
    "system_prompt": "...",
    "temperature": 0.7,
    "max_tokens": 4096,
    "top_p": 1.0,
    "tool_names": ["tool_a", "tool_b"]
  }
}
```

> **Status note:** `useNodeConfigUpdate` and `NodeConfigOverlay` are fully implemented but not yet wired to any page. They are present for upcoming live config-override feature work.

---

## TypeScript contract: event types

**File:** `api/events.generated.ts`

This file is **auto-generated** from the Python Pydantic contract in `agentic_v2/contracts/events.py`. It must not be edited by hand.

### Regeneration

```bash
# From agentic-workflows-v2/:
python scripts/generate_ts_types.py

# Or from agentic-workflows-v2/ui/:
npm run generate:types
```

### CI enforcement

The `wire-format-drift` CI job runs on every PR. It regenerates the TypeScript types from the committed JSON Schema (`tests/schemas/events.schema.json`) and diffs the result against the committed `events.generated.ts`. Any mismatch fails the job, blocking merge.

**Implication:** Any change to the Python `ExecutionEvent` Pydantic union must be accompanied by:
1. A bump to the JSON Schema file
2. Running `npm run generate:types`
3. Committing the updated `events.generated.ts`

### Generated event union

```typescript
export type ExecutionEvent =
  | WorkflowStartEvent
  | StepStartEvent
  | StepEndEvent
  | StepCompleteEvent
  | StepErrorEvent
  | WorkflowEndEvent
  | ErrorEvent
  | EvaluationStartEvent
  | EvaluationCompleteEvent;
```

### Event type reference

| Type | Key fields | Direction |
|---|---|---|
| `WorkflowStartEvent` | `run_id`, `workflow_name`, `timestamp` | Server → Client |
| `StepStartEvent` | `run_id`, `step`, `input`, `timestamp` | Server → Client |
| `StepEndEvent` | `run_id`, `step`, `status`, `duration_ms`, `output`, `model_used`, `tokens_used`, `tier` | Server → Client |
| `StepCompleteEvent` | Same as `StepEndEvent` + `outputs` | Server → Client |
| `StepErrorEvent` | `run_id`, `step`, `error`, `duration_ms`, `model_used`, `tokens_used` | Server → Client |
| `WorkflowEndEvent` | `run_id`, `status`, `timestamp` | Server → Client |
| `ErrorEvent` | `run_id`, `error`, `timestamp` | Server → Client |
| `EvaluationStartEvent` | `run_id`, `timestamp` | Server → Client |
| `EvaluationCompleteEvent` | `run_id`, `rubric`, `overall_score`, `weighted_score`, `grade`, `passed`, `criteria[]` | Server → Client |

**Client-only events** (not from the Pydantic contract; defined by hand in `api/types.ts`):

```typescript
export type ChannelEvent =
  | { type: 'error'; run_id: string; error: string }
  | { type: 'keepalive' }
  | { type: 'connection_established'; run_id: string; message: string };
```

`ChannelEvent` events are injected by the WebSocket client itself, not by the server. The full union consumed by the application is:

```typescript
export type ExecutionEvent = WireExecutionEvent | ChannelEvent;
```

---

## Error handling patterns

### REST errors

`fetchJSON<T>` throws a plain `Error` when `response.ok` is false. TanStack Query catches this and stores it in the `error` field of the query result. Components that need error UI read `query.error?.message`.

Common error display pattern:

```
if (isLoading) return <LoadingSkeleton />
if (error) return <ErrorBanner message={error.message} />
if (!data) return <EmptyState />
```

No global toast or notification system is present. Errors are surfaced inline within each component's render path.

### WebSocket transport errors

`connectExecutionStream` passes transport errors to `onError`. `useWorkflowStream` treats an `onError` callback as a trigger for the exponential backoff reconnect loop. If the `error` event is a genuine server error (closed with an error code), the hook sets `status: 'error'` and `error: <message>`. `LivePage` renders an error banner in this case.

### React render errors

`AppErrorBoundary` (`components/states/AppErrorBoundary.tsx`) wraps the entire application tree in `main.tsx`. Uncaught render-phase errors are caught by `getDerivedStateFromError` and display an `ErrorBanner` fallback with the error message.

---

## Caching and invalidation

### Default stale-time

All queries share a 10-second `staleTime`. Within 10 seconds of a successful fetch, subscribing to the same query key from any component returns the cached data synchronously. After 10 seconds the data is considered stale and a background refetch is triggered on next subscription.

### Cache key design

| Data type | Key structure | Scope |
|---|---|---|
| Workflow list | `['workflows']` | Global |
| Workflow DAG | `['workflow-dag', name]` | Per workflow |
| Workflow editor source | `['workflow-editor', name]` | Per workflow |
| Run list | `['runs']` | Global |
| Run detail | `['run', filename]` | Per run file |
| Runs summary | `['runs-summary']` | Global |
| Run evaluation | `['run-eval', filename]` | Per run file |
| Dataset list | `['eval-datasets']` | Global |
| Dataset samples | `['dataset-samples', source, id, offset, limit]` | Per page |
| Dataset sample detail | `['dataset-sample-detail', source, id, index]` | Per sample |

### Manual invalidation

Cache invalidation occurs in one place: `WorkflowEditorPage` after a successful `saveWorkflow` mutation:

```typescript
queryClient.invalidateQueries(['workflow-dag', name])
queryClient.invalidateQueries(['workflow-editor', name])
```

This causes the DAG preview to refresh from the newly saved workflow definition.

No other mutations trigger cache invalidation. After `runWorkflow` succeeds the page navigates away to `LivePage` without invalidating `['runs']`; the run list will refresh naturally on its 5-second poll interval or on next mount.

### Polling

Only `useRuns()` uses `refetchInterval`. All other queries are fetch-on-mount with stale-time-controlled background updates. There is no global polling management or pause-on-hidden-tab logic.
