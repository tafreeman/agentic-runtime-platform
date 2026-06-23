import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTheme } from "../../hooks/useTheme";
import { isNoLlmModeEnabled } from "../../config/featureFlags";
import { healthCheck } from "../../api/client";

/**
 * Navigation entries, mapped onto the seven existing routes. The visible label
 * and ordinal follow the redesigned console; the `data-testid` (`nav-<testid>`)
 * is preserved per route so existing tests and screen-reader anchors stay valid.
 */
interface NavItem {
  readonly to: string;
  readonly testid: string;
  readonly label: string;
  readonly num: string;
  readonly title: string;
  readonly end: boolean;
  readonly live?: boolean;
}

const links: readonly NavItem[] = [
  { to: "/", testid: "dashboard", label: "overview", num: "01", title: "overview", end: true },
  { to: "/live/latest", testid: "live", label: "live execution", num: "02", title: "live execution", end: false, live: true },
  { to: "/runs", testid: "runs", label: "runs", num: "03", title: "runs", end: false },
  { to: "/models", testid: "models", label: "model router", num: "04", title: "model router", end: false },
  { to: "/evaluations", testid: "evals", label: "evaluations", num: "05", title: "evaluations", end: false },
  { to: "/workflows", testid: "workflows", label: "workflow builder", num: "06", title: "workflow builder", end: false },
  { to: "/datasets", testid: "datasets", label: "datasets", num: "07", title: "datasets", end: false },
];

// Inline values for theme-driven tokens (radius / border-width / heading font)
// that have no Tailwind utility. Colours flow through Tailwind b-* classes.
const radSm = { borderRadius: "var(--b-rad-sm)" } as const;
const headingFont = { fontFamily: "var(--b-font-heading)" } as const;
const hardBorder = { borderWidth: "var(--b-bw)" } as const;

