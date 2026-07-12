import { expect, test } from '@playwright/test';

/**
 * Evaluations surface — "opening the evaluations page" (/evaluations →
 * EvaluationsPage).
 *
 * The page always renders two clay-accent action bands — "evaluate a previous
 * run" and the head-to-head "compare runs" panel — above a main region that
 * resolves to one of two states from GET /api/runs?limit=50 (the same list the
 * Runs page uses, filtered to runs carrying an evaluation_score):
 *   - populated: a scorecard (letter grade + score distribution), a pass-rate
 *     card, and a "recent evaluations" rubric table;
 *   - empty: the "no evaluated runs yet" state with a CTA to run a workflow.
 *
 * Which state shows is volatile — evaluated runs are only visible while they
 * sit in the top-50 recency window, and parallel specs mint fresh runs — so the
 * assertions anchor on the always-present heading + action bands and on a
 * scorecard-OR-empty-state locator, and branch on whichever actually settled
 * (never on the probe's snapshot, which can disagree once runs are minted). No
 * single scored run's volatile values (generated ids, timestamps, letter
 * grades) are pinned: the populated branch checks only derived, non-volatile
 * facts — that the scorecard reports a positive count of scored runs and that
 * the table surfaces a valid pass/warn/fail disposition. A `<section
 * aria-label>` is exposed as an ARIA "region", so the bands and scorecard are
 * matched by role/name.
 */
test.describe('evaluations', () => {
  test('loads the surface and renders its primary structure (populated or empty)', async ({
    page,
    request,
  }) => {
    await page.goto('/evaluations');

    // The h1 lives outside the data-gated main content, so it renders before
    // any run data lands.
    await expect(
      page.getByRole('heading', { name: /^Evaluations$/ }),
    ).toBeVisible();

    // Probe the page's data source directly (Vite proxies /api → backend) to
    // confirm reachability and the RunSummary shape the page reads, without
    // asserting on any volatile value.
    const runsRes = await request.get('/api/runs?limit=50');
    expect(runsRes.ok(), `GET /api/runs -> ${runsRes.status()}`).toBe(true);
    const runs = await runsRes.json();
    expect(Array.isArray(runs), 'GET /api/runs must return an array').toBe(true);
    if (runs.length > 0) {
      const first = runs[0];
      expect(typeof first.filename).toBe('string');
      // evaluation_score gates the populated-vs-empty branch: null on an
      // unscored run, a number once a run has been graded.
      expect(
        first.evaluation_score == null ||
          typeof first.evaluation_score === 'number',
      ).toBe(true);
    }

    // The two action bands render regardless of eval data (they sit above the
    // data-gated main content).
    await expect(
      page.getByRole('region', { name: 'evaluate a previous run' }),
    ).toBeVisible();
    await expect(
      page.getByRole('region', { name: 'compare runs' }),
    ).toBeVisible();

    // Main content settles into exactly one structural state. Wait for either
    // the scorecard (populated) or the empty-state line (empty); the list query
    // can take a few seconds and re-polls, so budget generously.
    const scorecard = page.getByRole('region', { name: 'scorecard' });
    const emptyState = page.getByText(/no evaluated runs yet/i);
    await expect(scorecard.or(emptyState).first()).toBeVisible({
      timeout: 30_000,
    });

    // Deepen whichever branch rendered so the primary structure is verified in
    // both worlds, still without touching any specific scored-run row.
    if (await emptyState.isVisible()) {
      await expect(
        page.getByRole('link', { name: /run a workflow with evaluation/i }),
      ).toBeVisible();
      // Mutual exclusivity: the scored-surface scorecard shares the page's one
      // empty/populated gate, so it must be absent in the empty world. This
      // stays green once empty — no spec deletes runs, so scored runs never
      // re-enter the recency window mid-suite to flip it back.
      await expect(scorecard).toHaveCount(0);
    } else {
      // Populated: prove the scored surface reflects real data, not just a
      // mounted shell. The scorecard headline carries a positive count of
      // scored runs — scoped to the region so it can't match the identical
      // phrase in the page subtitle — and the "recent evaluations" table
      // surfaces at least one row with a real pass/warn/fail disposition. The
      // pill text is lowercase in the DOM, so the anchored regex can't collide
      // with the uppercase "PASS" column header.
      await expect(scorecard.getByText(/[1-9]\d* runs scored/)).toBeVisible();
      const recent = page.getByRole('region', { name: 'recent evaluations' });
      await expect(recent).toBeVisible();
      await expect(
        recent.getByText(/^(pass|warn|fail)$/).first(),
      ).toBeVisible();
    }
  });

  test('routes to the evaluations surface from the sidebar', async ({
    page,
  }) => {
    await page.goto('/');

    // Sidebar labels carry a zero-padded ordinal prefix ("05 evaluations"), so
    // match by regex scoped to the single navigation landmark.
    const nav = page.getByRole('navigation');
    await nav.getByRole('link', { name: /evaluations/i }).click();

    await expect(page).toHaveURL(/\/evaluations$/);
    await expect(
      page.getByRole('heading', { name: /^Evaluations$/ }),
    ).toBeVisible({ timeout: 15_000 });
  });
});
