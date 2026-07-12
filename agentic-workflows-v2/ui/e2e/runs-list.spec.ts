import { expect, test } from '@playwright/test';

/**
 * Runs list surface — "browsing past runs" (/runs → RunsPage).
 *
 * On mount the page fires GET /api/runs?limit=50 (useRuns → listRuns) plus an
 * aggregate GET /api/runs/summary and renders the history as a master table:
 * one keyboard-navigable row per run (role="button", aria-label="Inspect run
 * <shortId>"), a KPI stats band, a status/workflow filter row, a live-tail
 * switch, and a per-row deep-link ([↗], aria-label="Open run <shortId>") to the
 * standalone /runs/:filename detail route. Clicking a row body opens the
 * in-place inspector aside; the [↗] link is the one that changes the URL.
 *
 * These specs stay agnostic to the (generated, volatile) run ids, timestamps,
 * and durations: they correlate the UI against the live API only by *shape* and
 * *count*, and hold whether the on-disk history is empty or populated. The
 * table/KPI band expose no data-testids, so the surface is anchored on the h1,
 * the static KPI label, the labelled filter controls, and the rows' own
 * role/name — all stable, non-volatile chrome. The detail route does carry a
 * real testid (run-detail-page-layout) once the shared panel mounts.
 */
test.describe('runs list', () => {
  // Mirror the client's own request: useRuns → listRuns() defaults to limit=50.
  const RUNS_ENDPOINT = '/api/runs?limit=50';

  test('lists past runs and the status filter narrows the list coherently', async ({
    page,
    request,
  }) => {
    await page.goto('/runs');

    // Page chrome renders immediately, independent of the async history fetch:
    // the "Runs" h1 and the KPI stats band (its static "runs total" cell label).
    await expect(page.getByRole('heading', { name: /^runs$/i })).toBeVisible();
    await expect(page.getByText('runs total', { exact: true })).toBeVisible();

    // The filter row's labelled controls (no data-testid in source): the status
    // <select> this test drives, plus the search box that anchors the row.
    const statusFilter = page.getByLabel('Filter by status');
    await expect(statusFilter).toBeVisible();
    await expect(
      page.getByLabel('Search runs by workflow name or run ID'),
    ).toBeVisible();

    // Ground the row assertions in the real payload — the same query the page
    // issues. GET /api/runs is proxied to the backend via Vite (5173 → 8010).
    const res = await request.get(RUNS_ENDPOINT);
    expect(res.ok(), `GET ${RUNS_ENDPOINT} -> ${res.status()}`).toBe(true);
    const runs = (await res.json()) as Array<{ status: string }>;
    expect(Array.isArray(runs), 'GET /api/runs must return an array').toBe(true);

    // Every rendered run is a keyboard row: role="button", name "Inspect run
    // <shortId>". This is the robust list anchor (empty OR populated).
    const rows = page.getByRole('button', { name: /^Inspect run / });

    if (runs.length === 0) {
      // Empty history: the table body shows its "no runs yet" placeholder.
      await expect(page.getByText(/no runs yet/i)).toBeVisible({
        timeout: 30_000,
      });
      return;
    }

    // Populated: at least one run row renders from the history.
    await expect(rows.first()).toBeVisible({ timeout: 30_000 });
    expect(await rows.count()).toBeGreaterThan(0);

    // Drive the status filter to "success" (the option *value*, not its
    // "status: success · N" label). Filtering is a client-side narrowing — no
    // refetch — so the list must stay coherent: rows survive when the fetched
    // page holds any success run, else the "no runs match" placeholder shows.
    await statusFilter.selectOption('success');
    await expect(statusFilter).toHaveValue('success');

    if (runs.some((r) => r.status === 'success')) {
      await expect(rows.first()).toBeVisible({ timeout: 15_000 });
      expect(await rows.count()).toBeGreaterThan(0);
    } else {
      await expect(page.getByText(/no runs match/i)).toBeVisible();
    }
  });

  test('opens a run detail from the list via its deep-link', async ({
    page,
    request,
  }) => {
    await page.goto('/runs');

    // Ground truth: the same history query the page issues.
    const res = await request.get(RUNS_ENDPOINT);
    expect(res.ok(), `GET ${RUNS_ENDPOINT} -> ${res.status()}`).toBe(true);
    const runs = (await res.json()) as unknown[];
    expect(Array.isArray(runs), 'GET /api/runs must return an array').toBe(true);

    const rows = page.getByRole('button', { name: /^Inspect run / });

    if (runs.length === 0) {
      // Empty history: nothing to open — assert the placeholder and stop, so
      // the test stays green on a fresh, run-free checkout.
      await expect(page.getByText(/no runs yet/i)).toBeVisible({
        timeout: 30_000,
      });
      return;
    }

    // Populated: rows land (deterministic no_llm history already on disk).
    await expect(rows.first()).toBeVisible({ timeout: 30_000 });

    // Each row carries a deep-link ([↗], aria-label="Open run <shortId>") to
    // the standalone detail route; its stopPropagation keeps the click from
    // also opening the in-place inspector aside. Follow the first one.
    const openLinks = page.getByRole('link', { name: /^Open run / });
    await expect(openLinks.first()).toBeVisible();
    await openLinks.first().click();

    // Routed to /runs/<filename> — distinct from the /runs list root. The
    // filename is generated + volatile, so match the route shape, not a value.
    await expect(page).toHaveURL(/\/runs\/.+/, { timeout: 15_000 });

    // The shared RunDetailPanel mounts in its "page" layout once the run loads;
    // the back-to-list control is the detail route's stable chrome.
    await expect(page.getByTestId('run-detail-page-layout')).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole('button', { name: /go back/i })).toBeVisible();
  });
});
