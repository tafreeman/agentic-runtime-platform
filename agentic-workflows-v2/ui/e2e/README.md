# E2E Tests (Playwright)

Streaming end-to-end tests for the Agentic Runtime Platform v2 UI. Introduced in
Epic 2 Story 2.2 — *Playwright E2E Bootstrap + 5× PR Gate*.

## Quick start

From `agentic-workflows-v2/ui/`:

```bash
npm install                          # installs @playwright/test
npx playwright install chromium      # (once) downloads the browser
npm run test:e2e                     # single pass
npm run test:e2e:5x                  # 5× PR gate (matches CI)
npm run test:e2e:ui                  # interactive debug mode
```

`playwright.config.ts` spawns the backend (`uvicorn` on `:8010`) and the Vite
dev server (`:5173`) automatically via its `webServer` block. Running
dev servers on those ports are reused outside CI (`reuseExistingServer: !CI`).

## What's covered

| Spec | Story | Asserts |
|------|-------|---------|
| `streaming.spec.ts` | 2.2 | code_review renders 5 step rows, shows a terminal status, UI status matches `/api/runs/{id}.json` |

Planned additions:

| Spec | Story |
|------|-------|
| `reconnect.spec.ts` | 2.3 — WebSocket fault-injection + replay |
| `slo-first-span.spec.ts` | 2.7 — time-to-first-span p95 ≤ 2s |

## Conventions

- **Selectors:** use `data-testid`. Never rely on class names or visible text
  for stable selection.
- **Timeouts:** 30 s for step rendering, 60 s for terminal status. Override
  per-test if a workflow is longer.
- **Retries:** zero (retries mask flakes). The nightly 50× job (Story 2.4)
  measures the rolling flake rate.
- **Backend LLM credentials:** the `code_review` workflow must reach a
  terminal state, which today requires at least one configured LLM provider.
  CI uses `GITHUB_TOKEN` + `models: read` to reach GitHub Models. Locally,
  set `GITHUB_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or any other
  supported provider key before running `npm run test:e2e`. True
  placeholder / no-LLM mode is available through `AGENTIC_NO_LLM=1`; provider-backed E2E still validates real model integration separately.

## CI

See `.github/workflows/ci.yml` — the `e2e-streaming` job runs
`streaming.spec.ts` 5× on every PR. Traces and videos of the first failure
are uploaded as artifacts.
