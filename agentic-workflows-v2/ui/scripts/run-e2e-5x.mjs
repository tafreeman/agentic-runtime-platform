#!/usr/bin/env node
// Epic 2 Story 2.2 — run the Playwright streaming spec 5 times in a row
// and abort on the first failure. Cross-platform replacement for the
// bash for-loop in the plan (needed because contributors run this on
// Windows PowerShell + Git Bash + Linux CI).
import { spawnSync } from 'node:child_process';

const RUNS = Number(process.env.E2E_5X_RUNS ?? 5);

// Use `npm run` rather than `npx`: npm resolves the script through the
// package's local node_modules (reliable on Windows and CI), where npx
// can fall through to a global/cached binary with a stale version.
for (let i = 1; i <= RUNS; i++) {
  console.log(`\n=== E2E run ${i} / ${RUNS} ===`);
  const result = spawnSync('npm', ['run', 'test:e2e'], {
    stdio: 'inherit',
    shell: true,
  });
  if (result.status !== 0) {
    console.error(`\nE2E run ${i} failed with exit code ${result.status}`);
    process.exit(result.status ?? 1);
  }
}

console.log(`\nAll ${RUNS} runs passed.`);
