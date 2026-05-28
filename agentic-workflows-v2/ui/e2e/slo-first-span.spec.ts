import { test, expect } from '@playwright/test';
import { recordLatency, readP95, InsufficientDataError } from './slo-storage';

// Serial because the two tests share mutable state (first-span-latency.json):
// the record-sample test must write before the p95 assertion test reads.
test.describe.serial('SLO: time-to-first-span p95 <= 2s', () => {
  test('record single latency sample', async ({ page }) => {
    await page.goto('/');
    const t0 = Date.now();
    await page.getByRole('link', { name: /workflows/i }).click();
    await page.getByRole('link', { name: /code_review/i }).click();
    await page.getByRole('button', { name: /run/i }).click();

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
