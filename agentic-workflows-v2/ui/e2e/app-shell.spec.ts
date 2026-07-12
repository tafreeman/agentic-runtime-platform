import { expect, test } from '@playwright/test';

/**
 * App-shell smoke test — "loading the app".
 *
 * Verifies the SPA boots, the backend is reachable through the Vite `/api`
 * proxy, and the primary navigation renders and routes. Uses role/name
 * anchors for the shell chrome (stable by design) and a proxied `/api/health`
 * probe so the test is agnostic to the backend port.
 */
test.describe('app shell', () => {
  test('loads the console, reaches the backend, and routes via the sidebar', async ({
    page,
    request,
  }) => {
    await page.goto('/');

    // SPA mounted: the brand link and the sidebar destinations are present.
    // Nav labels carry a zero-padded ordinal prefix ("01 overview"), so match
    // by regex and scope to the navigation landmark to stay unambiguous
    // against content links on the dashboard.
    await expect(page.getByRole('link', { name: 'console home' })).toBeVisible();
    const nav = page.getByRole('navigation');
    for (const label of [/overview/, /runs/, /model router/, /workflow builder/]) {
      await expect(nav.getByRole('link', { name: label })).toBeVisible();
    }

    // Backend is reachable through the dev proxy (5173 → 8010).
    const health = await request.get('/api/health');
    expect(health.ok(), `GET /api/health -> ${health.status()}`).toBe(true);
    expect((await health.json()).status).toBe('ok');

    // Navigation routes: "workflow builder" lands on the workflows list.
    await nav.getByRole('link', { name: /workflow builder/ }).click();
    await expect(page).toHaveURL(/\/workflows$/);

    // The list renders one row per workflow the backend reports — each row
    // carries a stable `workflow-link-<name>` testid. Reconcile the rendered
    // row count against the /api/workflows record (through the same proxy)
    // rather than trusting a single substring match, and anchor on the seeded
    // code_review definition by its exact testid so a `code_review_*` sibling
    // could never satisfy it by accident.
    const workflowsRes = await request.get('/api/workflows');
    expect(
      workflowsRes.ok(),
      `GET /api/workflows -> ${workflowsRes.status()}`,
    ).toBe(true);
    const { workflows } = (await workflowsRes.json()) as {
      workflows: string[];
    };
    expect(workflows).toContain('code_review');
    await expect(page.locator('[data-testid^="workflow-link-"]')).toHaveCount(
      workflows.length,
      { timeout: 15_000 },
    );
    await expect(page.getByTestId('workflow-link-code_review')).toBeVisible();
  });
});
