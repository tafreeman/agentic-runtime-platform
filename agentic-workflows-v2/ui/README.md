# Agentic Runtime Platform UI

React 19 + Vite 6 dashboard for running and inspecting Agentic Runtime Platform.

## Quick Start

```bash
cd agentic-workflows-v2/ui
npm install

npm run dev          # Dev server on :5173 (proxies /api and /ws)
npm run build        # Type check + production bundle
npm run test         # Vitest suite
npm run test:coverage
```

Backend proxy:
- Defaults to http://localhost:8010. Override with `VITE_API_PROXY_TARGET=http://<host>:<port>` when running the backend elsewhere.

## Architecture Notes

- **Entry:** `src/main.tsx` — renders the app wrapped in `AppErrorBoundary` and React Query provider.
- **Routing & views:** `src/App.tsx` (React Router 7); pages under `src/pages/`.
- **Layout:** `src/components/layout/Sidebar.tsx` — theme switcher (dark / paper / bolt), nav links.
- **Flow visualization:** `@xyflow/react` in `src/components/dag/WorkflowDAG.tsx` (full interactive); `BDagMini.tsx` for static SVG thumbnails.
- **Data fetching:** `@tanstack/react-query` with API clients in `src/api/`.
- **Hooks:** `src/hooks/useHotkeys.ts` — global keyboard shortcuts (n / f / / / j / k / Esc).

## Component Catalogue

| Component | Location | Purpose |
|-----------|----------|---------|
| `StatusBadge` | `components/common/` | ASCII bracket status: `[OK ]` `[RUN]` `[ERR]` `[WARN]` |
| `BDagMini` | `components/dag/` | Static SVG DAG thumbnail (no xyflow) |
| `WorkflowDAG` | `components/dag/` | Interactive xyflow DAG with live step states |
| `EmptyState` | `components/states/` | `$ no <entity> yet` terminal-style empty page |
| `ErrorBanner` | `components/states/` | `[!] {message}` full-page error |
| `NotFoundPage` | `components/states/` | `404 not found` with breadcrumb |
| `AppErrorBoundary` | `components/states/` | React error boundary wrapping the whole app |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` or `f` | Focus the filter input on Dashboard / Workflows pages |
| `Esc` | Clear filter and blur input |
| `j` / `k` | (reserved — next / prev item) |
| `n` | (reserved — new run) |

## Themes

Three CSS themes via `data-theme` on `<html>`: `dark` (default), `paper` (warm cream), `bolt` (cobalt).
All colors defined as space-separated RGB triplets in `src/styles/tokens.css` and consumed as `rgb(var(--b-*))`.

Keep backend (`agentic-workflows-v2` FastAPI app) running for live data; the proxy forwards `/api` and `/ws` to the configured target.
