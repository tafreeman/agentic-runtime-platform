import { expect, test } from '@playwright/test';

/**
 * Model-probe surface — "probing models" (/models → ModelFinderPage).
 *
 * On mount the page fires a live provider probe (GET /api/models/probe) that
 * loads the known model catalog with per-provider availability, and re-runs it
 * on "rescan". This test asserts the probe resolves (mode badge + provider
 * rows), a provider expands to reveal its models, and a rescan re-runs without
 * tearing the surface down.
 *
 * Mode-agnostic: the badge reads "no-LLM mode" with no provider keys (the
 * AGENTIC_NO_LLM baseline) and "LLM mode" when keys are present.
 */
test.describe('model probe', () => {
  test('probes providers on load, expands a provider, and re-probes on rescan', async ({
    page,
  }) => {
    await page.goto('/models');

    await expect(
      page.getByRole('heading', { name: /local model fit finder/i }),
    ).toBeVisible();

    // Probe resolved: the mode badge only renders once probe data lands.
    // /api/models/probe does live provider availability + hardware profiling
    // (~6-7s on its own); under parallel workers contending on the single dev
    // backend + Vite module serving this stacks up, so budget generously.
    const badge = page.getByTestId('probe-mode');
    await expect(badge).toBeVisible({ timeout: 30_000 });
    await expect(badge).toHaveText(/no-LLM mode|LLM mode/);

    // At least one provider-backend row rendered from the probe catalog. Each
    // row is a collapsible button carrying a live status word.
    const providerRows = page
      .getByRole('button')
      .filter({ hasText: /ready|no keys|placeholder/i });
    await expect(providerRows.first()).toBeVisible({ timeout: 30_000 });
    expect(
      await providerRows.count(),
      'probe should list at least one provider backend',
    ).toBeGreaterThan(0);

    // Expanding a provider reveals its per-model rows (tier badges T1–T5).
    const firstProvider = providerRows.first();
    await firstProvider.click();
    await expect(firstProvider).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByText(/^T[1-5]$/).first()).toBeVisible({
      timeout: 10_000,
    });

    // Rescan re-runs the probe; the surface survives (badge + rows persist).
    await page.getByRole('button', { name: /rescan/i }).click();
    await expect(badge).toBeVisible();
    await expect(providerRows.first()).toBeVisible();
  });
});
