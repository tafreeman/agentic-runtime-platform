# ARP Evidence Ledger UI Full-Rewrite Goal Prompt

Copy everything below the `BEGIN PROMPT` marker into a fresh GPT/Codex task.

---

## BEGIN PROMPT

You are the principal product designer and staff frontend/platform engineer responsible for a complete, production-quality rewrite of the Agentic Runtime Platform (ARP) web UI.

Work in:

`C:\Users\tandf\source\agentic-runtime-platform`

This is an implementation goal, not a design critique or a mockup-only exercise. Continue until the rewritten UI, required supporting contracts, tests, documentation, and verification evidence are complete. Do not stop after producing a plan.

### Start the goal

At the start of the task, call the goal-creation mechanism with this objective and no artificial token budget:

> Rewrite the complete ARP web UI around the Evidence Ledger design system, preserving proven runtime behavior, refining every current page, adding the explicitly scoped model-routing and usability capabilities, and verifying the result end to end.

Then maintain a concrete working plan with exactly one step in progress at a time. Give the user concise progress updates at meaningful milestones and at least once every 60 seconds during long-running work.

## 1. Required outcome

Replace the current terminal/Carbon-style UI with one coherent Evidence Ledger application system based on the implemented prototype at:

- `agentic-workflows-v2/ui/src/pages/PrototypeLabPage.tsx`
- `agentic-workflows-v2/ui/src/styles/prototype-lab.css`
- route: `/prototypes`, concept `02 Evidence ledger`

The prototype is visual direction, not production architecture and not a source of real data. Do not copy its mock records, fixed measurements, or nonfunctional controls into production.

The finished product must:

1. Preserve all working user-visible capabilities that exist in the current UI unless this prompt explicitly consolidates or removes them.
2. Make evaluation evidence, run provenance, workflow configuration, and model routing easier to understand and operate.
3. Preserve the Evidence Ledger prototype's airy, editorial aesthetic while presenting operational data efficiently; density must come from hierarchy and progressive disclosure, not cramped spacing.
4. Connect the Model Router to run launch and workflow authoring through reusable named model packs.
5. Remain usable with keyboard, screen reader, reduced motion, narrow laptop, tablet, and mobile layouts.
6. Use real backend data and explicit empty/loading/error/partial-data states. Never ship decorative fake metrics or controls with no behavior.
7. Leave the repository in a buildable, tested, documented state.
8. Use shadcn/ui as the owned component foundation, customized to the Evidence Ledger system rather than retaining shadcn's default visual appearance.

## 2. Authority and boundaries

Retain React and Vite, and adopt shadcn/ui as the component foundation. You may change the routing approach, state/query libraries, styling organization, visualization libraries, and UI folder organization if the change is justified by evidence and completed end to end. Keep React Flow unless a replacement materially improves ARP's DAG editing and is migrated completely.

You may make focused backend changes when a required UI capability needs a new or corrected API, persistence contract, event, pagination contract, or provenance field. Keep those changes within ARP package boundaries and update tests, generated types, ADRs, and documentation.

Do not:

- rewrite the Python execution engine merely to simplify frontend code;
- change public runtime semantics without an explicit compatibility analysis;
- introduce cross-package imports without reviewing `docs/ARCHITECTURE.md` and relevant ADRs;
- store provider secrets, raw API keys, or tokens in the browser, UI settings JSON, logs, screenshots, fixtures, or git;
- replace stable API behavior with client-only approximations;
- silently discard keyboard navigation, CLI parity, focus management, deep links, WebSocket reconnection, or reduced-motion support;
- commit, push, open a PR, or modify unrelated user files unless separately instructed;
- overwrite the existing untracked user files `.agentic_model_rankings.json` or `ai-firstify-assessment-report.md`;
- treat stale documentation as more authoritative than current code, tests, generated schemas, and runtime behavior.

## 3. Evidence-first discovery

Before changing code, inspect and reconcile:

- root `AGENTS.md` and repository instructions;
- `agentic-workflows-v2/ui/src/App.tsx`;
- every file under `agentic-workflows-v2/ui/src/pages/`;
- shared components under `ui/src/components/`;
- hooks under `ui/src/hooks/`;
- `ui/src/api/client.ts`, `ui/src/api/types.ts`, and generated API types;
- UI unit and Playwright tests;
- current server routes and the live OpenAPI document;
- `docs/architecture-ui.md`, `docs/component-inventory-ui.md`, `docs/ui/`, and relevant ADRs, especially ADR-012, ADR-014, ADR-043, and any superseding ADRs;
- current git status and all user changes.

Create and maintain a route/capability matrix with these columns:

| Route/surface | Current behavior confirmed in code | Preserve | Refine | New contract needed | Explicitly excluded | Verification |

Do not implement from the inventory below blindly. Verify it against the current branch because the repository may have changed.

## 4. Frontend architecture decision gate

