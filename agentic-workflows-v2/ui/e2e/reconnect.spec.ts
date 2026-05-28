import { expect, test } from '@playwright/test';

/**
 * Epic 2 Story 2.3 — WebSocket fault-injection + reconnect replay.
 *
 * Acceptance criteria:
 *   • Drop the network mid-run (CDP `Network.emulateNetworkConditions` offline)
 *     after step rows reach 3.
 *   • Restore the network and confirm the client reconnects, the server
 *     replays the buffered events, and the UI ends with all 5 step rows.
 *   • Final UI workflow-status matches the server-side run record.
 *
 * Why this works without a `last_seen_index` handshake:
 *   `useWorkflowStream` keys step state by `event.step` in a Map, so duplicate
 *   step events from the server's full replay buffer overwrite — they don't
 *   inflate the rendered row count. If you ever switch step storage to an
 *   append-only list, this test will catch the regression because the count
 *   will exceed 5 after restore.
 *
 * Backend conventions (mirrored from streaming.spec.ts):
 *   • `run_id` is exposed via the `data-run-id` attribute, not text content.
 *   • `/api/runs/{id}.json` returns `status` (not `overall_status`).
 */
test.describe('streaming fault recovery', () => {
  test('client reconnects and replays missed events after network drop', async ({
    page,
    context,
    request,
  }) => {
    await page.goto('/');

    // 1. Navigate: Workflows → code_review detail
    await page.getByTestId('nav-workflows').click();
    await page.getByTestId('workflow-link-code_review').click();

    // 2. Launch the run
    await page.getByTestId('run-button').click();

    // 3. Capture the run id once the run header renders
    const runHeader = page.getByTestId('run-id');
    await expect(runHeader).toBeVisible({ timeout: 15_000 });
    const runId = await runHeader.getAttribute('data-run-id');
    expect(runId, 'data-run-id must be populated after run kickoff').toBeTruthy();

    // 4. Wait until ~3 of the 5 code_review step rows have rendered
    const stepRows = page.locator('[data-testid^="step-row-"]');
    await expect(stepRows.nth(2)).toBeVisible({ timeout: 30_000 });
    expect(await stepRows.count()).toBeGreaterThanOrEqual(3);

    // 5. Drop the network — the existing WebSocket should close, the client
    //    should attempt reconnect with exponential backoff (1s, 2s, …).
    const client = await context.newCDPSession(page);
    await client.send('Network.enable');
    await client.send('Network.emulateNetworkConditions', {
      offline: true,
      latency: 0,
      downloadThroughput: 0,
      uploadThroughput: 0,
    });

    // Hold offline long enough for the WS close to propagate AND for the
    // backend to publish more step events into the replay buffer. The first
    // reconnect attempt fires ~1s after close; we want to be still offline
    // when it fails so the client backs off and retries after restore.
    await page.waitForTimeout(2500);

    // 6. Restore network — client reconnects, server replays buffered events.
    await client.send('Network.emulateNetworkConditions', {
      offline: false,
      latency: 0,
      downloadThroughput: -1,
      uploadThroughput: -1,
    });

    // 7. After reconnect, all 5 steps must render (the replay buffer covers
    //    the gap). code_review.yaml steps: parse_code, style_check,
    //    complexity_analysis, review_code, generate_summary.
    const EXPECTED_STEP_COUNT = 5;
    await expect(stepRows).toHaveCount(EXPECTED_STEP_COUNT, { timeout: 45_000 });

    // 8. Workflow reaches a terminal status in the UI.
    const workflowStatus = page.getByTestId('workflow-status');
    await expect(workflowStatus).toHaveText(
      /success|failed|error|completed/i,
      { timeout: 60_000 },
    );
    const uiStatus = (await workflowStatus.textContent())?.trim().toLowerCase() ?? '';
    expect(uiStatus, 'workflow-status must render non-empty text').toBeTruthy();

    // 9. UI status agrees with the server record.
    const apiResponse = await request.get(`http://127.0.0.1:8010/api/runs/${runId}.json`);
    expect(
      apiResponse.ok(),
      `GET /api/runs/${runId}.json should succeed (got ${apiResponse.status()})`,
    ).toBe(true);
    const apiRun = await apiResponse.json();
    // Contract: `/api/runs/{id}.json` returns `status` (verified against
    // routes/runs.py::get_run). `overall_status` is an unrelated internal
    // evaluation-scoring field; do NOT accept it as a fallback.
    const apiStatus = String(apiRun.status ?? '').trim().toLowerCase();
    expect(apiStatus, 'server run record must carry a status').toBeTruthy();

    // Canonicalise both statuses because the UI renders human-readable text
    // (`completed`/`success`/`ok`) while the API emits the enum literal.
    // This is terminal-state bucketing only, not a loose substring match.
    const canonicalise = (raw: string): 'success' | 'failed' | 'other' => {
      const s = raw.trim().toLowerCase();
      if (/^(success|completed|ok)$/.test(s)) return 'success';
      if (/^(failed|error)$/.test(s)) return 'failed';
      return 'other';
    };
    expect(canonicalise(uiStatus)).toBe(canonicalise(apiStatus));
  });
});
