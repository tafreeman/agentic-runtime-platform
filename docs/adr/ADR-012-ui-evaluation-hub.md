# ADR-012: UI Overhaul — Evaluation Hub & A/B Comparison Interface

---

| Field          | Value |
|----------------|-------|
| **ID**         | ADR-012 |
| **Status**     | 🟡 Proposed |
| **Date**       | 2026-03-06 |
| **System**     | agentic-workflows-v2/ui |
| **Authors**    | Platform Engineering |
| **Reviewers**  | Frontend, UX |
| **Extends**    | ADR-011 (API & Interface Design) |

---

## 1. TL;DR

> **The existing EvaluationsPage is overhauled from a passive filtered table into a real
> evaluation hub with two tabs and a "Compare Agents" call-to-action. Two additive screens
> are introduced: a 2-step wizard for configuring a new comparison, and a single-page
> result view that auto-transitions from live progress to final results without navigation.
> All real-time streaming reuses `connectExecutionStream()` verbatim — no new client-side
> WebSocket infrastructure (a new server-side route handler for `/ws/eval/{run_id}` is required). Contestant configuration is inline in the wizard (no file editing).
> A visual workflow pipeline builder is identified as the logical next phase but explicitly
> deferred.**

---

## 2. Status History

| Date | Status | Note |
|------|--------|------|
| 2026-03-06 | 🟡 Proposed | Initial UI overhaul design |

---

## 3. Context & Problem Statement

### 3.1 Current UI State Audit

The existing UI has seven pages. Six are working well and unchanged; one needs an overhaul:

| Page | Route | Disposition | Reason |
|------|-------|-------------|--------|
| Dashboard | `/` | Keep — minor CTA addition | Add "Compare Agents" shortcut card |
| Workflows | `/workflows` | Keep | Workflow library — unchanged |
| Workflow Detail | `/workflows/:name` | Keep | DAG + step detail — unchanged |
| Datasets | `/datasets` | Keep | Dataset browser — unchanged |
| **Evaluations** | `/evaluations` | **Overhaul as hub** | Currently thin: only filters runs by score |
| Run Detail | `/runs/:filename` | Keep | Step log viewer — unchanged |
| Live | `/live/:runId` | Keep | Proven WebSocket real-time pattern to reuse |

**EvaluationsPage — current state:**
```
/evaluations (current)
┌──────────────────────────────────────────────────────┐
│  Evaluations                                         │
│                                                      │
│  Workflow | Score | Grade | Steps | Date | Details   │
│  (filtered list: runs where evaluation_score != null)│
│                                                      │
│  No entry point to run a new evaluation.             │
│  No comparison capability or comparison history.     │
│  No A/B results. Passive observer only.              │
└──────────────────────────────────────────────────────┘
```

> **Note:** The "no entry point" observation applies specifically to `EvaluationsPage.tsx`.
> `WorkflowDetailPage.tsx` already has an evaluation entry point via `RunConfigForm`, which
> supports evaluation dataset selection, rubric selection, and multi-sample batch runs.
> The gap is that `EvaluationsPage` — the page whose purpose is evaluations — lacks any
> entry point to initiate one.

This page is a passive read-only table. It provides no user action and is not an
evaluation hub.

### 3.2 UX Requirements

The eval harness (ADR-010/011) introduces a primary user action: **start and observe an
A/B comparison**. That action has no home in the current UI:

