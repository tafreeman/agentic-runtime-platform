import { expect, test } from '@playwright/test';

/**
 * Settings surface — "providers & tiers" (/settings → SettingsPage).
 *
 * SettingsPage stacks two panels. ProviderPanel
 * (GET/PUT /api/settings/providers) lists the configured provider endpoints as
 * cards — each with an on/off switch (role=switch) — above an always-present
 * "add provider" type picker built from a static preset list. TierBoard
 * (GET/PUT /api/settings/tiers) renders one card per model tier ("T<n>") with
 * its routing order and capability tags. This spec is READ-ONLY: it loads the
 * page and asserts the structure renders, and probes the two backing endpoints
 * for their shape. It never saves, toggles, reranks, or edits capabilities — no
 * mutation of persisted settings.
 *
 * Neither panel exposes `data-testid`s, so the anchors here are the section
 * landmarks (`<section aria-label>` → role=region), the h1, the static section
 * headers, and the stable aria-labels the controls attach. Nav links carry a
 * zero-padded ordinal prefix ("08 providers & tiers"), so the sidebar link is
 * matched by regex scoped to the navigation landmark.
 *
 * Robust to an empty OR populated surface: the DOM assertions are grounded in
 * the live API payload and branch on it — the no-LLM baseline ships zero user
 * providers (so the empty-state strip renders) but a full config-driven tier
 * table, and this spec stays green either way.
 */
test.describe('settings', () => {
  test('renders the provider-endpoint and tier controls', async ({ page }) => {
    await page.goto('/settings');

    // Page mounted on the settings route: the h1 and its mono subtitle strip.
    await expect(page.getByRole('heading', { level: 1, name: /^settings$/i })).toBeVisible();
    await expect(page.getByText(/capability tags/i)).toBeVisible();

    // The sidebar marks settings active. The link's accessible name carries the
    // "08" ordinal prefix, so match by regex within the nav landmark.
    const settingsLink = page
      .getByRole('navigation')
      .getByRole('link', { name: /providers & tiers/ });
    await expect(settingsLink).toHaveAttribute('aria-current', 'page');

    // ── Provider endpoints panel ── (static chrome, independent of the fetch)
    const providerRegion = page.getByRole('region', { name: 'provider endpoints' });
    await expect(providerRegion).toBeVisible();
    // Header text — scoped .first() because the empty-state strip ("no provider
    // endpoints configured") also matches this case-insensitive pattern; the
    // panel header renders first in DOM order.
    await expect(providerRegion.getByText(/PROVIDER ENDPOINTS/i).first()).toBeVisible();
    // The add-provider type picker is built from a fixed preset list, so these
    // buttons render regardless of how many providers are configured.
    await expect(
      providerRegion.getByRole('button', { name: 'Add OpenAI provider' }),
    ).toBeVisible();
    await expect(
      providerRegion.getByRole('button', { name: 'Add Custom endpoint provider' }),
    ).toBeVisible();

    // ── Tier routing panel ── (header renders unconditionally)
    const tierRegion = page.getByRole('region', { name: 'tier routing' });
    await expect(tierRegion).toBeVisible();
    await expect(tierRegion.getByText(/MODEL TIERS/i)).toBeVisible();
  });

  test('settings endpoints expose the provider and tier shapes the page renders', async ({
    page,
    request,
  }) => {
    await page.goto('/settings');

    // Header renders immediately (independent of the data fetch).
    await expect(
      page.getByRole('heading', { level: 1, name: /^settings$/i }),
    ).toBeVisible();

    // ── Providers ── the list the panel maps into cards, the closed
    // provider-type enum that drives the "add provider" buttons, and the
    // env-configured strip. GET /api/settings/providers is proxied via Vite.
    const providersRes = await request.get('/api/settings/providers');
    expect(
      providersRes.ok(),
      `GET /api/settings/providers -> ${providersRes.status()}`,
    ).toBe(true);
    const providers = await providersRes.json();
    expect(Array.isArray(providers.providers)).toBe(true);
    expect(Array.isArray(providers.provider_types)).toBe(true);
    expect(Array.isArray(providers.env_configured_providers)).toBe(true);
    // provider_types is a closed enum; "custom" is a stable member.
    expect(providers.provider_types).toContain('custom');

    const providerRegion = page.getByRole('region', { name: 'provider endpoints' });
    if (providers.providers.length > 0) {
      // Populated: one on/off switch per configured provider, and no empty copy.
      // Tie the rendered switch count to the API rather than pinning a number.
      await expect(providerRegion.getByRole('switch')).toHaveCount(
        providers.providers.length,
        { timeout: 15_000 },
      );
      await expect(
        providerRegion.getByText(/no provider endpoints configured/i),
      ).toHaveCount(0);
    } else {
      // Empty: the panel shows its terminal-style empty-state strip.
      await expect(
        providerRegion.getByText(/no provider endpoints configured/i),
      ).toBeVisible({ timeout: 15_000 });
    }

    // ── Tiers ── the routing table the board renders, the model capability
    // catalog, and the known capability tags.
    const tiersRes = await request.get('/api/settings/tiers');
    expect(tiersRes.ok(), `GET /api/settings/tiers -> ${tiersRes.status()}`).toBe(true);
    const tiers = await tiersRes.json();
    expect(Array.isArray(tiers.tiers)).toBe(true);
    expect(Array.isArray(tiers.models)).toBe(true);
    expect(Array.isArray(tiers.known_capabilities)).toBe(true);
    // Every tier chain carries a numeric tier and the three routing arrays the
    // board reads (default / override / effective). Loop is empty-safe.
    for (const tier of tiers.tiers) {
      expect(typeof tier.tier).toBe('number');
      expect(Array.isArray(tier.default_chain)).toBe(true);
      expect(Array.isArray(tier.override)).toBe(true);
      expect(Array.isArray(tier.effective)).toBe(true);
    }

    const tierRegion = page.getByRole('region', { name: 'tier routing' });
    if (tiers.tiers.length > 0) {
      // Populated: one card per tier, each showing a "T<n>" label. Count tracks
      // the API payload so it adapts if the tier set changes.
      await expect(tierRegion.getByText(/^T\d+$/)).toHaveCount(tiers.tiers.length, {
        timeout: 15_000,
      });
    } else {
      // No tiers configured — only the panel header renders.
      await expect(tierRegion.getByText(/MODEL TIERS/i)).toBeVisible();
    }
  });
});
