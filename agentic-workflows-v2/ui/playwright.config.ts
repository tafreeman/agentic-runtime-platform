/// <reference types="node" />

import { defineConfig, devices } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// package.json sets "type": "module", so Playwright loads this config as ESM
// where `__dirname` is undefined. Derive the dirname from import.meta.url.
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const venvCandidate = process.platform === 'win32'
  ? path.join('..', '.venv', 'Scripts', 'python.exe')
  : path.join('..', '.venv', 'bin', 'python');

// Existence is checked relative to the backend's `cwd` (`..` from the ui dir),
// matching what `webServer.command` resolves at spawn time. CI environments
// (GitHub Actions) install Python via setup-python without creating a `.venv`,
// so fall back to the system `python` on PATH when the venv binary is absent.
const venvAbsolute = path.resolve(__dirname, '..', venvCandidate);
const venvPython = fs.existsSync(venvAbsolute) ? venvCandidate : 'python';

/**
 * Playwright config for streaming E2E (Epic 2 Story 2.2).
 *
 * - Spawns backend + frontend via `webServer` so contributors can run
 *   `npm run test:e2e` with no prior setup.
 * - Backend health check on `/api/health`.
 * - `reuseExistingServer` locally so dev servers on 8010/5173 are reused.
 * - No retries: flake rate is observable, not masked.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [
    ['list'],
    ['json', { outputFile: 'e2e-results.json' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      name: 'backend',
      command: `${venvPython} -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010`,
      cwd: '..',
      url: 'http://127.0.0.1:8010/api/health',
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'frontend',
      command: 'npm run dev -- --host 127.0.0.1 --strictPort',
      url: 'http://127.0.0.1:5173',
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
