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

    // Guard: node visibility is only meaningful once the ReactFlow canvas
    // itself has non-zero dimensions — a zero-sized canvas hides every node,
    // and asserting on nodes first turns a container-sizing failure into a
    // misleading "node hidden" timeout (the PR #203 flake's failure shape).
    const flowCanvas = page.locator('.react-flow').first();
    await expect
      .poll(
        async () => {
          const box = await flowCanvas.boundingBox();
          return box ? Math.min(box.width, box.height) : 0;
        },
        {
          timeout: 15_000,
          message: 'ReactFlow canvas must acquire a non-zero size',
        }
      )
      .toBeGreaterThan(0);

    // The live DAG renders (ReactFlow nodes carry data-testid="dag-node-<id>")
    // and mounts every step from the definition — not just the entry node.
    // ReactFlow keeps all nodes in the DOM (no onlyRenderVisibleElements), so
    // the count is a stable cross-check against the DAG's step_count.
    const dagNodes = page.locator('[data-testid^="dag-node-"]');
    await expect(dagNodes.first()).toBeVisible({ timeout: 20_000 });
    await expect(dagNodes).toHaveCount(EXPECTED_STEP_COUNT);

    // UI reaches a terminal status.
    const status = page.getByTestId('workflow-status');
    await expect(status).toHaveText(TERMINAL, { timeout: 60_000 });
    const uiStatus = (await status.textContent())?.trim() ?? '';

    // Server run record agrees on identity, shape, and terminal state.
    const rec = await request.get(`/api/runs/${runId}.json`);
    expect(rec.ok(), `GET /api/runs/${runId}.json -> ${rec.status()}`).toBe(true);
    const run = await rec.json();
    expect(run.run_id, 'record identity must match the launched run').toBe(runId);
    expect(run.workflow_name).toBe('fullstack_generation');
    expect(run.step_count).toBe(EXPECTED_STEP_COUNT);
    expect(run.status, 'server record must carry a status').toBeTruthy();
    // UI vs. server reconciled by canonical bucket — deliberately NOT pinned to
    // `success`, because a no_llm fullstack_generation run can legitimately end
    // `failed`; the buckets must still agree (a failed run reads `failed` on
    // both sides, and `error`/`completed` map to different buckets so they
    // cannot agree by substring).
    expect(bucket(uiStatus)).toBe(bucket(String(run.status)));
  });
});
