import { expect, test } from '@playwright/test';

/** Terminal workflow states surfaced by the live stream. */
const TERMINAL = /completed|success|failed|error/i;

/** Canonicalise UI text vs. the API enum into terminal buckets so `error`
 *  cannot silently agree with `completed` via a loose substring match. */
function bucket(raw: string): 'success' | 'failed' | 'other' {
  const s = raw.trim().toLowerCase();
  if (/^(success|completed|ok)$/.test(s)) return 'success';
  if (/^(failed|error)$/.test(s)) return 'failed';
  return 'other';
}

/**
 * Full-stack workflow run — "making a full-stack workflow".
 *
 * Drives the whole stack end-to-end against the `fullstack_generation`
 * workflow (an 8-step generate → review → test DAG): the SPA POSTs /api/run,
 * the server executes the DAG and streams step events over the WebSocket, the
 * client redirects to /live/{run_id}, the graph renders, and the run reaches a
 * terminal status that agrees with the persisted server run record.
 *
 * If the fullstack_generation definition changes step count, update
 * EXPECTED_STEP_COUNT.
 */
test.describe('full-stack workflow run', () => {
  const EXPECTED_STEP_COUNT = 8;

  test('runs fullstack_generation end-to-end and matches the server record', async ({
    page,
    request,
  }) => {
    await page.goto('/workflows/fullstack_generation');

    // feature_spec is the only required free input; tech_stack has a
    // server-side default object, so leaving it blank is sufficient.
    await page
      .getByTestId('input-feature_spec')
      .fill('a todo list with add and complete');
    await page.getByTestId('run-button').click();

    // Redirected to the live run view; capture the freshly minted run id.
    await expect(page).toHaveURL(/\/live\//, { timeout: 15_000 });
    const runHeader = page.getByTestId('run-id');
    await expect(runHeader).toBeVisible({ timeout: 15_000 });
    const runId = await runHeader.getAttribute('data-run-id');
    expect(runId, 'run-id must expose a data-run-id after kickoff').toBeTruthy();

    // The live DAG renders (ReactFlow nodes carry data-testid="dag-node-<id>").
    await expect(
      page.locator('[data-testid^="dag-node-"]').first(),
    ).toBeVisible({ timeout: 20_000 });

    // UI reaches a terminal status.
    const status = page.getByTestId('workflow-status');
    await expect(status).toHaveText(TERMINAL, { timeout: 60_000 });
    const uiStatus = (await status.textContent())?.trim() ?? '';

    // Server run record agrees on identity, shape, and terminal state.
    const rec = await request.get(`/api/runs/${runId}.json`);
    expect(rec.ok(), `GET /api/runs/${runId}.json -> ${rec.status()}`).toBe(true);
    const run = await rec.json();
    expect(run.workflow_name).toBe('fullstack_generation');
    expect(run.step_count).toBe(EXPECTED_STEP_COUNT);
    expect(run.status, 'server record must carry a status').toBeTruthy();
    expect(bucket(uiStatus)).toBe(bucket(String(run.status)));
  });
});