The target foundation is React, Vite, TypeScript, and shadcn/ui. The current UI also uses React Router, TanStack Query, Tailwind, React Flow, Vitest, and Playwright. Preserve the working libraries unless replacement has a demonstrated product or engineering benefit.

Install shadcn/ui through its official project-compatible setup and commit the selected component source into the repository. Treat those components as owned code. Configure aliases and CSS variables consistently with the project. Add only components that are actually used.

Likely shadcn primitives include Button, Input, Textarea, Select, Checkbox, Switch, Tabs, Table, Badge, Tooltip, Popover, Dropdown Menu, Command, Dialog, Alert Dialog, Sheet, Drawer, Scroll Area, Separator, Skeleton, Collapsible, Accordion, Form, and an accessible toast system. This is not a mandatory component checklist; omit anything without a real use.

Do not ship the default shadcn visual language unchanged. Restyle its tokens, radius, density, typography, focus, borders, tables, dialogs, and states to match Evidence Ledger. Give shadcn components more breathing room than their compact defaults. Avoid pill-heavy layouts, excessive rounded cards, crowded toolbars, dark control-room styling, and generic dashboard examples.

Before replacing any major current library, write a short decision record comparing it with the proposed replacement against:

- real-time WebSocket state and reconnection;
- complex DAG editing and canvas performance;
- accessible data tables, inspectors, drawers, and forms;
- type sharing with FastAPI/OpenAPI;
- unit, component, and browser testing;
- incremental migration risk;
- bundle size and route-level code splitting;
- long-term maintenance and ecosystem maturity;
- Windows developer experience and existing build commands;
- ability to preserve deep links and current API contracts.

For shadcn/ui and any major new dependency, verify current official documentation and compatible versions from primary sources. Record material architectural changes in an ADR, provide a migration map, and remove abandoned libraries cleanly. Do not run two competing component systems indefinitely. Novelty is not a benefit.

## 5. Evidence Ledger design system

The canonical design-system specification is:

`docs/ui/evidence-ledger-design-system.md`

Read it completely before implementing UI changes. Its tokens, composition rules, shadcn standards, ARP-specific patterns, responsive behavior, accessibility requirements, anti-patterns, and visual acceptance checklist are authoritative. If this prompt's summary conflicts with that file, the standalone design-system file wins.

### 5.1 Visual thesis

ARP should feel like an engineering evidence desk: editorial clarity, warm paper-like surfaces, crisp ink, restrained safety orange, calm quantitative typography, generous negative space, and precise hairline dividers. The airiness of the Evidence Ledger prototype is a core product quality, not optional polish. It should communicate rigor without looking bureaucratic, cluttered, cramped, dark, or like a generic SaaS dashboard.

Preserve the prototype's visual rhythm:

- broad breathing room around page titles and major evidence bands;
- generous row padding and clearly separated information groups;
- large, calm, light surfaces with minimal ornamental chrome;
- thin rules instead of boxed containers wherever structure remains clear;
- short line lengths for explanatory copy;
- only a small number of decisive controls in the primary view;
- orange used sparingly for action, selection, or the most important comparison;
- typography and whitespace carrying hierarchy before backgrounds, borders, or shadows.

### 5.2 Interaction thesis

Use three consistent interaction patterns:

1. Master-detail selection: rows remain visible while a right inspector reveals evidence or configuration.
2. Progressive disclosure: common actions remain in the primary workspace; advanced runtime, evaluation, and routing controls live in drawers or expandable sections.
3. Stable context transitions: shared-layout or short fade/slide transitions clarify selection and navigation without delaying work.

Respect `prefers-reduced-motion`. Motion must explain state or hierarchy, never decorate routine operations.

### 5.3 Core tokens

Create semantic tokens rather than page-local color values. At minimum define:

- canvas, primary surface, raised surface, hover surface;
- primary ink, secondary ink, muted ink, disabled ink;
- primary divider, soft divider, strong divider;
- action/accent orange, action hover, action soft background;
- success, warning, danger, information, running, and neutral states;
- focus ring, selection rail, chart series, graph node/edge states;
- typography, spacing, radius, shadow, z-index, density, and motion scales.

Evidence Ledger is unequivocally light-first. Warm paper, off-white, and pale neutral surfaces define the product. Dark mode is optional and must not delay or compromise the light system; if retained, it is a secondary preference rather than the brand default. Never use dark panels as the normal page structure. Any supported theme must meet WCAG 2.2 AA contrast for essential text and controls.

### 5.4 Typography

Use no more than two type families:

- a highly legible UI sans for navigation, controls, tables, and body text;
- an editorial display face or system serif only for major page titles and high-level evidence scores.

Use tabular numerals for scores, durations, tokens, costs, and counts. Use monospace only for identifiers, code, YAML, CLI commands, events, and technical provenance—not for all interface copy.

### 5.5 Layout system

Use a consistent, spacious application frame:

- global product navigation;
- primary work surface;
- optional secondary inspector;
- one clear primary action per page;
- contextual filters attached to the data they affect;
- intentional negative space between primary sections so the interface never reads as one continuous control panel.

Organize navigation into four product areas:

- **Observe:** Overview, Runs, Live execution.
- **Build:** Workflows, Datasets.
- **Evaluate:** Evaluations.
- **Configure:** Model Router.

Do not devote persistent navigation space to a page with no unique purpose. Provider and tier settings belong inside Model Router. Retire the current standalone Settings navigation item; preserve `/settings` as a redirect to the relevant Model Router subview unless genuinely independent settings are implemented.

### 5.6 Airiness, density, and space rules

- Design desktop-first at 1440×900, validate at 1280×720 and 1024×768, and provide intentional behavior at 390×844.
- Persistent global chrome should normally consume no more than 56 px vertically and 220 px horizontally when expanded.
- Standard page heading/action bands should normally fit within 72 px.
- The first viewport must contain the primary working surface, not an oversized hero, while retaining enough whitespace that the surface does not feel compressed.
- Prefer tables, split panes, scorelines, timelines, and plain sections over card mosaics.
- Use cards only when the boundary is interactive or groups one discrete object.
- Default to comfortable density. A compact density may be offered for expert users, but it must not define the visual baseline.
- Use approximately 24–40 px page gutters on desktop, 24–32 px between major sections, 14–20 px inside interactive rows, and at least 8 px between label/value groups unless a specialized canvas requires otherwise.
- Do not fill empty space merely because it exists. Remove low-value controls or move them into an inspector, menu, or advanced section.
- Prefer one visually dominant table, graph, or evidence band per viewport over several equally weighted panels.
- Hide secondary columns responsively before shrinking essential text below readable sizes.
- On mobile, convert inspectors to full-height sheets and data tables to prioritized rows/details; do not force an unusable desktop canvas into 390 px.

### 5.7 Utility copy

Use operational labels such as “Recent runs,” “Provider health,” “Selected rubric,” “Routing order,” and “Last evaluation.” Do not add marketing headlines or abstract metaphors to working pages.

## 6. Global application behaviors

Preserve and refine:

- skip-to-content and route-change focus management;
- keyboard navigation and discoverable shortcuts;
- global command palette;
- CLI parity/command preview where the action has a real CLI twin;
- backend health and no-LLM-mode visibility;
- WebSocket reconnect status;
- theme preference;
- responsive navigation;
- consistent loading, empty, stale, partial, offline, permission, and error states;
- copyable run/model/workflow identifiers;
- stable deep-link URLs;
- error boundaries and not-found recovery;
- query caching and targeted invalidation;
- safe optimistic UI only where rollback is deterministic.

Add a unified toast/notification policy for successful mutations and recoverable errors. Destructive actions require clear confirmation and consequences. Never use browser `alert`/`confirm` as the final production interaction.

## 7. Page-by-page capability plan

### 7.1 Overview — `/`

#### Current behavior to preserve

- total runs, success rate, 30-day tokens, and active-run counts from real APIs;
- recent runs with workflow, status, score/grade, and deep links;
- configured/probed model summary;
- workflow quick access;
- run filtering and new-run navigation;
- backend status, cold-start skeletons, retryable partial errors, and first-run guidance.

#### Rewrite and refinement

- Use a compact Evidence Ledger scoreline instead of three equal statistic cards.
- Show run health, evaluation readiness, latency, token/cost trend when backed by data, and active failures requiring attention.
- Provide a dense recent-runs table as the main surface and a narrow “attention” rail for failed/stalled runs, unavailable providers, or failed evaluations.
- Link every aggregate to its filtered source view.
- Show freshness/source metadata for metrics.
- Keep “Start run” as the single primary action.

#### Space budget

- heading/actions: ≤72 px;
- scoreline/trend band: approximately 150–180 px;
- remaining first viewport: recent runs plus attention rail;
- no more than five primary metrics above the fold.

#### Exclude

- fake executive summaries;
- decorative charts without decision value;
- a card per workflow or model above the fold;
- billing analytics unless the backend has trustworthy cost data.

### 7.2 Runs index — `/runs`

#### Current behavior to preserve

- total/passing/failed/average-duration summary;
- current 50-row window disclosure;
- status, workflow, and text filters;
- optional live-tail polling;
- searchable workflow/run IDs;
- keyboard `j`/`k`, Enter-to-inspect, Escape-to-close;
- master-detail inspector;
- copyable identifiers, workflow/run deep links, step counts, score/grade, duration, and relative time;
- stale-data display with retry;
- trigger-run action and CLI parity.

#### Rewrite and refinement

