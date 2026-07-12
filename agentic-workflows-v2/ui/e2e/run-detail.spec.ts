import { expect, test } from '@playwright/test';

/**
 * Run detail surface — "inspecting one run" (/runs/:filename → RunDetailPage).
 *
 * The deep-link route wraps the shared RunDetailPanel in its "page" layout: a
 * status header (workflow-name h1 + a run-status pill), a workflow DAG card, and
 * a step-list card whose rows open an Output/Input/Metadata inspector. On mount
 * the panel fires GET /api/runs/<filename> (useRunDetail → getRunDetail) plus the
 * workflow DAG; the standalone route adds a breadcrumb + back-to-list button.
 *
 * The sibling runs-list.spec.ts already proves the list → deep-link navigation
 * lands the panel; these specs go one layer deeper into the *content*: they
 * cross-check the rendered status against the persisted record and drive the
 * per-step drill-down. Everything is grounded in the live API by shape, count,
 * and canonicalised status bucket — never in the generated, volatile filename,
 * run id, timestamps, or wall-clock durations — and holds whether the on-disk
 * history (and a run's step list) is empty or populated.
 *
 * The spans-tab body carries a real testid (run-detail-page-layout); the header
 * status pill and the step inspector expose none, so they are anchored on stable
 * status tokens / accessible names and DOM order, not on styling classes.
 */

/** Terminal + in-flight status tokens a run or step can surface as a bare pill. */
const STATUS_TOKEN =
  /^(success|completed|failed|error|running|in_progress|pending|skipped|cancelled)$/i;

/** Canonicalise UI text vs. the API enum into buckets so `error` cannot silently
 *  agree with `completed` via a loose substring match. Mirrors the helper in
 *  workflow-run.spec.ts. */
function bucket(raw: string): 'success' | 'failed' | 'other' {
  const s = raw.trim().toLowerCase();
  if (/^(success|completed|ok)$/.test(s)) return 'success';
  if (/^(failed|error)$/.test(s)) return 'failed';
  return 'other';
}

/** Escape a run/step identifier for safe embedding in an accessible-name regex. */
function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

