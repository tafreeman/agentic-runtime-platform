import { test, expect } from '@playwright/test';
import { recordLatency, readP95, InsufficientDataError } from './slo-storage';

// Serial because the two tests share mutable state (first-span-latency.json):
// the record-sample test must write before the p95 assertion test reads.
test.describe.serial('SLO: time-to-first-span p95 <= 2s', () => {
  // The SLO is defined on an isolated single-spec run (the nightly's dedicated
  // "Record time-to-first-span sample" step). The nightly's full-suite 5x
  // flake loop (scripts/run-e2e-5x.mjs sets E2E_REPEAT_RUN) runs this spec
  // beside 3 other Playwright workers, where the sample is 4-7s of CPU
  // contention, not a latency regression. Those samples would pollute the
  // rolling window and trip the 2000ms gate (nightly red since 2026-10-19).
  test.skip(
    process.env.E2E_REPEAT_RUN === '1',
    'SLO sample is only meaningful in an isolated run; skipped under the repeat-run flake loop',
  );

  test('record single latency sample', async ({ page }) => {
    await page.goto('/');
    const t0 = Date.now();
    await page.getByTestId('nav-workflows').click();
    await page.getByTestId('workflow-link-code_review').click();
    await page.getByTestId('run-button').click();

    // Wait for first DAG node render
    await expect(page.locator('[data-testid^="dag-node-"]').first()).toBeVisible();
    const latency = Date.now() - t0;

    await recordLatency(latency);
  });

  test('rolling 7-day p95 is within budget', async () => {
    // Bootstrap semantics: the first ~10 nightlies after an slo-data branch
    // reset will not have enough samples to compute a meaningful p95. Treat
    // that as "deferred", not "passed" — the silent-pass on empty data was the
    // Sprint B #2 bug. readP95 throws InsufficientDataError; we convert to a
    // skip so the nightly continues. Once the window is populated, this
    // becomes a hard gate.
    try {
      const p95 = await readP95({ windowDays: 7 });
      expect(p95, `p95=${p95}ms exceeds 2000ms budget`).toBeLessThanOrEqual(2000);
    } catch (err) {
      if (err instanceof InsufficientDataError) {
        test.skip(true, err.message);
        return;
      }
      throw err;
    }
  });
});