- Use a real data table with sortable columns and a sticky header.
- Add server-backed pagination/cursor loading before claiming access to more than the current API limit.
- Add filters for date/time, evaluation state/grade, model/provider, dataset, execution profile, and routing pack only when backend fields exist.
- Encode filter/sort state in the URL for sharing and return navigation.
- Make selected-run inspector width resizable on desktop and a sheet on narrow screens.
- Allow export of the current filtered view only through a bounded, escaped CSV/JSON contract.
- Clearly distinguish running, queued, cancelled, failed, partial, and completed states.

#### Space budget

- summary and filters together: ≤170 px;
- table owns the rest of the viewport;
- when inspector opens, retain at least run ID, workflow, status, and duration columns.

#### Exclude

- infinite polling while the tab is hidden;
- fabricated span/route columns;
- client-only pagination over an undisclosed 50-row subset;
- bulk destructive run deletion unless retention APIs and authorization exist.

### 7.3 Run detail — `/runs/:filename`

#### Current behavior to preserve

- full run metadata and status;
- workflow DAG with step status, edge traversal counts, and kickback edges;
- step selection and input/output details;
- Spans and YAML/source views;
- evaluation summary and detailed rubric accordion;
- objective, judge, and advisory layers;
- judge-skipped reason, expected-text warning, hard gates, floor violations, and gate failures;
- captured-input replay with required-input safety check;
- CLI parity and back navigation.

#### Rewrite and refinement

- Make the evidence record the primary structure: Overview, Trace, Inputs/Outputs, Evaluation, Provenance.
- Show immutable run identity, timestamps, workflow revision, model/provider actually used, routing pack/version, fallback path, dataset/sample, rubric/version, execution profile, token/cost/latency totals, and environment fingerprint when available.
- Show requested model/tier separately from resolved model and fallback reason.
- Make step selection synchronize between DAG, trace timeline, and inspector.
- Add downloadable evidence only for real server artifacts.
- When evaluation reasoning/evidence is not present in the typed backend contract, add the contract and tests or show it as unavailable; never invent it.

#### Space budget

- compact identity header: ≤92 px;
- primary tab row: ≤42 px;
- DAG/trace plus inspector fills remaining viewport;
- large JSON/YAML/output content gets dedicated scroll regions, not expanding the entire page.

#### Exclude

- editing a completed run;
- mutating recorded provenance;
- replaying when required captured inputs are missing;
- presenting re-evaluation as original-run evidence without a new evaluation timestamp/version.

### 7.4 Live execution — `/live/:runId` and `/live/latest`

#### Current behavior to preserve

- WebSocket event stream with bounded exponential reconnect;
- workflow inference and DAG load;
- real-time step states, edge counts, kickback edges, and active-step auto-selection;
- elapsed time, completed-step progress, current model/tier, tokens, event log, streaming output, and final evaluation;
- latest-active-run resolution and empty state;
- scorecard expansion when evaluation completes;
- error and connection-state visibility.

#### Rewrite and refinement

- Use the Flow Canvas interaction model inside Evidence Ledger styling: graph center, live trace/timeline, contextual inspector.
- Keep the active step and latest material event visible without auto-scrolling away from a user-selected historical step.
- Separate transport state from workflow state.
- Add explicit “follow live” control, pause log auto-scroll, event-level filtering, and copy/download for bounded logs.
- Add cancel-run only if a safe server cancellation contract, authorization, event, and tests are implemented.
- Preserve the completed state at the same deep link and offer links to the permanent run/evaluation record.

#### Space budget

- status/header: ≤76 px;
- DAG receives at least 55% desktop width;
- inspector receives 300–420 px;
- logs are a collapsible bottom drawer or inspector tab rather than a permanently competing column.

#### Exclude

- fake pause/resume controls;
- unbounded in-memory event rendering;
- animations on every event;
- automatic selection changes after the user intentionally pins a step.

### 7.5 Workflows index — `/workflows`

#### Current behavior to preserve

- registered workflow count;
- search by workflow name;
- latest run status;
- workflow deep links;
- loading, error, no-workflows, and no-match states;
- `/` shortcut.

#### Rewrite and refinement

- Use a ledger list/table, not one card per workflow.
- Add description, tags, step count, last run/time, last evaluation grade, default routing pack, and validation state when backed by APIs.
- Add sorting and URL-backed filtering.
- Provide “Create workflow” only when the builder has a safe creation contract; otherwise explain the repository-owned definition workflow.
- Make duplicate/import actions explicit and validated if implemented.

#### Space budget

- header + search/filter: ≤130 px;
- ledger list fills remaining space;
- rows should remain scannable at approximately 52–68 px.

#### Exclude

- large DAG thumbnail on every row;
- editing YAML directly from the index;
- tags or descriptions synthesized only in the client.

### 7.6 Workflow detail and run configuration — `/workflows/:name`

#### Current behavior to preserve

- workflow DAG, description, node/edge count, and tiers;
- workflow input form generated from schema;
- string, number, enum, object/array, image, audio, and file inputs;
- required/default handling and media data-URL safety behavior;
- execution runtime profile;
- optional rubric and evaluation controls;
- repository/local dataset selection, evaluation set, sample indices, runs per record, sample preview, and batch execution progress;
- direct model override;
- deterministic demo run when supported;
- run history, edit link, run submission, and navigation to live execution;
- dataset deep-link preconfiguration.