```
┌─────────────────────────────────────────────────────────────────┐
│  UX REQUIREMENTS FOR THE EVAL HARNESS UI                        │
├─────────────────────────────────────────────────────────────────┤
│  R1 │ Start a new A/B comparison from the browser               │
│  R2 │ Observe live progress during a 30-120 min comparison      │
│  R3 │ See results on the same page — no navigation disruption   │
│  R4 │ Configure contestants inline — no terminal or file edit   │
│  R5 │ Browse comparison history alongside scored workflow runs   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 Real-Time Infrastructure Assessment

The existing WebSocket infrastructure is proven stable in production:

```typescript
// api/websocket.ts — connectExecutionStream()
// Deployed: stable for 30–60 minute workflow runs in LivePage
// Auto-reconnect: 5 retries, exponential backoff (retryDelayMs × 2^(retryCount-1) → 1s, 2s, 4s, 8s, 16s)
// pathPrefix option: pass pathPrefix="eval" to reach /ws/eval/{runId} — no new function needed
// Used by: useWorkflowStream.ts → LivePage.tsx
```

This is production infrastructure. The eval feature reuses it by passing `pathPrefix: "eval"`
to `connectExecutionStream()` — zero new client-side WebSocket code required.
`useEvalStream.ts` mirrors `useWorkflowStream.ts` structurally with eval-specific
event types — the only difference is the shape of the state object.

---

## 4. Decision

### 4.1 EvaluationsPage → Evaluation Hub (tab extension)

**Change principle: additive only.** The existing "Scored Runs" table is unchanged in
content and styling. A tab selector and "Compare Agents" button are added above it.

```
/evaluations — overhauled
┌──────────────────────────────────────────────────────────┐
│  Evaluations                    [Compare Agents →]       │
│                                                          │
│  [Scored Runs]   [Comparisons]  ← tab toggle             │
│                                                          │
│  Scored Runs tab:                                        │
│  Workflow │ Score │ Grade │ Steps │ Date │ Details       │
│  (existing table — content, sorting, and styling intact) │
│                                                          │
│  Comparisons tab:                                        │
│  Commit  │ A vs B           │ Winner │ Margin │ Date │ ▶ │
│  abc123  │ workflow vs prompt│  A    │ +1.4   │ Mar 6│ ▶ │
│  def456  │ agent vs agent   │  tie  │  0.0   │ Mar 5│ ▶ │
└──────────────────────────────────────────────────────────┘
```

### 4.2 Compare Wizard — 2 Steps, One Decision Per Step

Rationale: GOV.UK Design System's "one thing per page" pattern, validated through lab
testing on Register to vote and GOV.UK Verify (design-system.service.gov.uk). Each step
focuses attention on a single decision and validates before advancing.

**Step 1 — Commit** (2 fields, immediate feedback):
```
Step 1 of 2: Select Commit
┌────────────────────────────────────────────┐
│                                            │
│  Repository path                           │
│  ┌──────────────────────────────────────┐  │
│  │ /path/to/repo                        │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  Commit SHA           [HEAD~1 shortcut]    │
│  ┌──────────────────────────────────────┐  │
│  │ abc123def                            │  │
│  └──────────────────────────────────────┘  │
│  Commit validated: "fix: resolve edge ..." │
│                                            │
│                              [Next →]      │
└────────────────────────────────────────────┘
```

Validation on "Next": send `POST /eval/validate-commit` — verifies repo path is accessible
and commit SHA resolves. Inline commit summary shown on success.

**Step 2 — Contestants** (inline config expands by type):
```
Step 2 of 2: Configure Contestants
┌────────────────────────────────────────────┐
│                                            │
│  Contestant A                              │
│  [workflow] [prompt] [agent]  ← pill tabs  │
│                                            │
│  -- if workflow: --                        │
│  Workflow:  [code_review ▼]               │
│  Model override: [default ▼]             │
│                                            │
│  -- if prompt: --                          │
│  ┌────────────────────────────────────┐    │
│  │ You are an expert Python developer │    │
│  │ specializing in ...               │    │
│  └────────────────────────────────────┘    │
│  Model: [claude-sonnet-4-6 ▼]            │
│  Temperature: [===●=====] 0.7            │
│                                            │
│  -- if agent: --                           │
│  Class: [ClaudeAgent     ] Model: [▼]    │
│  System prompt: [optional override...]    │
│                                            │
│  Contestant B  [workflow] [prompt] [agent] │
│  (same expanded form for B)               │
│                                            │
│  Rubric: [coding_standards ▼]             │
│                                            │
│  [← Back]            [Run Comparison]     │
└────────────────────────────────────────────┘
```

On submit: `POST /eval/compare` → navigate to `/evaluations/compare/{run_id}`.

> **Existing API surface:** A partial eval API already exists — `api/client.ts:64` defines
> `listEvaluationDatasets()` calling `GET /api/eval/datasets`. The proposed endpoints
> (`POST /eval/validate-commit`, `POST /eval/compare`) are additive to this existing
> `/eval/` namespace.

### 4.3 Comparison Run Page — Single Page, Two States

**Design principle**: GitHub Actions / Vercel deployment pattern — progress and result
on the same URL. No navigation disruption during a long-running job.

**State 1 — Running** (WebSocket connected, live event-driven updates):
```
/evaluations/compare/{run_id}  (state: running)
┌──────────────────────────────────────────────┐
│ ← Back   abc123...           ◉ running       │
│                                              │
│ ✅  Extract requirements       done   3.2s  │
│ ◉   Run Contestant A          running  48s  │
│ ○   Run Contestant B          waiting       │
│ ○   Score & generate report   waiting       │
│                                              │
│ ┌────────────────────────────────────────┐   │
│ │ Contestant A: code_review              │   │
│ │ type: workflow · claude-sonnet-4-6     │   │
│ │ 14 files modified                      │   │
│ └────────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

