import { expect, test } from '@playwright/test';

/**
 * Settings compatibility route — /settings redirects into the consolidated
 * Model Router at /models?tab=providers. Provider and tier controls remain
 * first-class tab panels instead of a second settings shell.
 *
 * The Model Router hosts ProviderPanel
 * (GET/PUT /api/settings/providers) lists the configured provider endpoints as
 * cards — each with an on/off switch (role=switch) — above an always-present
 * "add provider" type picker built from a static preset list. TierBoard
 * (GET/PUT /api/settings/tiers) renders one card per model tier ("T<n>") with
 * its routing order and capability tags. This spec is READ-ONLY: it loads the
 * page and asserts the structure renders, and probes the two backing endpoints
 * for their shape. It never saves, toggles, reranks, or edits capabilities — no
 * mutation of persisted settings.
 *
 * Neither panel exposes `data-testid`s, so the anchors here are the tablist,
 * section landmarks (`<section aria-label>` → role=region), headings, and the
 * stable aria-labels the controls attach.
 *
 * Robust to an empty OR populated surface: the DOM assertions are grounded in
 * the live API payload and branch on it — the no-LLM baseline ships zero user
 * providers (so the empty-state strip renders) yet a non-empty env-configured
 * set and a full config-driven tier table, so this spec stays green either way.
 * Where the surface is populated it reconciles the rendered DOM against the
 * payload (the env-provider strip echoes the id list; one routing row renders
 * per model in each tier's effective chain) so a dropped or duplicated entry
 * fails rather than passing on mere presence.
 */
test.describe('settings', () => {
  test('renders the provider-endpoint and tier controls', async ({ page }) => {
    await page.goto('/settings');

    // Legacy deep links land on the canonical Model Router provider tab.
    await expect(page).toHaveURL(/\/models\?tab=providers$/);
    await expect(page.getByRole('heading', { level: 1, name: /^providers$/i })).toBeVisible();

    // The sidebar marks the consolidated Model Router surface active.
    const modelRouterLink = page
      .getByRole('navigation')
      .getByRole('link', { name: /model router/ });
    await expect(modelRouterLink).toHaveAttribute('aria-current', 'page');

    // ── Provider endpoints panel ── (static chrome, independent of the fetch)
    const providerRegion = page.getByRole('region', { name: 'provider endpoints' });
    await expect(providerRegion).toBeVisible();
    await expect(providerRegion.getByText(/endpoint registry/i)).toBeVisible();
    // The add-provider type picker is built from a fixed preset list, so these
    // buttons render regardless of how many providers are configured.
    await expect(
      providerRegion.getByRole('button', { name: 'Add OpenAI provider' }),
    ).toBeVisible();
    await expect(
      providerRegion.getByRole('button', { name: 'Add Custom endpoint provider' }),
    ).toBeVisible();

    // ── Tier routing panel ── switch tabs, preserving URL-addressable state.
    await page.getByRole('tab', { name: 'Tiers' }).click();
    await expect(page).toHaveURL(/\/models\?tab=tiers$/);
    const tierRegion = page.getByRole('region', { name: 'tier routing' });
    await expect(tierRegion).toBeVisible();
    await expect(
      tierRegion.getByRole('heading', { level: 1, name: /^model tiers$/i }),
    ).toBeVisible();
  });

  test('settings endpoints expose the provider and tier shapes the page renders', async ({
    page,
    request,
  }) => {
    await page.goto('/settings');

    // Compatibility redirect and provider header render independently of data.
    await expect(page).toHaveURL(/\/models\?tab=providers$/);
    await expect(
      page.getByRole('heading', { level: 1, name: /^providers$/i }),
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

    // ── Env-configured strip ── distinct from user providers: the panel echoes
    // the provider ids discovered from environment credentials. The no-LLM
    // baseline reports a non-empty, sorted set, so the strip renders and must
    // list exactly what the API returns (reconciled against the payload); an
    // empty set hides the strip entirely.
    if (providers.env_configured_providers.length > 0) {
      const envStrip = providerRegion.getByText(/configured via environment/i);
      await expect(envStrip).toBeVisible({ timeout: 15_000 });
      await expect(envStrip).toContainText(
        providers.env_configured_providers.join(', '),
      );
    } else {
      await expect(
        providerRegion.getByText(/configured via environment/i),
      ).toHaveCount(0);
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
    // board reads (default / override / effective). Loop is empty-safe; sum the
    // effective-chain lengths so the rendered routing rows can be reconciled.
    let effectiveRows = 0;
    for (const tier of tiers.tiers) {
      expect(typeof tier.tier).toBe('number');
      expect(Array.isArray(tier.default_chain)).toBe(true);
      expect(Array.isArray(tier.override)).toBe(true);
      expect(Array.isArray(tier.effective)).toBe(true);
      effectiveRows += tier.effective.length;
    }

    await page.getByRole('tab', { name: 'Tiers' }).click();
    const tierRegion = page.getByRole('region', { name: 'tier routing' });
    if (tiers.tiers.length > 0) {
      // Populated: one card per tier, each showing a "T<n>" label. Count tracks
      // the API payload so it adapts if the tier set changes.
      await expect(tierRegion.getByText(/^T\d+$/)).toHaveCount(tiers.tiers.length, {
        timeout: 15_000,
      });
      // Each model in a tier's effective chain renders exactly one capability-
      // editor row (aria-label "Edit capabilities for <model> in tier <n>").
      // Reconcile the rendered row count against the summed effective chains so
      // the board can't silently drop or duplicate a routed model. Empty-safe:
      // resolves to 0 rows when every chain is empty (e.g. a bare tier 0).
      await expect(
        tierRegion.getByRole('button', {
          name: /Edit capabilities for .+ in tier \d+/,
        }),
      ).toHaveCount(effectiveRows, { timeout: 15_000 });
    } else {
      // No tiers configured — only the panel header renders.
      await expect(
        tierRegion.getByRole('heading', { level: 1, name: /^model tiers$/i }),
      ).toBeVisible();
    }
  });
});
