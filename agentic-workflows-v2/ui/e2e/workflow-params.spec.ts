import { expect, test } from '@playwright/test';

/** Terminal workflow-status words the live pill (`workflow-status`) can show.
 *  `success` is normalised to `completed` upstream so it never appears
 *  verbatim; anchoring keeps the non-terminal states (connecting/running/
 *  evaluating) from matching on a substring. */
const TERMINAL = /^(completed|failed|error)$/i;

/** Canonicalise UI text vs. the API enum into terminal buckets so `error`
 *  cannot silently agree with `completed` via a loose substring match. */
function bucket(raw: string): 'success' | 'failed' | 'other' {
  const s = raw.trim().toLowerCase();
  if (/^(success|completed|ok)$/.test(s)) return 'success';
  if (/^(failed|error)$/.test(s)) return 'failed';
  return 'other';
}

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
    const status = page.getByTestId('workflow-status');
    await expect(status).toHaveText(TERMINAL, { timeout: 60_000 });
    const uiStatus = (await status.textContent())?.trim() ?? '';

    // Reconcile the record's identity first, so the inputs assertion below
    // cannot pass against some other run's log.
    const rec = await request.get(`/api/runs/${runId}.json`);
    expect(rec.ok(), `GET /api/runs/${runId}.json -> ${rec.status()}`).toBe(true);
    const run = await rec.json();
    expect(run.run_id, 'record identity must match the launched run').toBe(runId);
    expect(run.workflow_name).toBe('code_review');

    // The edited, non-default parameters must be exactly what ran.
    expect(run.inputs).toMatchObject({
      code_file: codeFile,
      review_depth: 'deep',
    });

    // UI terminal state and the persisted status must agree on one canonical
    // bucket, and a no_llm code_review run resolves deterministically to
    // success — a stronger check than matching a status substring.
    const serverBucket = bucket(String(run.status));
    expect(bucket(uiStatus)).toBe(serverBucket);
    expect(serverBucket).toBe('success');
  });
});