#### Rewrite and refinement

- Treat DAG as context and run configuration as the primary task.
- Group configuration into Inputs, Routing, Runtime, and Evaluation with progressive disclosure.
- Add model-pack selection with clear precedence: explicit per-run model override > selected run pack > workflow-bound pack > global active pack > existing deployment/env/default routing.
- Preview the resolved routing plan before launch: requested tier, candidate chain, disabled/unavailable providers, fallback policy, and source of each setting.
- Preserve a direct model override as an advanced escape hatch.
- Show an accurate batch job count and estimated request volume before submission.
- Require confirmation for unusually large batch sizes using a server-enforced maximum.
- Keep recent run history visible but secondary.

#### Space budget

- desktop: DAG/context 55–65%, configuration inspector 340–420 px;
- mobile: configuration first, DAG in a separate tab;
- common required inputs and Run action visible without expanding Advanced.

#### Exclude

- silently applying a model pack;
- storing raw media in local storage;
- unlimited batch fan-out;
- cost estimates unless provider pricing and token assumptions are versioned and trustworthy.

### 7.7 Workflow builder — `/workflows/:name/edit`

#### Current behavior to preserve

- feature-gated access;
- visual and YAML modes;
- dirty-state tracking and unsaved-change protection;
- validate and save actions with validation issue reporting;
- DAG editing and local draft derivation;
- add/delete step;
- add/remove dependencies;
- select/configure nodes and edges;
- edge mappings and target `when` condition;
- per-step agent, model override, persona, sampling parameters, tools, observers, dependencies, condition, and prompt file;
- catalogs for personas, tools, observers, and probed models;
- model tier/capability context;
- run-after-save/detail navigation;
- correct query invalidation after save.

#### Rewrite and refinement

- Adopt Flow Canvas spatial ergonomics within the Evidence Ledger system.
- Provide pan/zoom, fit view, minimap, keyboard traversal, accessible selection, multi-select, duplicate, copy/paste, and undo/redo.
- Keep node configuration in a consistent right inspector with compact summaries and advanced sections.
- Add workflow-level and node-level model-pack binding; node direct model override remains highest precedence.
- Show routing provenance and validation inline on affected nodes.
- Validate continuously with debouncing, but keep explicit Save and server validation as authority.
- Keep YAML and visual modes round-trip safe; add structural diff before overwriting changes made in the other mode.
- Make auto-layout an explicit reversible action.
- Preserve edge labels/mappings and make connection creation keyboard accessible.
- Add a read-only mode with a clear reason when editing is unavailable.

#### Space budget

- canvas gets the largest region;
- tool rail ≤56 px;
- inspector 320–400 px;
- top controls ≤58 px;
- validation appears inline and in a compact problems drawer, not as a permanent third column.

#### Exclude

- collaborative multiplayer editing;
- arbitrary Python execution in the browser;
- a full IDE/file explorer;
- autosaving directly to repository definitions without explicit save semantics;
- visual-only features that cannot round-trip to the workflow document.

### 7.8 Datasets — `/datasets`

#### Current behavior to preserve

- repository and local dataset groups;
- dataset selection;
- paged/sample-index browsing;
- sample selection and detailed field rendering;
- metadata expansion;
- workflow compatibility/adapted-input preview;
- workflow selection and deep link to a run preconfigured with the sample;
- loading, error, empty, and no-selection states.

#### Rewrite and refinement

- Use a three-level evidence workspace: source/dataset list, sample table, sample detail inspector.
- Add search/filter by source, task, schema, size, and compatibility when metadata exists.
- Surface source provenance, revision/hash, split, license, sample count, schema, cache state, and last refresh.
- Integrate dynamic dataset providers already supported by the backend and clearly distinguish remote metadata from locally cached data.
- Add explicit register/import/refresh actions only through validated backend contracts.
- Add schema and adapter validation before launching a workflow.
- Preserve sample-to-run flow and make selected dataset/sample state URL-addressable.

#### Space budget

- source/dataset rail: 220–280 px;
- sample table: main region;
- detail inspector: 320–420 px or mobile sheet;
- metadata defaults collapsed unless it affects validity or licensing.

#### Exclude

- a general-purpose dataframe editor;
- silently downloading very large datasets;
- claiming benchmark validity from dataset presence alone;
- displaying remote samples as cached when they are not.

### 7.9 Evaluations — `/evaluations`

#### Current behavior to preserve

- evaluated-run scorecard;
- grade distribution and score histogram;
- per-workflow pass rate;
- recent evaluation list;
- expandable run rubric details;
- evaluate/re-evaluate a previous captured run;
- two-run head-to-head comparison under one rubric;
- candidate scores, winner/tie, weighted delta, and per-criterion deltas;
- judge-skipped, hard-gate, floor, and error states;
- run detail links and query invalidation after mutation.

