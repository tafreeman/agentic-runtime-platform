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

    // Populated: the list renders exactly the fetched history. listRuns issues
    // the same GET /api/runs?limit=50 and does no client-side reshaping, and
    // with the default filters (status "all", empty query) every fetched run
    // becomes one row — so the row count reconciles 1:1 with the API payload
    // (a stronger, auto-retrying check than "at least one").
    await expect(rows.first()).toBeVisible({ timeout: 30_000 });
    await expect(rows).toHaveCount(runs.length, { timeout: 15_000 });

    // Drive the status filter to "success" (the option *value*, not its
    // "status: success · N" label). Filtering is a client-side narrowing — no
    // refetch — so the list must stay coherent: it must show *exactly* the
    // success runs from the fetched page, else the "no runs match" placeholder.
    const successCount = runs.filter((r) => r.status === 'success').length;
    await statusFilter.selectOption('success');
    await expect(statusFilter).toHaveValue('success');

    if (successCount > 0) {
      // Narrowed set reconciles 1:1 with the success runs in the payload.
      await expect(rows).toHaveCount(successCount, { timeout: 15_000 });
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
    // also opening the in-place inspector aside. Capture the first link's href
    // before following it so we can assert we land on *that* run, not merely
    // "some" detail route.
    const openLinks = page.getByRole('link', { name: /^Open run / });
    const openLink = openLinks.first();
    await expect(openLink).toBeVisible();
    const href = await openLink.getAttribute('href');
    expect(href, 'open-run deep-link must carry an href').toBeTruthy();
    await openLink.click();

    // Routed to exactly the deep-link's target — a single /runs/<filename>
    // segment beyond the list root. The filename is generated + volatile, so
    // assert the path equals the href we followed rather than a hardcoded value.
    await expect(page).toHaveURL((url) => url.pathname === href, {
      timeout: 15_000,
    });

    // The shared RunDetailPanel mounts in its "page" layout once the run loads;
    // the back-to-list control is the detail route's stable chrome.
    await expect(page.getByTestId('run-detail-page-layout')).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole('button', { name: /go back/i })).toBeVisible();
  });
});
