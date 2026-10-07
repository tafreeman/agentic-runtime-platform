/**
 * The console's primary destinations (design system §8.1: Observe, Build,
 * Evaluate, Configure — Configure has a single destination, Model Router).
 * Shared by the desktop sidebar and the mobile bottom bar / "More" sheet.
 *
 * The `data-testid` (`nav-<testid>`) is preserved per route so existing tests
 * and screen-reader anchors stay valid.
 */
export interface NavItem {
  readonly to: string;
  readonly testid: string;
  readonly label: string;
  /** Short label for the mobile bottom bar. */
  readonly shortLabel: string;
  readonly num: string;
  readonly end: boolean;
  readonly live?: boolean;
  /**
   * Path prefix that marks this item active when it differs from `to` —
   * the live item links the `/live/latest` alias but owns every `/live/*`.
   */
  readonly matchPrefix?: string;
  /** Second key of the `g`-sequence shortcut (see useGoNav's GO_TARGETS). */
  readonly goKey: string;
  /** Shown directly in the mobile bottom bar (the rest live under "More"). */
  readonly mobilePrimary: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", testid: "dashboard", label: "overview", shortLabel: "overview", num: "01", end: true, goKey: "d", mobilePrimary: true },
  { to: "/live/latest", testid: "live", label: "live execution", shortLabel: "live", num: "02", end: false, live: true, matchPrefix: "/live", goKey: "e", mobilePrimary: true },
  { to: "/runs", testid: "runs", label: "runs", shortLabel: "runs", num: "03", end: false, goKey: "r", mobilePrimary: true },
  { to: "/models", testid: "models", label: "model router", shortLabel: "models", num: "04", end: false, goKey: "m", mobilePrimary: false },
  { to: "/evaluations", testid: "evals", label: "evaluations", shortLabel: "evals", num: "05", end: false, goKey: "l", mobilePrimary: false },
  { to: "/workflows", testid: "workflows", label: "workflow builder", shortLabel: "workflows", num: "06", end: false, goKey: "w", mobilePrimary: true },
  { to: "/datasets", testid: "datasets", label: "datasets", shortLabel: "datasets", num: "07", end: false, goKey: "a", mobilePrimary: false },
];

/**
 * Whether `item` is the current destination for `pathname`. Query strings are
 * not part of `pathname`, so `/models?tab=providers` (the `/settings` alias)
 * keeps "model router" active.
 */
export function isNavItemActive(item: NavItem, pathname: string): boolean {
  const base = item.matchPrefix ?? item.to;
  if (item.end) return pathname === base;
  return pathname === base || pathname.startsWith(`${base}/`);
}