**State 2 — Complete** (auto-transition in place, same URL, no navigation):
```
/evaluations/compare/{run_id}  (state: complete)
┌──────────────────────────────────────────────┐
│ ← Back   abc123...           ✅ complete     │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │  A WINS   +1.4 points               │    │
│  │  code_review outscores experimental  │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  Dimension       A          B                │
│  completeness    ████████░  ██████░░░        │
│  correctness     ███████░░  █████████        │
│  quality         ████████░  ███████░░        │
│  specificity     ███████░░  ██████░░░        │
│  alignment       █████████  ███████░░        │
│  Rubric (0.0–1.0)  0.783      0.614          │
│                                              │
│  Tests    A: 12/14 ✅    B: 9/14 ✅          │
│                                              │
│  [▶ Show patch diff]                        │
│  [↓ HTML report]   [↓ Markdown report]      │
└──────────────────────────────────────────────┘
```

The page does not navigate to a new route. The `useEvalStream` hook drives a state
transition from `status: "running"` to `status: "complete"`, and the JSX conditionally
renders the progress tracker or the result view.

### 4.4 Real-Time Hook (`useEvalStream.ts`)

Mirrors `useWorkflowStream.ts` with eval-specific event types:

```typescript
type EvalEvent =
  | { type: "eval_start";    run_id: string }
  | { type: "phase_start";   phase: "extract" | "run_a" | "run_b" | "score" }
  | { type: "phase_end";     phase: string; status: "done" | "error"; elapsed_ms: number }
  | { type: "eval_complete"; winner: "A" | "B" | "tie"; score_a: number;
      score_b: number; result: ComparisonResult }
  | { type: "error";         message: string }

interface EvalStreamState {
  phases: Record<string, "waiting" | "running" | "done" | "error">;
  status: "connecting" | "running" | "complete" | "error";
  result: ComparisonResult | null;
  error: string | null;
}

export function useEvalStream(runId: string | null): EvalStreamState {
  // Mirrors useWorkflowStream.ts exactly — four independent useState calls, no useReducer:
  const [phases, setPhases] = useState<EvalStreamState["phases"]>({});
  const [status, setStatus] = useState<EvalStreamState["status"]>("connecting");
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    const stream = connectExecutionStream(runId, (event) => {
      // dispatch on event.type → call appropriate setter
    }, { pathPrefix: "eval" });
    return () => stream.close();
  }, [runId]);

  return { phases, status, result, error };
}
```

WebSocket URL: `ws://host/ws/eval/{run_id}` — reached via `pathPrefix: "eval"` option; same
host, no new client-side WebSocket infrastructure required.

### 4.5 New Files

| File | Lines (est.) | Purpose |
|------|-------------|---------|
| `pages/eval/NewComparisonPage.tsx` | 140 | 2-step wizard page (`/evaluations/compare/new`) |
| `pages/eval/ComparisonRunPage.tsx` | 170 | Progress + result, 2 states (`/evaluations/compare/:id`) |
| `components/eval/ComparisonWizard.tsx` | 100 | Wizard step logic + validation state |
| `components/eval/ContestantConfig.tsx` | 70 | Type pill toggle + ref input (used for A and B) |
| `components/eval/ContestantPropertiesForm.tsx` | 90 | Expands fields by type (workflow/prompt/agent) |
| `components/eval/EvalProgressTracker.tsx` | 80 | 4-step linear progress indicator |
| `components/eval/ComparisonResultView.tsx` | 130 | Winner banner + dimension bars + test summary |
| `components/eval/PatchDiff.tsx` | 80 | Collapsible side-by-side unified diff viewer |
| `hooks/useEvalStream.ts` | 70 | WebSocket hook (mirrors `useWorkflowStream`) |
| `api/eval.ts` | 50 | Typed `fetch` wrappers for eval REST endpoints |

