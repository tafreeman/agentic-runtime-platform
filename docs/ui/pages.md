# Evidence Ledger page guide

This guide describes the production UI as of 2026-07-14. All pages share the
responsive Evidence Ledger shell, warm-paper tokens, route Suspense state,
focus rules, semantic status treatment, and CLI parity where a command exists.

## Overview — `/`

The landing page summarizes real run and runtime data, recent evidence,
available workflows, and first-run guidance. Filters and links navigate to the
underlying evidence rather than presenting decorative metrics. Partial API
failures preserve available sections and offer retry or the safest next step.

## Runs — `/runs`

The run ledger discloses its bounded server window and supports status,
workflow, and text filters. `j`/`k` move selection, Enter opens the inspector,
and Escape closes it. The inspector links to permanent detail. Live tail keeps
its existing visibility/retry safeguards; the page does not imply complete
history when only a window is loaded.

## Run detail — `/runs/:filename`

Permanent run evidence includes metadata, workflow structure, step input and
output, YAML/JSON evidence, evaluation layers, and guarded replay. A routing
provenance section now shows:

- selection source (`run`, `workflow`, `global`, or defaults);
- requested direct model override;
- exact model-pack identity/version and immutable snapshot;
- resolved step model and provider.

Recorded evidence is displayed as untrusted text and is never editable.

## Live execution — `/live/:runId` and `/live/latest`

The live page connects to the run WebSocket, reduces duplicate/out-of-order
events, bounds event history, and distinguishes transport state from workflow
state. Terminal runs link to permanent detail. The UI does not present pause,
resume, or cancel because the backend has no such contract.

## Workflows — `/workflows`

The registry searches real registered workflows and links to launch/detail.
Descriptions, latest-run state, and pack status appear only when backed by an
API. Empty and error states offer retry or first-run navigation.

## Workflow launch — `/workflows/:name`

The page combines the DAG, schema-driven inputs, runtime profile, routing, and
optional evaluation/batch configuration. Input types include text, numbers,
objects, enums, and bounded file/media data URLs. Advanced routing supports:

1. automatic workflow/global/default policy;
2. an exact immutable model-pack version for the run;
3. an optional direct model override, which has higher precedence.

Repository, local, or eval-set data can supply a bounded sample selection and
multiple runs per record. Successful launch navigates to live execution.

## Workflow editor — `/workflows/:name/edit`

When the feature flag is enabled, visual and YAML modes share one document.
The editor exposes validation, node/edge inspection, explicit save, dirty
protection, and query invalidation. The visual graph retains React Flow and a
keyboard/semantic alternative. Saving is disabled when the server marks the
workflow read-only.

## Datasets — `/datasets`

The three-level workspace selects a source/dataset, pages sample summaries,
and inspects the selected sample plus metadata. Compatibility checks are
explicit. “Run with sample” creates a deep link to workflow configuration; it
does not start work silently.

## Evaluations — `/evaluations`

Evaluations presents backed run scores, workflow pass rates, rubric layers,
gate failures, expected-output presence, and explicit judge-skip reasons.
Existing runs can be re-evaluated and two comparable runs can be compared.
Comparison remains ephemeral because no persistence contract exists.

## Model Router — `/models`

The `tab` query parameter selects a stable workspace:

| `tab` | Surface |
|---|---|
| `finder` (default) | Catalog discovery, availability, search, filters |
| `providers` | Provider endpoints and safe operational probes |
| `tiers` | Ordered fallbacks, capability metadata, dry-run route |
| `packs` | Immutable named routing policy lifecycle |
| `playground` | Streaming text/image chat |
| `hardware` | Hardware fit and operator override |

The default finder keeps a responsive summary card for every provider reported
by the backend, including zero-model and missing-key states. Detailed model
groups remain collapsed and searchable below the cards, so large live catalogs
such as OpenRouter stay navigable without hiding any supported backend.

### Providers

Create or edit a provider with a stable ID, provider type, HTTP(S) base URL,
and optional environment-variable **name**. Secret values are never accepted
or returned. Operators can probe, disable/re-enable, and delete with explicit
confirmation. Probe results include classified outcome, latency, timestamp,
and model count without credential leakage.

### Tiers

Reorder models with pointer or keyboard controls, reset to defaults, and edit
known capability metadata. Dry-run selects a tier/capability and explains the
effective candidate chain and winner without invoking a provider.

### Model packs

Create version 1 from effective routing, built-in defaults, or an explicit
policy. Editing saves a new immutable version. A version can be validated,
activated globally, duplicated, exported/imported, bound to a workflow,
unbound, or archived after dependency disclosure and confirmation. Archived
versions remain available to historical run provenance.

### Playground and multimodal behavior

The playground uses the real `POST /api/chat` SSE endpoint. A message may
contain ordered text and local image parts. Up to four PNG/JPEG/WebP/GIF images
of five MiB each may be previewed and removed before sending. SVG and remote
input URLs are rejected. Typed image output is rendered alongside text when
the backend validates its MIME and URL. Stop aborts the current request; Clear
resets only the conversation.

## Settings compatibility — `/settings`

This path redirects to `/models?tab=providers`. There is no separate settings
information architecture.

## Responsive behavior

At desktop widths, the left evidence index remains visible. On smaller screens
it becomes a five-item bottom navigation and wide tables/canvases keep their
specialized scroll, list, or inspector behavior. Critical layouts are verified
at 1440×900, 1280×720, 1024×768, and 390×844.

## Production-state policy

Every route must make loading, empty, partial, stale/error, disabled/read-only,
and no-match states distinguishable with text and a safe action. Controls that
have no server capability are omitted; production contains no mock metrics or
inert actions. The capability and exclusion record is maintained in
[the migration matrix](evidence-ledger-migration.md).
