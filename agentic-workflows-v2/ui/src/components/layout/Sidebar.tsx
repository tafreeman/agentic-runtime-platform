import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTheme } from "../../hooks/useTheme";
import { useBackendHealth } from "../../hooks/useBackendHealth";
import MobileNav from "./MobileNav";
import PaletteShortcut from "./PaletteShortcut";
import { NAV_ITEMS, isNavItemActive } from "./navigation";

// Small-caps overline (CONSOLE / SHORTCUTS).
const OVERLINE = "text-micro font-medium tracking-[1.6px] text-el-muted";

export default function Sidebar() {
  const [theme, setTheme] = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const { pathname } = useLocation();

  // Footer engine-status dot wired to the shared backend health probe (see
  // useBackendHealth). The dot colour + label reflect the live connection
  // state.
  const health = useBackendHealth();
  const engineConnected = health.isSuccess;
  const engineChecking = health.isLoading || health.isFetching;
  // No-LLM indicator reflects the server's own reported mode (health.data.no_llm_mode),
  // not a client build-time flag, so it can never drift from how the server was
  // actually started.
  const noLlmMode = health.data?.no_llm_mode ?? false;
  const serverVersion = health.data?.version;

  let engineDotClass = "bg-el-danger";
  let engineTextClass = "text-el-danger";
  let engineLabel = "engine: offline";
  if (engineConnected) {
    engineDotClass = "bg-el-success";
    engineTextClass = "text-el-success";
    engineLabel = "engine: ready";
  } else if (engineChecking) {
    // Only the transient "checking" state pulses (motion-safe).
    engineDotClass = "bg-el-warning motion-safe:animate-pulse";
    engineTextClass = "text-el-warning";
    engineLabel = "engine: checking";
  }
  const engineTitle =
    engineConnected && serverVersion
      ? `${engineLabel} · server v${serverVersion}`
      : engineLabel;

  // Toggle cycles only between the two supported themes (dark ⇄ paper).
  const nextTheme = theme === "dark" ? "paper" : "dark";

  // Collapsed, labels stay in the accessibility tree (sr-only) so icon-width
  // controls keep their names.
  const labelClass = collapsed ? "sr-only" : "whitespace-nowrap";

  return (
    <>
    {/* Width snaps between expanded and collapsed: animating `width` is a
        layout transition (reflows the main column every frame). */}
    <aside
      className={`hidden h-full flex-none flex-col border-r border-el-divider bg-el-surface md:flex ${
        collapsed ? "w-16" : "w-[216px]"
      }`}
    >
      {/* Section label. The brand lives once, in ConsoleHeader. */}
      {!collapsed && (
        <div className={`px-[18px] pt-4 pb-2 ${OVERLINE}`}>CONSOLE</div>
      )}

      {/* Navigation */}
      <nav
        aria-label="Primary"
        className={`flex flex-col gap-0.5 px-2.5 ${collapsed ? "pt-4" : ""}`}
      >
        {NAV_ITEMS.map((link) => {
          const isActive = isNavItemActive(link, pathname);
          return (
            <Link
              key={link.to}
              to={link.to}
              title={link.label}
              aria-current={isActive ? "page" : undefined}
              data-testid={`nav-${link.testid}`}
              className={`relative flex min-h-9 items-center gap-2.5 rounded-md px-[11px] py-2 text-[12.5px] transition-colors focus-ring-inset ${
                isActive
                  ? "bg-el-subtle font-medium text-el-ink"
                  : "text-el-muted hover:bg-el-hover hover:text-el-ink"
              }`}
            >
              {isActive && (
                // Active state = a 2px rule (design system §8.1), not a
                // coloured capsule.
                <span
                  aria-hidden="true"
                  className="absolute inset-y-2 left-0 w-0.5 bg-el-accent-strong"
                />
              )}
              <span className="w-3.5 flex-none text-center text-micro text-el-faint">
                {link.num}
              </span>
              <span className={labelClass}>{link.label}</span>
              {link.live && !collapsed && (
                <span
                  aria-hidden="true"
                  className="ml-auto h-1.5 w-1.5 flex-none rounded-full bg-el-success"
                />
              )}
              {!collapsed && (
                <span
                  className={`${link.live ? "" : "ml-auto "}flex-none font-mono text-micro text-el-muted`}
                  aria-hidden="true"
                >
                  g {link.goKey}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Shortcuts legend — mirrors the design kit's sidebar footer block. */}
      {!collapsed && (
        <div className="mt-4 px-[18px]">
          <div className={`pb-2 ${OVERLINE}`}>SHORTCUTS</div>
          <div className="space-y-1 text-micro text-el-muted">
            <div>
              <kbd className="font-mono text-el-secondary">j k</kbd> move ·{" "}
              <kbd className="font-mono text-el-secondary">↵</kbd> inspect
            </div>
            <div>
              <kbd className="font-mono text-el-secondary">esc</kbd> close panel
            </div>
            <div>
              <PaletteShortcut variant="inline" /> palette ·{" "}
              <kbd className="font-mono text-el-secondary">g</kbd>+key go to
            </div>
          </div>
        </div>
      )}

      {/* Footer: engine status, no-LLM mode, theme toggle, collapse */}
      <div className="mx-2 mt-auto mb-0 flex flex-col gap-1 rounded-md border-t border-el-divider bg-el-canvas p-2.5">
        {/* Engine / connection status — wired to the live /health probe */}
        <div
          className="flex items-center gap-2.5 px-2.5 py-[7px]"
          title={engineTitle}
        >
          <span
            aria-hidden="true"
            className={`h-2 w-2 flex-none rounded-full ${engineDotClass}`}
          />
          <span className={`${labelClass} text-micro ${engineTextClass}`}>
            {engineLabel}
          </span>
          {!collapsed && engineConnected && serverVersion && (
            <span className="ml-auto font-mono text-micro text-el-muted">
              v{serverVersion}
            </span>
          )}
        </div>

        {/* No-LLM mode indicator (server-reported). The on/off word carries
            the state; the dot is a supplement, never the only cue. */}
        <div
          className="flex items-center gap-2.5 px-2.5 py-[7px]"
          title={noLlmMode ? "No-LLM mode active" : "No-LLM mode off"}
        >
          <span
            aria-hidden="true"
            className={`h-2 w-2 flex-none rounded-full ${
              noLlmMode ? "bg-el-warning" : "border border-el-muted"
            }`}
          />
          <span className={`${labelClass} text-micro text-el-secondary`}>
            No-LLM mode{" "}
            <span className={noLlmMode ? "text-el-warning" : "text-el-muted"}>
              {noLlmMode ? "on" : "off"}
            </span>
          </span>
        </div>

        {/* Theme toggle: cycles dark ⇄ paper only */}
        <button
          type="button"
          onClick={() => setTheme(nextTheme)}
          aria-pressed={theme === "paper"}
          title={`switch to ${nextTheme} theme`}
          className="flex min-h-9 w-full items-center gap-2.5 rounded-md bg-transparent px-2.5 text-left text-micro text-el-secondary transition-colors hover:bg-el-hover hover:text-el-ink focus-ring"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            className="flex-none"
            aria-hidden="true"
          >
            <path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36A5.39 5.39 0 0 1 12 3z" />
          </svg>
          <span className={labelClass}>{theme} theme</span>
        </button>

        {/* Collapse control */}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-pressed={collapsed}
          aria-label={collapsed ? "expand sidebar" : "collapse sidebar"}
          title={collapsed ? "expand sidebar" : "collapse sidebar"}
          className="mt-1 flex min-h-9 w-full items-center gap-2.5 rounded-md border border-el-divider bg-el-surface px-2.5 text-left text-micro text-el-secondary transition-colors hover:bg-el-hover hover:text-el-ink focus-ring"
        >
          <span className="w-4 flex-none text-center text-[13px]" aria-hidden="true">
            {collapsed ? "»" : "«"}
          </span>
          {!collapsed && <span className="whitespace-nowrap">collapse</span>}
        </button>
      </div>
    </aside>
    <MobileNav />
    </>
  );
}