### 4.6 Modified Files

| File | Change |
|------|--------|
| `pages/EvaluationsPage.tsx` | Add "Compare Agents →" CTA button + Comparisons tab |
| `App.tsx` | Add routes: `/evaluations/compare/new`, `/evaluations/compare/:id` |

**Sidebar**: unchanged. The Evaluations link already exists in the nav. Comparison
features live under `/evaluations/*` — no new nav item required.

### 4.7 Long-Term Roadmap — In-App Workflow Pipeline Builder

Visual drag-and-drop creation and editing of workflow YAML files. React Flow is
already installed and used in `WorkflowDAG.tsx`. This is deferred to a future phase.

**Deferral rationale:** The eval harness is a prerequisite for knowing which workflow
patterns perform well. It would be premature to build a pipeline authoring UI before
having data on what effective pipelines look like.

**Future location:** `/workflows/new` and `/workflows/:name/edit`

```
Future — two editing modes (toggle):
  Visual: React Flow DAG → drag steps → configure → export YAML
  YAML:   Monaco/CodeMirror editor with JSON schema validation
  Bidirectional sync: edit graph ↔ edit YAML (consistent state)

Future backend needed:
  POST /workflows         → save new YAML to workflows/definitions/
  PUT  /workflows/:name   → update existing definition
  GET  /workflows/:name/schema → JSON schema for editor validation
```

---

## 5. Rationale

### 5.1 Two-Step Wizard over Single Long Form

Nielsen Norman Group's research on form usability (nngroup.com) establishes that wizards
"dynamically display relevant fields based on users' prior input" and "minimize the physical
effort required to fill out the form and save users from spending attentional resources to
scan and filter irrelevant questions."

The key dependency in this form: Step 2 (contestant configuration) requires knowing the
repo path from Step 1 in order to populate the workflow dropdown from `GET /workflows`.
This dependency makes a strict two-step split natural — not merely cosmetic.

| Factor | 2-Step Wizard | Single Long Form |
|--------|--------------|------------------|
| Cognitive load per screen | One decision area | All decisions simultaneously |
| Validation feedback | Per-step, immediate (commit validated on "Next") | At submit — ambiguous which field failed |
| Progressive disclosure | Contestant config expands based on type selected | All possible fields visible simultaneously |
| Error recovery | Back button goes to specific failing step | Start over from top |
| Mobile / narrow viewport | One focused section per screen | Vertical scrolling required |
| Step dependency handling | Step 2 receives validated Step 1 data | Must pass validated data down within one form |

### 5.2 Single-Page Progress → Result (same URL, no navigation)

| Factor | Single Page (auto-transition) | Separate Result Route |
|--------|------------------------------|----------------------|
| Navigation disruption | None — transitions in place during live run | User leaves progress URL mid-operation |
| Deep-linkable | Yes — `/evaluations/compare/{id}` shows current state | Requires two bookmarkable URLs |
| WebSocket lifecycle | Single connection, no reconnect on navigate | New connection required on route change |
| Back button behavior | Clear — goes back to /evaluations | Ambiguous — which "back" goes where? |
| Share URL semantics | One URL shows the current state of any run | Two URLs for two "phases" of one run |

Precedents: GitHub Actions workflow run page and Vercel deployment status page both
use this pattern. A single URL serves both the in-progress log and the final result.
Users can bookmark, share, or return to a URL and see the current state — running
or complete — without confusion.

### 5.3 Inline Contestant Configuration

Without inline config, the workflow to set up a `prompt` contestant is:

1. Open terminal → write prompt text to a `.md` file
2. Note the file path
3. Return to browser → paste file path into the wizard
4. If the prompt changes: repeat steps 1–3

