import {
  Database,
  Gauge,
  LayoutDashboard,
  List,
  Radio,
  Trophy,
  Workflow,
  type LucideIcon,
} from "lucide-react";

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
  /** Glyph for the collapsed rail and the mobile bar (same set as ⌘K). */
  readonly icon: LucideIcon;
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
  { to: "/", testid: "dashboard", label: "Overview", shortLabel: "Overview", icon: LayoutDashboard, end: true, goKey: "d", mobilePrimary: true },
  { to: "/live/latest", testid: "live", label: "Live execution", shortLabel: "Live", icon: Radio, end: false, live: true, matchPrefix: "/live", goKey: "e", mobilePrimary: true },
  { to: "/runs", testid: "runs", label: "Runs", shortLabel: "Runs", icon: List, end: false, goKey: "r", mobilePrimary: true },
  { to: "/models", testid: "models", label: "Model router", shortLabel: "Models", icon: Gauge, end: false, goKey: "m", mobilePrimary: false },
  { to: "/evaluations", testid: "evals", label: "Evaluations", shortLabel: "Evals", icon: Trophy, end: false, goKey: "l", mobilePrimary: false },
  { to: "/workflows", testid: "workflows", label: "Workflow builder", shortLabel: "Workflows", icon: Workflow, end: false, goKey: "w", mobilePrimary: true },
  { to: "/datasets", testid: "datasets", label: "Datasets", shortLabel: "Datasets", icon: Database, end: false, goKey: "a", mobilePrimary: false },
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
