import { expect, test } from '@playwright/test';

/** Terminal workflow states surfaced by the live stream. */
const TERMINAL = /completed|success|failed|error/i;

/**
 * Changing run parameters and launching — "changing the parameters and
 * running" (/workflows/code_review).
 *
 * Flips `review_depth` from its schema default ("standard") to the non-default
 * "deep", sets a distinctive `code_file`, launches, and asserts the *edited*
 * parameters round-trip into the persisted server run record. This proves the
 * run-config form → POST /api/run → run log path carries the user's edits
 * rather than silently submitting defaults.
 */
test.describe('run parameters', () => {
  test('edited inputs propagate through to the server run record', async ({
    page,
    request,
  }) => {
    await page.goto('/workflows/code_review');

    // The select starts at the schema default.
    const depth = page.getByTestId('input-review_depth');
    await expect(depth).toHaveValue('standard');

    // Edit both inputs: a distinctive path + a non-default depth.
    const codeFile = 'e2e/param-change-sample.py';
    await page.getByTestId('input-code_file').fill(codeFile);
    await depth.selectOption('deep');
    await expect(depth).toHaveValue('deep');

    await page.getByTestId('run-button').click();

    // Capture the run id from the live view.
    await expect(page).toHaveURL(/\/live\//, { timeout: 15_000 });
    const runHeader = page.getByTestId('run-id');
    await expect(runHeader).toBeVisible({ timeout: 15_000 });
    const runId = await runHeader.getAttribute('data-run-id');
    expect(runId, 'run-id must expose a data-run-id after kickoff').toBeTruthy();

    // Let the run reach a terminal state so the record is fully written.
    await expect(page.getByTestId('workflow-status')).toHaveText(TERMINAL, {
      timeout: 60_000,
    });

    // The edited, non-default parameters must be exactly what ran.
    const rec = await request.get(`/api/runs/${runId}.json`);
    expect(rec.ok(), `GET /api/runs/${runId}.json -> ${rec.status()}`).toBe(true);
    const run = await rec.json();
    expect(run.inputs).toMatchObject({
      code_file: codeFile,
      review_depth: 'deep',
    });
    expect(String(run.status).toLowerCase()).toMatch(/success|completed/);
  });
});