With inline config (textarea for `prompt` type), this collapses to typing the prompt
directly into the wizard. The `workflow` type gets a dropdown populated from `GET /workflows`.
The `agent` type gets a class name input. No file editing, no terminal context-switching.

This is the same design principle used by OpenAI Playground and PromptLayer: reduce
the friction between "I have an idea for a prompt" and "I can evaluate it."

### 5.4 Design Token Consistency

All new components must use the existing design token set:

| Token | Purpose |
|-------|---------|
| `bg-surface-1`, `bg-surface-2` | Card and panel backgrounds |
| `bg-accent-blue/10`, `text-accent-blue` | Active state, links |
| `border-white/5` | Subtle borders |
| `text-gray-400`, `text-gray-500`, `text-gray-600` | Secondary text hierarchy |
| `btn-ghost` | Ghost button variant (Back, Cancel) |
| `tabular-nums` | Score display, counters |

No new Tailwind classes. The comparison result dimension bars use the same
`bg-green-500` / `bg-amber-500` / `bg-red-500` pattern established in `CriterionRow`
in `LivePage.tsx`.

> **Known defect:** `bg-surface-hover` is used in the current `EvaluationsPage.tsx:60` but
> is NOT defined in `tailwind.config.js` or `globals.css`. Tailwind JIT silently drops
> undefined classes, so `bg-surface-hover` produces no styles. Implementers studying the
> existing page for token precedents should be aware of this phantom token and avoid
> replicating it.

### 5.5 Production Precedents for This UI Pattern

| Pattern | Precedent | Applied In |
|---------|-----------|-----------|
| Evaluation hub with tabs | DORA Dashboard (deploy frequency, failure rate, etc.) | Scored Runs + Comparisons tabs |
| Wizard for parameterized job setup | GitHub Actions `workflow_dispatch` input form | 2-step Compare Wizard |
| Single-page progress → result auto-transition | GitHub Actions run page, Vercel deploy status | ComparisonRunPage 2 states |
| Dimension-per-row bar chart | SWE-bench leaderboard, HELM benchmark results | ComparisonResultView dimension bars |
| Inline prompt config in UI | OpenAI Playground, PromptLayer | ContestantPropertiesForm for prompt type |
| Wizard step validation before advance | Multi-step checkout (Stripe, Shopify) | Step 1 commit validation before Step 2 |

---

## 6. Consequences

### 6.1 Positive Outcomes

| Outcome | Mechanism |
|---------|-----------|
| No file editing to run a comparison | Inline contestant config in wizard |
| Live feedback for 30–120 min evals | WebSocket progress events via `useEvalStream` |
| Comparison history browsable with scored runs | Two-tab EvaluationsPage hub |
| No new *client-side* WebSocket infrastructure | `connectExecutionStream()` called with `pathPrefix: "eval"` — reaches `/ws/eval/{run_id}` with zero new client code. **Note:** a new server-side WebSocket route handler for `/ws/eval/{run_id}` must be written — the server currently only registers `/ws/execution/{run_id}` |
| Six of seven pages untouched | Only EvaluationsPage modified; all routes additive |

### 6.2 Trade-offs and Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Wizard Step 1 validation requires network round-trip | Medium | Client validates path format locally; server validates SHA; debounced on blur |
| WebSocket keepalive needed for 2+ hour eval runs at load balancer | Medium | Server sends JSON keepalive ping every 30s; client reconnect absorbs any drops |
| `prompt_text` in wizard may be large (tens of KB) | Low | Frontend limits textarea to 16KB; documented as constraint |
| Comparisons tab empty state needs guidance copy | Low | Empty state component with "No comparisons yet — click Compare Agents" |
| Future pipeline builder (React Flow visual editor) has substantial scope | Low | Explicitly deferred; documented in roadmap section |

---

## 7. Alternatives Considered