test.describe('run detail', () => {
  test('surfaces run status, the step list, and per-step drill-down, matching the record', async ({
    page,
    request,
  }) => {
    await page.goto('/runs');
    await expect(page.getByRole('heading', { name: /^runs$/i })).toBeVisible();

    // Ground emptiness in the same history query the page issues (useRuns →
    // listRuns defaults to limit=50). Proxied 5173 → 8010 by Vite.
    const listRes = await request.get('/api/runs?limit=50');
    expect(listRes.ok(), `GET /api/runs?limit=50 -> ${listRes.status()}`).toBe(true);
    const history = (await listRes.json()) as unknown[];
    expect(Array.isArray(history), 'GET /api/runs must return an array').toBe(true);

    // Each populated row carries a deep-link ([↗], aria-label "Open run
    // <shortId>") to the standalone /runs/:filename route.
    const openLinks = page.getByRole('link', { name: /^Open run / });
    if (history.length === 0) {
      // Fresh, run-free checkout: nothing to open — assert the placeholder, stop.
      await expect(page.getByText(/no runs yet/i)).toBeVisible({ timeout: 30_000 });
      return;
    }
    await expect(openLinks.first()).toBeVisible({ timeout: 30_000 });

    // Derive the run's storage filename from the deep-link's href (…/runs/<file>)
    // rather than hardcoding the generated, volatile value. The filename already
    // carries its .json suffix, so the route and GET /api/runs/<file> both take
    // it verbatim (unlike a bare run_id, which needs .json appended).
    const firstLink = openLinks.first();
    const href = await firstLink.getAttribute('href');
    expect(href, 'open-run deep-link must carry an href').toBeTruthy();
    const file = decodeURIComponent((href ?? '').split('/runs/')[1] ?? '');
    expect(file, 'href must include a /runs/<file> segment').toBeTruthy();

    // Opening the same link routes to the standalone detail — a filename segment
    // beyond the /runs list root.
    await firstLink.click();
    await expect(page).toHaveURL(/\/runs\/[^/]+$/, { timeout: 15_000 });

    // Shared RunDetailPanel mounts in its "page" layout once the run resolves.
    await expect(page.getByTestId('run-detail-page-layout')).toBeVisible({
      timeout: 30_000,
    });

    // Authoritative server record for the opened run (filename derived above).
    const rec = await request.get(`/api/runs/${file}`);
    expect(rec.ok(), `GET /api/runs/${file} -> ${rec.status()}`).toBe(true);
    const run = await rec.json();
    expect(run.status, 'server record must carry a status').toBeTruthy();

    // Identity: the detail heading is the opened run's workflow name — proof the
    // route resolved the run the deep-link pointed at.
    await expect(
      page.getByRole('heading', { level: 1, name: String(run.workflow_name) }),
    ).toBeVisible();

    // Structure: the workflow-DAG card renders alongside the step list in the
    // page-layout grid (its title is stable chrome regardless of DAG load state).
    await expect(page.getByText(/^workflow dag$/i)).toBeVisible();

    // Status: the header pill is the first bare status token in DOM order — the
    // metrics ("ok 100%"), run id, and workflow name never full-match a status
    // word. Read it independently of the API, then cross-check terminal buckets
    // so a wrong disposition cannot silently agree via substring.
    const uiStatusEl = page.getByText(STATUS_TOKEN).first();
    await expect(uiStatusEl).toBeVisible({ timeout: 30_000 });
    const uiStatus = (await uiStatusEl.textContent())?.trim() ?? '';
    expect(bucket(uiStatus)).toBe(bucket(String(run.status)));

    // Step list + per-step drill-down. Holds whether the run has steps or not.
    const steps = Array.isArray(run.steps) ? run.steps : [];
    if (steps.length === 0) {
      await expect(page.getByText(/no steps recorded/i)).toBeVisible();
      return;
    }
    // The step-list card title carries the count ("steps · N"); assert the
    // exact count from the record (bullet-glyph agnostic) so it reconciles with
    // the persisted step list and never collides with the header's "steps N"
    // metric (no bullet glyph → no match).
    await expect(
      page.getByText(new RegExp(`^steps\\s+\\S\\s+${steps.length}$`)),
    ).toBeVisible();

    // Drill into a concrete step from the record (step names are workflow-defined
    // and stable, not generated ids). Its Output/Input/Metadata inspector renders
    // and toggles — the tab group only exists once a step is selected.
    const stepName = String(steps[steps.length - 1].step_name);
    await page
      .getByRole('button', { name: new RegExp(escapeRegExp(stepName)) })
      .first()
      .click();

    const outputTab = page.getByRole('button', { name: 'Output', exact: true });
    const metadataTab = page.getByRole('button', { name: 'Metadata', exact: true });
    await expect(outputTab).toBeVisible();
    await expect(metadataTab).toBeVisible();
    await expect(outputTab).toHaveAttribute('aria-selected', 'true');

    await metadataTab.click();
    await expect(metadataTab).toHaveAttribute('aria-selected', 'true');
    await expect(outputTab).toHaveAttribute('aria-selected', 'false');
  });

  test('deep-links straight to /runs/:filename and renders the detail cold', async ({
    page,
    request,
  }) => {
    // Cold entry by URL — no list, no SPA transition, no warm react-query cache.
    // Pick any persisted run from the API to build the deep link.
    const listRes = await request.get('/api/runs?limit=1');
    expect(listRes.ok(), `GET /api/runs?limit=1 -> ${listRes.status()}`).toBe(true);
    const runs = (await listRes.json()) as Array<{
      filename: string;
      workflow_name: string;
      status: string;
    }>;
    expect(Array.isArray(runs), 'GET /api/runs must return an array').toBe(true);

    if (runs.length === 0) {
      // No history to deep-link: fall back to the list's empty placeholder.
      await page.goto('/runs');
      await expect(page.getByText(/no runs yet/i)).toBeVisible({ timeout: 30_000 });
      return;
    }

    // The stored filename already carries its .json suffix; the route takes it
    // verbatim (react-router decodes the segment back to the raw filename).
    const [first] = runs;
    const file = String(first.filename);
    await page.goto(`/runs/${encodeURIComponent(file)}`);

    // RunDetailPage wrapper chrome: the breadcrumb path + the back-to-list button.
    await expect(page.getByRole('button', { name: /go back/i })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(`runs/${file}`, { exact: true }).first()).toBeVisible();

    // Shared panel resolved in its page layout, headed by the run's workflow name.
    await expect(page.getByTestId('run-detail-page-layout')).toBeVisible({
      timeout: 30_000,
    });
    await expect(
      page.getByRole('heading', { level: 1, name: String(first.workflow_name) }),
    ).toBeVisible();

    // Status cross-check from the cold load: the header pill (first bare status
    // token in DOM order) agrees with the top-level `status` on the record.
    const uiStatusEl = page.getByText(STATUS_TOKEN).first();
    await expect(uiStatusEl).toBeVisible({ timeout: 30_000 });
    const uiStatus = (await uiStatusEl.textContent())?.trim() ?? '';
    expect(bucket(uiStatus)).toBe(bucket(String(first.status)));
  });
});
