# UI API integration

**Current:** 2026-07-28
**Client:** `agentic-workflows-v2/ui/src/api/client.ts`
**Types:** `ui/src/api/types.ts` plus `*.generated.ts`

The browser calls only `/api` paths on the same origin. `requestJson` owns
status handling, JSON decoding, and safe errors. TanStack Query owns cache and
invalidation; components do not maintain a second copy of server state.

## Cache policy

The application query client uses a ten-second stale window, one retry, and no
refetch on window focus. Feature hooks can override polling only where live
state requires it. Mutations invalidate the narrow resource keys they change.
SSE chat uses fetch directly so it can keep one `AbortController`; live workflow
execution uses the WebSocket hook and bounded reducer.

## Core resources

| UI function/family | HTTP resource | Notes |
|---|---|---|
| workflow list/DAG/editor | `/api/workflows...` | Registry, graph, document, validation/save |
| `runWorkflow` | `POST /api/run` | Optional exact `model_pack` and direct `model_override` |
| run list/detail/replay | `/api/runs...` | Permanent evidence and guarded replay |
| evaluation/datasets | `/api/eval...` | Scores, comparison, dataset paging/sample detail |
| model probe | `/api/models/probe` | Live availability/catalog; no fake discovery |
| hardware | `/api/model-finder/profile...` | Detection, recommendations, and operator override |
| provider settings | `/api/settings/providers` | Full-replacement settings document |
| tier settings | `/api/settings/tiers` | Ordered model overrides and capabilities |
| model packs | `/api/settings/model-packs...` | Immutable lifecycle and bindings |
| chat | `POST /api/chat` | Explicit-model or tier-routed abortable SSE text/media stream |

## Providers

`GET /api/settings/providers` returns provider records, supported provider
types, and providers configured by deployment environment. `PUT` replaces the
validated collection. Provider records hold an optional environment-variable
name, never a credential value.

`POST /api/settings/providers/{provider_id}/probe` probes only the saved,
enabled provider. Explicit base URLs are restricted to HTTP(S) and reject
embedded credentials. Ollama uses its tags endpoint; compatible providers use
their model-list endpoint with the saved env-name credential if required.
Redirects are disabled, timeouts are bounded, and the response exposes only a
classified status, message, latency, model count, and timestamp.

## Model packs

Model packs are instance-scoped settings records. Each update appends a
version, and all references are exact `{id, version}` values.

| Method/path | Behavior |
|---|---|
| `GET /api/settings/model-packs` | Packs, active ref, workflow bindings |
| `POST /api/settings/model-packs` | Create v1 from effective/default/explicit policy |
| `PUT /api/settings/model-packs/{id}` | Append an immutable version |
| `POST /api/settings/model-packs/{id}/duplicate` | Create a new stable ID at v1 |
| `POST /api/settings/model-packs/{id}/validate?version=N` | Validate chains/providers/capabilities |
| `POST /api/settings/model-packs/{id}/activate?version=N` | Set global exact version |
| `PUT /api/settings/model-packs/{id}/bindings/{workflow}?version=N` | Bind exact version |
| `DELETE /api/settings/model-packs/bindings/{workflow}` | Remove binding |
| `GET /api/settings/model-packs/{id}/dependencies?version=N` | Active/binding/recent-run use |
| `POST /api/settings/model-packs/{id}/archive?version=N` | Archive after dependency guard |
| `GET /api/settings/model-packs/{id}/export?version=N` | Versioned JSON document |
| `POST /api/settings/model-packs/import` | Validated import as a new pack |

The workflow run request accepts `model_pack?: ModelPackRef`. The server
resolves the requested/workflow/global pack, enters an execution-context-local
routing scope, and records source, snapshot, direct override, and resolved
step models/providers in `run.extra.routing`. The UI reads that recorded data;
it never recomputes historical provenance from current settings.

## Chat and multimodal wire format

`ChatMessage.content` is backward-compatible:

```ts
type ChatContentPart =
  | { type: "text"; text: string }
  | { type: "image"; mime_type: RasterMime; data_url: string; alt?: string };

type ChatMessage = {
  role: "user" | "assistant" | "system";
  content: string | ChatContentPart[];
};
```

The request validator accepts 1–12 ordered parts, PNG/JPEG/WebP/GIF data URLs,
and at most five decoded MiB per image. Remote image input and SVG are rejected.
The route converts parts to the installed LangChain provider block format.

SSE frames are discriminated JSON objects:

```text
route  { type, requested_tier, model }
token  { type, delta }
media  { type, mime_type, url, alt? }
done   { type, model }
error  { type, category, message }
```

The request is an overload: `{model, messages, temperature?}` targets one
provider/model exactly, while `{tier, messages, temperature?}` delegates model
selection to the configured tier router. Supplying both selectors or neither
returns `422`. Tier requests emit `route` before output so clients can record
the actual provider/model selected.

`media` accepts only an explicit safe raster MIME and a validated raster data
URL or HTTPS URL. Unsafe provider blocks are ignored. The UI parses complete
SSE frames, appends text/media to the active assistant message, announces
status changes, and aborts fetch when Stop is selected or the component
unmounts.

## Generated contracts and drift

Python Pydantic models own the wire format. Run:

```powershell
Push-Location agentic-workflows-v2
..\.venv\Scripts\python.exe -m scripts.generate_ts_types
npm --prefix ui run generate:types
..\.venv\Scripts\python.exe -m pytest tests/test_schema_drift.py -q
Pop-Location
```

The snapshots cover workflow/step events, DAG/editor/input/run shapes, chat
requests, and every chat stream event including `ChatMediaEvent`. Generated
files are committed so drift is reviewable. Chat coverage includes the two
request constructors and every stream event including `ChatRouteEvent` and
`ChatMediaEvent`.

## Error, security, and privacy rules

- Render API/model/dataset/YAML/JSON content as escaped text; never use unsafe
  HTML insertion.
- Preserve structured HTTP status and classified stream errors without echoing
  request headers, secret values, or provider response bodies.
- Disable or omit controls without a backend mutation contract.
- Validate media type and size on the server even when the browser has already
  checked them.
- Never treat hidden controls as authorization; API middleware remains the
  mutation boundary.
