import { expect, test } from '@playwright/test';

/**
 * Epic 2 Story 2.2 — Streaming PR gate.
 *
 * Acceptance criteria:
 *   • code_review workflow renders ≥5 step rows (one per step) within 30 s
 *   • a final workflow status is displayed (success / failed / error)
 *   • UI final status matches the server-side run record
 *
 * Backend corrections vs plan:
 *   • Health endpoint is `/api/health` (not `/health`)
 *   • Run details endpoint returns `status` (not `overall_status`)
 *   • `run_id` is exposed via `data-run-id` attribute on the run header
 *     (not rendered as visible text)
 */
test.describe('streaming PR gate', () => {
  test('code_review streams step events and matches server run record', async ({
    page,
    request,
  }) => {
    await page.goto('/');

    // 1. Navigate: Workflows → code_review detail
    await page.getByTestId('nav-workflows').click();
    await page.getByTestId('workflow-link-code_review').click();

    // 2. Launch the run
    await page.getByTestId('run-button').click();

    // 3. Run header must render with the new run id
    const runHeader = page.getByTestId('run-id');
    await expect(runHeader).toBeVisible({ timeout: 15_000 });
    const runId = await runHeader.getAttribute('data-run-id');
    expect(runId, 'data-run-id must be populated after run kickoff').toBeTruthy();

    // 4. All 5 code_review steps must render within 30 s.
    //    code_review.yaml defines: parse_code, style_check, complexity_analysis,
    //    review_code, generate_summary (generate_summary is conditional but runs
    //    by default when review_depth != 'quick'). If the workflow definition
    //    changes, update EXPECTED_STEP_COUNT.
    const EXPECTED_STEP_COUNT = 5;
    const stepRows = page.locator('[data-testid^="step-row-"]');
    await expect(stepRows).toHaveCount(EXPECTED_STEP_COUNT, { timeout: 30_000 });

    // 5. A terminal workflow status is shown
    const workflowStatus = page.getByTestId('workflow-status');
    await expect(workflowStatus).toHaveText(
      /success|failed|error|completed/i,
      { timeout: 60_000 },
    );
    const uiStatus = (await workflowStatus.textContent())?.trim().toLowerCase() ?? '';
    expect(uiStatus, 'workflow-status must render non-empty text').toBeTruthy();

    // 6. UI status agrees with the server record. The runs endpoint accepts
    //    the run-log filename; the server writes `<run_id>.json`.
    const apiResponse = await request.get(`http://127.0.0.1:8010/api/runs/${runId}.json`);
    expect(
      apiResponse.ok(),
      `GET /api/runs/${runId}.json should succeed (got ${apiResponse.status()})`,
    ).toBe(true);
    const apiRun = await apiResponse.json();
    expect(apiRun.status, 'server run record must carry a status').toBeTruthy();

    // Canonicalise both statuses to `success | failed` so `error` on one side
    // and `completed` on the other cannot silently agree via substring match.
    const canonicalise = (raw: string): 'success' | 'failed' | 'other' => {
      const s = raw.trim().toLowerCase();
      if (/^(success|completed|ok)$/.test(s)) return 'success';
      if (/^(failed|error)$/.test(s)) return 'failed';
      return 'other';
    };
    expect(canonicalise(uiStatus)).toBe(canonicalise(String(apiRun.status)));
  });
});