| Alternative | Rejected Because |
|-------------|-----------------|
| **Separate `/compare` top-level section in sidebar** | Discoverability: users expect eval features under Evaluations; adds a 6th nav item without justification |
| **Full-page modal for the wizard** | No deep-link URL for in-progress comparison; back button behavior undefined inside modal; route-based navigation is cleaner |
| **SSE for progress stream** | Creates a second streaming protocol; diverges from the proven `connectExecutionStream()` WebSocket infrastructure (also ADR-011 §6.2) |
| **promptfoo web UI for comparison setup** | Node.js dependency stack; no native integration with Python/FastAPI backend; no private-commit support; introduces a second UI framework |
| **React Query polling (no WebSocket)** | 30–120 min runs require hundreds of polling requests; no push semantics; latency between completion and display |
| **Separate progress URL + separate result URL** | Navigation disruption during live run; bookmark semantics are ambiguous; WebSocket lifecycle breaks on navigate |
| **Build pipeline editor now (not deferred)** | Eval harness should produce evidence of which workflow patterns work before committing to a pipeline authoring UI; React Flow visual editor scope is large |

---

## 8. References

| Citation | Relevance |
|----------|-----------|
| Nielsen Norman Group — **4 Principles to Reduce Cognitive Load in Forms** (nngroup.com) | Wizard pattern justification; progressive disclosure; one-focus-per-screen |
| Nielsen Norman Group — **Wizards: Definition and Design Recommendations** (nngroup.com/articles/wizards/) | Source for §5.1 quote: "dynamically display relevant fields based on users' prior input" |
| GOV.UK Design System — **Question pages: One thing per page** (design-system.service.gov.uk) | Validated through lab testing on Register to vote and GOV.UK Verify; starting pattern for multi-step flows |
| Smashing Magazine — **Better Form Design: One Thing Per Page** (smashingmagazine.com, 2017) | User research: single-question pages reduce errors and improve completion rates |
| GitHub Actions — workflow run page (github.com) | Single-URL progress → result auto-transition pattern |
| Vercel — deployment status page (vercel.com) | Same-URL live-to-complete state transition precedent |
| DORA State of DevOps 2024 — Dashboard design | Multi-metric tab panel inspiration for Evaluations hub |
| SWE-bench web results viewer (swebench.com) | Dimension-per-row score bar display inspiration |
| `api/websocket.ts:connectExecutionStream()` | Existing WebSocket client infrastructure — reused verbatim |
| `hooks/useWorkflowStream.ts` | Existing WebSocket React hook — mirrored for eval event types |
| `pages/LivePage.tsx` | Proven single-page real-time display; `CriterionRow` bar chart pattern |
| React Flow documentation — `@xyflow/react` (reactflow.dev) | Visual builder option for future pipeline editor phase (React Flow v12 publishes under the `@xyflow` org) |

---

## 9. Decision Map

```
┌──────────────────────────────────────────────────────────────────────┐
│  ADR-012 DECISION MAP                                                │
│                                                                      │
│  EvaluationsPage Disposition                                         │
│    ├── Leave as-is (passive filtered table) ─────── REJECTED         │
│    ├── Replace with comparison-only view ────────── REJECTED         │
│    └── Tab extension: hub + CTA + Comparisons ───── CHOSEN           │
│                                                                      │
│  Comparison Setup UX                                                 │
│    ├── Single long form (all fields) ────────────── REJECTED         │
│    ├── Full-page modal ──────────────────────────── REJECTED         │
│    └── 2-step wizard (one decision per screen) ──── CHOSEN           │
│                                                                      │
│  Progress and Result Display                                         │
│    ├── Separate progress route + separate result ── REJECTED         │
│    └── Single route, auto-transition in place ────── CHOSEN          │
│                                                                      │
│  Real-Time Streaming                                                 │
│    ├── React Query polling ──────────────────────── REJECTED         │
│    ├── SSE ──────────────────────────────────────── REJECTED         │
│    └── Reuse connectExecutionStream() (WebSocket) ── CHOSEN          │
│                                                                      │
│  Contestant Configuration                                            │
│    ├── File path only (user edits files in terminal) REJECTED        │
│    └── Inline in wizard (textarea/dropdown/inputs) ── CHOSEN         │
│                                                                      │
│  Workflow Pipeline Builder                                           │
│    ├── Build now (React Flow visual editor) ─────── DEFERRED         │
│    └── Flag in roadmap — post eval harness data ──── CURRENT SCOPE  │
└──────────────────────────────────────────────────────────────────────┘
```
