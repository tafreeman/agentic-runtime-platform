import { expect, test } from '@playwright/test';

/**
 * Model-probe surface — "probing models" (/models → ModelFinderPage).
 *
 * On mount the page fires a live provider probe (GET /api/models/probe) that
 * loads the known model catalog with per-provider availability, and re-runs it
 * on "rescan". This test asserts the probe resolves (mode badge + provider
 * rows), a provider expands to reveal its models, and a rescan genuinely
 * re-fires the probe without tearing the surface down.
 *
 * Mode-agnostic, but not tautological: instead of accepting either badge
 * string, the badge is reconciled against the `no_llm_mode` field of the probe
 * response it is actually rendered from. The /models/probe route reports
 * `is_agentic_no_llm_enabled()` — a distinct source from /health's
 * `effective_no_llm_mode()` — so the probe response is the only sound oracle
 * for this badge. A badge that disagreed with its own backend record fails.
 */
test.describe('model probe', () => {
  test('probes providers on load, expands a provider, and re-probes on rescan', async ({
    page,
  }) => {
    // Capture the on-mount probe response (the page's own request — no extra
    // backend load) so the mode badge and provider-row count can be reconciled
    // against the exact record the UI rendered from. /api/models/probe does
    // live provider availability + hardware profiling (~6-7s on its own); under
    // parallel workers contending on the single dev backend + Vite module
    // serving this stacks up, so budget generously.
    const firstProbe = page.waitForResponse(
      (r) =>
        r.url().includes('/api/models/probe') &&
        r.request().method() === 'GET',
      { timeout: 30_000 },
    );
    await page.goto('/models');
    const probeResponse = await firstProbe;
    expect(
      probeResponse.ok(),
      `GET /api/models/probe -> ${probeResponse.status()}`,
    ).toBe(true);
    const probeBody = (await probeResponse.json()) as {
      no_llm_mode: boolean;
      models?: ReadonlyArray<{ provider: string }>;
      available_providers?: ReadonlyArray<string>;
      unavailable_providers?: ReadonlyArray<string>;
    };
    const expectedMode = probeBody.no_llm_mode ? 'no-LLM mode' : 'LLM mode';

    await expect(
      page.getByRole('heading', { name: /model catalog/i }),
    ).toBeVisible();

    // Probe resolved: the mode badge only renders once probe data lands, and
    // its text must match the mode the backend actually reported (not merely
    // "one of the two legal strings").
    const badge = page.getByTestId('probe-mode');
    await expect(badge).toBeVisible({ timeout: 30_000 });
    await expect(badge).toHaveText(expectedMode);

    // Exactly one collapsible provider-backend row renders per provider in
    // the union the page itself derives: keyed providers, un-keyed providers
    // (visible as "no keys" instead of disappearing), and providers with
    // detected models. Rows are counted by their stable testid (a text
    // filter is unsound here: in no-LLM mode the placeholder model id itself
    // contains "placeholder", matching unrelated catalog buttons), then the
    // first row's live status word is verified separately.
    const providerRows = page.getByTestId(/^provider-row-/);
    const distinctProviders = new Set([
      ...(probeBody.available_providers ?? []),
      ...(probeBody.unavailable_providers ?? []),
      ...(probeBody.models ?? []).map((model) => model.provider),
    ]).size;
    expect(
      distinctProviders,
      'probe should return at least one provider backend',
    ).toBeGreaterThan(0);
    await expect(providerRows).toHaveCount(distinctProviders);
    await expect(providerRows.first()).toContainText(
      /ready|no keys|not detected|placeholder/i,
    );

    // Expanding a provider reveals its per-model rows, each tagged with a tier
    // badge. Tiers span T0–T5 in the live catalog (local/uncategorized backends
    // are T0 and dominate the largest provider), so match any single-digit tier
    // rather than only T1–T5 — otherwise the assertion silently depends on the
    // first provider happening to carry a T1–T5 model.
    const firstProvider = providerRows.first();
    await firstProvider.click();
    await expect(firstProvider).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByText(/^T[0-9]$/).first()).toBeVisible({
      timeout: 10_000,
    });

    // Rescan must genuinely re-run the probe, not just leave the surface up:
    // wait for a fresh GET /api/models/probe triggered by the click, then
    // confirm the badge (still reconciled) and rows persist through it.
    const reprobe = page.waitForResponse(
      (r) =>
        r.url().includes('/api/models/probe') &&
        r.request().method() === 'GET',
      { timeout: 30_000 },
    );
    await page.getByRole('button', { name: /rescan/i }).click();
    const reprobeResponse = await reprobe;
    expect(
      reprobeResponse.ok(),
      `rescan GET /api/models/probe -> ${reprobeResponse.status()}`,
    ).toBe(true);
    await expect(badge).toHaveText(expectedMode);
    await expect(providerRows.first()).toBeVisible();
  });
});
