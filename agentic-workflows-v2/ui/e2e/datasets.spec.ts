import { expect, test } from '@playwright/test';

/**
 * Datasets surface — "browsing evaluation datasets" (/datasets →
 * DatasetsPage → DatasetBrowser).
 *
 * On mount the page fires GET /api/eval/datasets and renders three grouped
 * sources — repository catalog, local JSON datasets, and eval sets — inside a
 * three-pane browser (list → sample index → sample detail). This spec proves
 * the route resolves from the sidebar, the header + count strip render, and the
 * browser body reflects the API payload: the grouped sections/rows when the
 * catalog is populated, or the "$ no datasets available" strip when it is empty.
 *
 * DatasetsPage / DatasetBrowser expose no `data-testid`s, so the surface is
 * anchored on the h1 heading, the mono count strip, and the browser's own
 * static placeholders/section labels — all stable, non-volatile chrome. Nav
 * links carry a zero-padded ordinal ("07 datasets"), so the sidebar link is
 * matched by regex scoped to the navigation landmark.
 */
test.describe('datasets', () => {
  test('routes to /datasets from the sidebar and renders the header + count strip', async ({
    page,
  }) => {
    await page.goto('/');

    // Sidebar routes to the datasets page. The link's accessible name carries
    // the "07" ordinal prefix, so match by regex within the nav landmark.
    const nav = page.getByRole('navigation');
    await nav.getByRole('link', { name: /datasets/ }).click();
    await expect(page).toHaveURL(/\/datasets$/);

    // Page shell: the h1 and the mono "$ N repo · N local · N eval sets" strip.
    // Assert the strip's *structure* (three labelled counts) rather than exact
    // numbers so it holds whether the catalog is empty or populated.
    await expect(page.getByRole('heading', { level: 1, name: /datasets/i })).toBeVisible();
    await expect(
      page.getByText(/\d+ repo · \d+ local · \d+ eval sets/),
    ).toBeVisible({ timeout: 15_000 });
  });

  test('renders repository / local / eval-set sections from the API, or a clear empty state', async ({
    page,
    request,
  }) => {
    await page.goto('/datasets');

    // Header renders immediately (independent of the data fetch).
    await expect(
      page.getByRole('heading', { level: 1, name: /datasets/i }),
    ).toBeVisible();

    // Ground the assertions in the real payload shape: three arrays keyed by
    // source. GET /api/eval/datasets is proxied to the backend via Vite.
    const res = await request.get('/api/eval/datasets');
    expect(res.ok(), `GET /api/eval/datasets -> ${res.status()}`).toBe(true);
    const payload = await res.json();
    for (const key of ['repository', 'local', 'eval_sets'] as const) {
      expect(
        Array.isArray(payload[key]),
        `payload.${key} must be an array`,
      ).toBe(true);
    }

    // The browser mounts once the query resolves: with nothing selected, the
    // middle/right panes show their static prompts regardless of catalog size.
    // This is the robust "surface rendered" anchor (empty OR populated).
    await expect(page.getByText('$ select a dataset')).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText('$ select a sample')).toBeVisible();

    // Names shown as left-pane rows/entries across every source (repository +
    // local rows, eval-set entries). Read from the same response so the check
    // adapts if the catalog changes rather than pinning volatile data.
    const listedNames: string[] = [
      ...payload.repository.map((d: { name: string }) => d.name),
      ...payload.local.map((d: { name: string }) => d.name),
      ...payload.eval_sets.map((s: { name: string }) => s.name),
    ];

    if (listedNames.length > 0) {
      // Populated: the browser lists at least the first catalog entry and does
      // NOT surface its internal empty strip. The repository group header is a
      // stable structural anchor unique to the section (the count strip abbreviates
      // it to "repo").
      if (payload.repository.length > 0) {
        await expect(page.getByText(/repository ·/)).toBeVisible();
      }
      await expect(page.getByText(listedNames[0]).first()).toBeVisible({
        timeout: 15_000,
      });
      await expect(page.getByText('$ no datasets available')).toHaveCount(0);
    } else {
      // Empty: the browser's left pane shows its terminal-style empty strip.
      await expect(page.getByText('$ no datasets available')).toBeVisible();
    }
  });
});