export default function Sidebar() {
  const [theme, setTheme] = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const noLlmMode = isNoLlmModeEnabled();

  // Footer engine-status dot wired to the real backend health probe (the same
  // /health endpoint ConsoleStatus polls). The dot colour + label reflect the
  // live connection state; the dot keeps the motion-safe pulse treatment.
  const health = useQuery({
    queryKey: ["backend-health"],
    queryFn: healthCheck,
    retry: false,
    refetchInterval: 15_000,
  });
  const engineConnected = health.isSuccess;
  const engineChecking = health.isLoading || health.isFetching;

  let engineDotClass = "bg-b-red";
  let engineTextClass = "text-b-red";
  let engineLabel = "engine: offline";
  let engineTitle = "engine: offline";
  if (engineConnected) {
    engineDotClass = "bg-b-green";
    engineTextClass = "text-b-green";
    engineLabel = "engine: ready";
    engineTitle = "engine: ready";
  } else if (engineChecking) {
    engineDotClass = "bg-b-amber";
    engineTextClass = "text-b-amber";
    engineLabel = "engine: checking";
    engineTitle = "engine: checking";
  }

  // Toggle cycles only between the two supported themes (dark ⇄ paper).
  const nextTheme = theme === "dark" ? "paper" : "dark";

  return (
    <aside
      className={`flex h-full flex-col border-r border-b-line bg-b-bg1 transition-[width] ${
        collapsed ? "w-16" : "w-52"
      }`}
    >
      {/* Brand */}
      <div className="flex items-center gap-3 px-4 pb-4 pt-4">
        <svg
          width="30"
          height="30"
          viewBox="0 0 30 30"
          fill="none"
          className="flex-none"
          aria-hidden="true"
        >
          <ellipse cx="15" cy="15" rx="13" ry="5.4" transform="rotate(-24 15 15)" stroke="rgb(var(--b-clay))" strokeWidth="1.5" fill="none" opacity="0.9" />
          <ellipse cx="15" cy="15" rx="9" ry="3.6" transform="rotate(-24 15 15)" stroke="rgb(var(--b-clay))" strokeWidth="1" fill="none" opacity="0.45" />
          <circle cx="15" cy="15" r="4.2" fill="rgb(var(--b-bg0))" />
          <circle cx="15" cy="15" r="4.2" fill="none" stroke="rgb(var(--b-clay))" strokeWidth="1.5" />
        </svg>
        {!collapsed && (
          <div className="leading-tight">
            <div
              className="text-[14px] font-semibold tracking-tight text-b-text"
              style={headingFont}
            >
              agentic
            </div>
            <div className="mt-[3px] text-[9.5px] tracking-[1px] text-b-text-faint">
              RUNTIME · v0.4.2
            </div>
          </div>
        )}
      </div>

      {/* Section label */}
      {!collapsed && (
        <div className="px-[18px] pb-2 pt-1.5 text-[9px] tracking-[1.6px] text-b-text-faint">
          CONSOLE
        </div>
      )}

      {/* Navigation */}
      <nav className="flex flex-col gap-0.5 px-2.5">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            title={link.title}
            data-testid={`nav-${link.testid}`}
            style={radSm}
            className={({ isActive }) =>
              `relative flex items-center gap-2.5 px-[11px] py-2.5 text-[12.5px] transition-colors focus:outline-none focus:ring-1 focus:ring-b-clay/50 ${
                isActive
                  ? "bg-b-clay-soft text-b-clay"
                  : "text-b-text-dim hover:bg-b-bg2 hover:text-b-text"
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span
                    aria-hidden="true"
                    className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 bg-b-clay"
                    style={{ borderRadius: "0 3px 3px 0" }}
                  />
                )}
                <span className="w-3.5 flex-none text-center text-[9.5px] text-b-text-faint">
                  {link.num}
                </span>
                {!collapsed && (
                  <span className="whitespace-nowrap">{link.label}</span>
                )}
                {link.live && !collapsed && (
                  <span
                    aria-hidden="true"
                    className="ml-auto h-1.5 w-1.5 flex-none rounded-full bg-b-green motion-safe:animate-pulse"
                  />
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Footer: engine status, no-LLM mode, theme toggle, collapse */}
      <div
        className="mx-2 mb-0 mt-auto flex flex-col gap-1 border-t border-b-line bg-b-bg0 p-2.5"
        style={radSm}
      >
        {/* Engine / connection status — wired to the live /health probe */}
        <div
          className="flex items-center gap-2.5 px-2.5 py-[7px]"
          title={engineTitle}
        >
          <span
            aria-hidden="true"
            className={`h-2 w-2 flex-none rounded-full motion-safe:animate-pulse ${engineDotClass}`}
          />
          {!collapsed && (
            <span className={`whitespace-nowrap text-[11px] ${engineTextClass}`}>
              {engineLabel}
            </span>
          )}
        </div>

        {/* No-LLM mode indicator (reflects the configured feature flag) */}
        <div
          className="flex items-center gap-2.5 px-2.5 py-[7px]"
          title={noLlmMode ? "No-LLM mode active" : "No-LLM mode off"}
        >
          <span
            aria-hidden="true"
            className={`h-2 w-2 flex-none rounded-full ${
              noLlmMode ? "bg-b-green shadow-[0_0_6px] shadow-b-green" : "bg-b-text-faint"
            }`}
          />
          {!collapsed && (
            <span className="whitespace-nowrap text-[11px] text-b-text-mid">
              No-LLM mode
            </span>
          )}
        </div>

        {/* Theme toggle: cycles dark ⇄ paper only */}
        <button
          type="button"
          onClick={() => setTheme(nextTheme)}
          aria-pressed={theme === "paper"}
          title={`switch to ${nextTheme} theme`}
          className="flex w-full items-center gap-2.5 bg-transparent px-2.5 py-[7px] text-left text-[11px] text-b-text-dim transition-colors hover:text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
          style={radSm}
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
          {!collapsed && <span className="whitespace-nowrap">{theme} theme</span>}
        </button>

        {/* Collapse control */}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-pressed={collapsed}
          aria-label={collapsed ? "expand sidebar" : "collapse sidebar"}
          title={collapsed ? "expand sidebar" : "collapse sidebar"}
          className="mt-1 flex w-full items-center gap-2.5 border border-b-line bg-b-bg1 px-2.5 py-2 text-left text-[11px] text-b-text-dim transition-colors hover:text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
          style={{ ...radSm, ...hardBorder }}
        >
          <span className="w-4 flex-none text-center text-[13px]" aria-hidden="true">
            {collapsed ? "»" : "«"}
          </span>
          {!collapsed && <span className="whitespace-nowrap">collapse</span>}
        </button>
      </div>
    </aside>
  );
}