#### Rewrite and refinement

- Make Evidence Ledger’s evaluation workspace the canonical design reference.
- Organize into Runs, Comparisons, Benchmarks, and Rubrics without creating separate top-level navigation for each.
- Add URL-backed filters for workflow, dataset, rubric/version, model/provider, judge model, grade, pass/fail, hard-gate state, and date where data exists.
- Show score provenance: rubric/version, objective layer, judge identity/resolved model, judge skipped/fallback, advisory layer, calibration artifact/version, timestamp, and source run revision.
- Add trend and regression views only using statistically honest sample counts and uncertainty.
- Add comparison history only if comparisons are persisted; otherwise label current comparison as ephemeral.
- Make evaluation setup controls functional. Remove presentational-only option pills.
- Add benchmark coverage/status and dataset-to-workflow adapter validity, not a vanity leaderboard.
- Add export for a self-contained evaluation evidence bundle when supported.

#### Space budget

- heading/tabs/filters: ≤150 px;
- compact scoreline: ≤160 px;
- evaluation ledger/table is the dominant surface;
- detailed reasoning and evidence open in an inspector or dedicated deep link.

#### Exclude

- hiding judge-skipped or missing-golden-text states;
- presenting incomparable rubrics as one ranking;
- confidence claims without statistical support;
- fake persisted comparison history;
- hard-gate activation that contradicts current ADRs or lacks identity/calibration binding.

### 7.10 Model Router — `/models`

Consolidate current Model Finder plus provider/tier Settings into one coherent route with URL-addressable subviews:

1. Models
2. Providers
3. Tiers
4. Packs
5. Playground
6. Hardware

Do not render all six as one long page.

#### Current behavior to preserve

- live provider rescan/probe;
- available/unavailable provider state and no-LLM mode;
- full probed model catalog grouped by provider;
- model substring search, tier/capability/cloud/running/verification indicators, and deep links to chat;
- direct chat playground with model selection and stream/error behavior;
- local hardware profile discovery and editable override;
- recommendation category and sorting;
- RAM/CPU/accelerator/throughput profile;
- hardware fit bands and model external links;
- provider endpoint listing;
- provider creation for OpenAI, Anthropic, GitHub Models, Ollama, Foundry Local, and custom endpoints;
- provider enable/disable and deletion;
- base URL, credential environment-variable name, default model, label, and safe validation;
- environment-configured provider disclosure;
- tier chains, effective/default/override order, reranking, reset-to-default, and route-winner indicator;
- per-model capability overrides and clear/reset behavior;
- mutation errors and cache updates.

#### Providers refinement

- Add editing for existing providers, not only create/delete.
- Add explicit connection test/probe with timestamp, status, latency, discovered model count, and actionable error category.
- Explain precedence and the effect of disabling a provider before saving.
- Prevent disabling/deleting the final viable provider used by an active/default pack without a clear warning and dependency list.
- Keep credentials deployment-owned: accept only environment-variable names or a separately approved secret-manager reference. Never accept or echo raw keys.
- Allow provider-specific safe options through typed schemas; do not expose an unvalidated arbitrary JSON bag by default.

#### Tiers refinement

- Support mouse and keyboard reordering.
- Show default, UI override, environment pin, effective chain, unavailable entries, and actual routing winner distinctly.
- Validate duplicate entries, empty required tiers, disabled providers, missing capabilities, and unsupported models.
- Show fallback and cross-tier policy only if the backend contract exposes it.
- Provide a dry-run route explanation for a sample requirement without invoking a model.

#### New named model packs

Implement reusable, named, versioned routing packs. A pack is a deliberate configuration bundle, not a copy of mutable global state.

A pack must include, as applicable:

- stable ID, display name, description, version, timestamps, and active/archive state;
- per-tier ordered model chains;
- allowed/enabled provider set;
- capability requirements and model capability overrides or references;
- fallback and cross-tier policy where supported;
- optional max-cost/max-latency policy only when enforceable;
- default evaluation judge model/policy where supported;
- provenance showing whether each value is inherited or explicit.

Required pack operations:

- create from effective routing;
- create from defaults;
- edit as a new version rather than silently changing historical run meaning;
- duplicate;
- validate/dry run;
- activate as global default;
- bind to a workflow;
- select for one run;
- archive;
- export/import through a versioned, validated schema;
- show dependent workflows and recent runs before archive/delete.

Runtime integration requirements:

- run launch accepts an optional pack ID/version;
- workflow definition or UI-managed binding can name a default pack;
- node-level direct model override remains the highest-precedence escape hatch;
- every run records selected pack ID/version, requested route, resolved provider/model, fallbacks, and relevant policy snapshot;
- historical run detail resolves from recorded data, not the pack’s current mutable state;
- environment/deployment pins retain their documented precedence unless an ADR intentionally changes it.

