# Runtime dashboard

This package is the React 19 dashboard for Agentic Workflows v2. It uses
TypeScript, Vite 8, React Router, TanStack Query, and XYFlow.

## Start development

The normal repository-wide command is:

```text
just dev
```

It starts the FastAPI backend on port `8010` and this Vite server on port
`5173`.

To work on the UI by itself, first start the backend, then run:

```text
npm --prefix agentic-workflows-v2/ui ci
npm --prefix agentic-workflows-v2/ui run dev
```

Vite forwards `/api` requests to `http://localhost:8010`. In development, the
WebSocket client connects directly to that backend because Vite's hot-module
reload also uses WebSockets.

Set `VITE_API_PROXY_TARGET` before starting Vite to use a different backend:

```powershell
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:9000"
npm --prefix agentic-workflows-v2/ui run dev
```

## Pages

| Route | Purpose |
|---|---|
| `/` | Runtime summary |
| `/workflows` | Workflow catalog |
| `/workflows/:name` | Workflow details and run controls |
| `/workflows/:name/edit` | Workflow editor |
| `/datasets` | Evaluation datasets |
| `/evaluations` | Evaluation setup and comparison |
| `/models` | Model finder, providers, tiers, and model packs |
| `/runs` | Saved runs |
| `/runs/:filename` | Saved run details |
| `/live/:runId` | Live execution |

`/settings` redirects to the provider tab under `/models`.

The workflow editor is enabled by default in development. Production builds
require `VITE_AGENTIC_ENABLE_WORKFLOW_BUILDER=1` or
`AGENTIC_ENABLE_WORKFLOW_BUILDER=1`.

## Commands

Run these from the repository root:

```text
npm --prefix agentic-workflows-v2/ui run dev
npm --prefix agentic-workflows-v2/ui run build
npm --prefix agentic-workflows-v2/ui test
npm --prefix agentic-workflows-v2/ui run test:coverage
npm --prefix agentic-workflows-v2/ui run test:e2e
```

- `build` runs TypeScript project checks before creating `dist/`.
- `test` runs the Vitest unit suite once.
- `test:coverage` enforces 60% for lines, statements, and functions, and 56%
  for branches. The branch threshold is a temporary ratchet recorded in
  `vitest.config.ts`.
- `test:e2e` runs Playwright and requires its configured backend and browser
  setup.

## Code map

| Path | Purpose |
|---|---|
| `src/App.tsx` | Application routes |
| `src/pages/` | Route-level pages |
| `src/components/` | Shared UI and workflow/run views |
| `src/api/` | HTTP clients and generated wire types |
| `src/hooks/` | Shared state and interaction hooks |
| `src/styles/` | Design tokens and global styles |
| `src/__tests__/` | Vitest tests |
| `e2e/` | Playwright tests |

`src/main.tsx` installs the router, React Query client, and top-level error
boundary.

## API contract changes

The Python contracts generate JSON Schemas under
`agentic-workflows-v2/tests/schemas/`. After those schemas are regenerated,
update the TypeScript types with:

```text
npm --prefix agentic-workflows-v2/ui run generate:types
```

Commit the schemas and generated TypeScript together. CI regenerates both and
fails when they do not match.

## Production serving

`npm run build` writes `dist/`. When that directory exists, FastAPI serves it
as a single-page application and keeps `/api`, `/ws`, `/docs`, and
`/openapi.json` on their backend routes.

See the central [runtime API guide](../../docs/api-contracts-runtime.md) for
the route contracts.
