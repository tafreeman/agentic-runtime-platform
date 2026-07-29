# UI end-to-end tests

These Playwright tests exercise the React dashboard against a real local
FastAPI process.

## Run

From `agentic-workflows-v2/ui/`:

```powershell
npm install
npx playwright install chromium
npm run test:e2e
```

Other modes:

```powershell
npm run test:e2e -- streaming.spec.ts
npm run test:e2e:5x
npm run test:e2e:ui
```

`test:e2e:5x` is the repeated CI flake gate.

## Test environment

`playwright.config.ts` starts and owns:

- FastAPI on `127.0.0.1:8010`;
- Vite on `127.0.0.1:5173`.

It sets `AGENTIC_NO_LLM=1` for the backend and does not reuse existing
services. Stop anything already using those ports before running the suite.
Provider credentials are not required for this default E2E path.

The Python command uses `agentic-workflows-v2/.venv` when present and otherwise
uses `python` from `PATH`. Install the runtime and its test dependencies before
starting Playwright.

## Coverage

The current specs cover:

- application shell and navigation;
- workflow parameters and run submission;
- run list and run detail views;
- live streaming, reconnect behavior, and first-span timing;
- datasets and evaluation pages;
- model probe and settings pages;
- chat playground behavior.

The exact list is the `*.spec.ts` files in this directory.

## Conventions

- Prefer roles, labels, and `data-testid` selectors over CSS class names.
- Keep provider calls disabled unless a test is explicitly marked and isolated
  as a live integration test.
- Use route mocks only for the boundary a test owns; do not mock the UI logic
  under test.
- Keep retries at zero. Repeated CI runs measure flakes instead of hiding
  them.
- Preserve Playwright traces, screenshots, and videos from failures.

The test timeout is 90 seconds and assertion timeout is 10 seconds by default.
Override them only when the behavior itself has a longer documented bound.

## CI

The root `.github/workflows/ci.yml` runs the repeated E2E gate and uploads
failure artifacts. `.github/workflows/nightly.yml` runs additional repeated
streaming checks.