Add backend models, persistence, APIs, generated types, migrations/version handling, and tests as needed. Keep pack storage instance-scoped unless a broader deployment store is explicitly designed. Do not overload the existing provider/tier update payload with an unversioned ad hoc field.

#### Space budget

- subview tabs and status summary: ≤100 px;
- each subview has one dominant table/workspace;
- provider/model inspectors use 320–420 px;
- pack editor uses a focused route or full-width workspace, not a cramped modal;
- show at most the essential status columns by default; capabilities and raw metadata belong in inspectors.

#### Exclude

- secret storage in frontend or UI settings;
- provider account/billing management;
- automatic provider signup;
- claiming hardware fit equals model quality;
- unversioned pack mutation that changes historical provenance;
- arbitrary pricing estimates without a maintained source/version.

### 7.11 Settings compatibility — `/settings`

The current Settings page only contains provider endpoints and tier routing. Move those functions into Model Router and redirect:

- `/settings` → `/models?tab=providers`

Do not create a mostly empty replacement page. Independent preferences such as theme, density, keyboard-shortcut help, or telemetry may live in a compact application menu until enough real settings justify a route.

### 7.12 Prototypes and migration cleanup — `/prototypes`

Use the prototypes during implementation and visual comparison. Once the production Evidence Ledger system is complete:

- remove the prototype route and mock-only production imports, or move the lab to a clearly development-only Storybook/design-lab boundary;
- do not ship mock metrics in the normal production bundle;
- retain approved screenshots/design documentation as evidence if useful.

### 7.13 Not found, errors, and empty states

Create one consistent family for:

- unknown route;
- unknown workflow/run/dataset/model pack;
- backend unavailable;
- unauthorized/forbidden if authentication is enabled;
- invalid deep-link parameters;
- no data yet;
- no filter matches;
- stale cached data with refresh failure;
- feature disabled/read-only.

Every state must explain what happened and offer the safest next action.

## 8. Product-wide engineering requirements

### Architecture

- Prefer route-level code splitting.
- Break current very large page components into cohesive feature modules without producing a meaningless one-file-per-div component tree.
- Keep server state in a query/cache layer; do not duplicate it into global client state.
- Keep transient UI state local or URL-backed when shareable.
- Generate or validate TypeScript types from server contracts per ADR-014.
- Preserve abort/cancellation behavior for fetches and streams.
- Bound event lists, logs, JSON rendering, and large tables through virtualization or pagination where needed.

### Accessibility

- Meet WCAG 2.2 AA for critical flows.
- Use semantic landmarks, headings, tables, forms, dialogs/sheets, and live regions.
- Provide visible focus, complete keyboard operation, logical tab order, and escape behavior.
- Do not encode status by color alone.
- Announce mutation, connection, validation, and streaming status changes appropriately without excessive screen-reader noise.
- Provide graph/list equivalence for users who cannot operate a spatial DAG.

### Security and privacy

- Never render or log secret values.
- Sanitize/escape user and model content; do not use unsafe HTML insertion.
- Treat model output, YAML, JSON, dataset values, and event payloads as untrusted.
- Bound file/media size and validate MIME/type server-side.
- Preserve human approval boundaries for high-impact tools; the UI must not imply that a pending approval is a normal running step.
- Require server authorization for mutations; hiding a button is not access control.

### Performance

- Establish baseline and final production bundle sizes.
- Code-split heavy graph/editor/JSON views.
- Avoid refetch storms and unconditional background polling.
- Pause live-tail polling when not visible.
- Keep primary interactions responsive with realistic row/event volumes.

## 9. Implementation sequence

Use vertical slices and keep the application runnable after each phase.

### Phase 0 — audit and decision artifacts

1. Capture current git status and preserve user work.
2. Run the existing targeted UI tests and production build to establish a baseline.
3. Complete the route/capability matrix.
4. Confirm the React/Vite/shadcn architecture and decide whether any supporting library warrants replacement.
5. Write/update architecture and design-system documents.
6. Identify backend contract gaps and classify them as required, optional, or excluded.

### Phase 1 — system foundation

1. Configure shadcn/ui and map its semantic CSS variables to the Evidence Ledger tokens.
2. Implement or restyle the selected shadcn primitives and remove superseded generic primitives as routes migrate.
3. Implement the global shell, navigation, responsive behavior, focus management, command palette integration, theme, and notification policy.
4. Implement shared table, filter, scoreline, inspector/sheet, tabs, form, error, empty, loading, and provenance components using the owned shadcn foundation where appropriate.
5. Add visual test fixtures based on typed data builders, not inline page mocks.

### Phase 2 — Observe

Migrate Overview, Runs, Run Detail, and Live Execution. Preserve streaming and replay behavior before visual polish. Add pagination/provenance contracts only with backend tests.

### Phase 3 — Build

Migrate Workflows, Workflow Detail/Run Configuration, Workflow Builder, and Datasets. Maintain visual/YAML round-trip and dataset-to-run deep links.

### Phase 4 — Evaluate

Migrate Evaluations, comparison, rubric detail, benchmark views, and evidence provenance. Resolve existing presentational-only controls by implementing or removing them.

### Phase 5 — Configure

Consolidate Model Finder and Settings into Model Router. Preserve providers, tiers, hardware fit, probe, and playground. Implement model-pack contracts and integrations through workflow/run provenance.

### Phase 6 — cleanup and hardening

1. Remove superseded components/styles/routes and dead dependencies.
2. Remove or development-gate prototypes.
3. Update docs, ADRs, screenshots, changelog, and test coverage.
4. Run the full verification matrix.
5. Perform a final capability-matrix audit proving no current behavior was silently lost.

If the scope is too large for one uninterrupted implementation window, persist the matrix, design specification, ADRs, and next executable phase to disk before context compaction. Continue the goal in subsequent turns; do not mark it complete because a phase ended.

## 10. Testing and verification

For every migrated route, add or update:

- unit tests for transformations and validation;
- component tests for loading, populated, empty, partial, and error states;
- mutation success/error/rollback tests;
- keyboard and focus behavior tests;
- responsive browser tests for essential flows;
- contract tests for new API fields;
- WebSocket tests for connect, reconnect, duplicate/out-of-order events, bounded event history, completion, and failure;
- accessibility assertions feasible with the selected stack;
- visual screenshots at 1440×900, 1280×720, 1024×768, and 390×844 for critical pages.

At minimum verify:

```powershell
npm --prefix agentic-workflows-v2/ui run build
npm --prefix agentic-workflows-v2/ui test
npm --prefix agentic-workflows-v2/ui run test:e2e
.venv\Scripts\python.exe -m pytest agentic-workflows-v2/tests -q
.venv\Scripts\python.exe agentic-workflows-v2/scripts/check_docs_refs.py
.venv\Scripts\python.exe scripts/generate_doc_stats.py --check
pre-commit run --all-files
git diff --check
```

Use narrower commands during iteration. If any full gate is unavailable or fails for a pre-existing reason, record the exact command, exact failure, evidence that it is pre-existing, and the narrower verification that covers your change. Never report a gate as passing when it did not run.

Required browser journeys:

1. Start from Overview, filter a run, inspect it, open full run detail, and replay safely.
2. Launch a workflow with normal inputs, watch live execution, and reach permanent run detail.
3. Launch a dataset-backed evaluated batch with a bounded sample selection.
4. Edit a workflow visually, validate, inspect the YAML diff, save, reload, and confirm round-trip fidelity.
5. Add a safe custom provider using an environment-variable name, test it, disable/re-enable it, and inspect consequences.
6. Reorder a tier with keyboard, reset it, and confirm effective routing provenance.
7. Create/version/validate a model pack, bind it to a workflow, launch a run with it, and verify recorded resolved model/provider/pack provenance.
8. Evaluate a previous run, inspect rubric layers and gate failures, then compare two runs.
9. Browse a dataset sample, validate workflow compatibility, and deep-link to a preconfigured run.
10. Complete essential navigation and actions at 390 px using keyboard-equivalent controls and a screen-reader-friendly DOM.

## 11. Definition of done

Do not mark the goal complete until all of the following are true:

- all production routes use the Evidence Ledger system;
- all production interaction primitives use the customized shadcn/ui foundation or have a documented reason for a specialized component;
- every current capability has been preserved, intentionally refined, consolidated, or explicitly removed with rationale;
- provider creation/editing/toggle/probe and tier configuration work from Model Router;
- named versioned model packs can be created, validated, selected for runs, bound to workflows, and traced in run provenance;
- no fake data or inert production controls remain;
- loading/error/empty/partial/offline states are implemented consistently;
- required deep links, keyboard flows, WebSocket behavior, and CLI parity work;
- desktop and mobile layouts are visually verified;
- the final visual audit confirms warm-paper surfaces, editorial typography, generous whitespace, hairline structure, restrained orange, and a calm uncluttered rhythm across every route—not only Evaluations;
- production build, relevant tests, docs checks, and diff checks pass or have precisely documented pre-existing blockers;
- framework and backend contract changes have ADRs and generated types where required;
- superseded UI code and dependencies are removed;
- `CHANGELOG.md` and UI documentation describe the user-visible change;
- a final report lists files changed, capabilities delivered, exclusions/deferred items, verification commands/results, screenshots, and remaining risks;
- the goal mechanism is marked complete only after the objective is actually achieved.

When product intent and current implementation conflict, preserve runtime correctness and evidence integrity, document the conflict, choose the smallest coherent product behavior, and continue. Ask the user only when a decision would materially change authorization, security boundaries, public runtime semantics, or the core information architecture defined here.

## END PROMPT
