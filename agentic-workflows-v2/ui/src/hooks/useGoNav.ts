import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

/** How long a leading `g` stays "armed" waiting for its second key. */
const GO_SEQUENCE_WINDOW_MS = 1500;

interface GoTarget {
  readonly path: string;
}

/**
 * `g`-then-key page shortcuts from the console design kit (`g r` → Runs,
 * `g e` → live execution, …). Keys match the hints rendered in the sidebar.
 * The CLI strip follows the route (useCliRouteSync), so a jump shows the
 * destination's real CLI equivalent, or none — never an invented command.
 */
export const GO_TARGETS: Readonly<Record<string, GoTarget>> = {
  d: { path: "/" },
  e: { path: "/live/latest" },
  r: { path: "/runs" },
  m: { path: "/models" },
  l: { path: "/evaluations" },
  w: { path: "/workflows" },
  a: { path: "/datasets" },
  // Not hinted in the sidebar: "providers & tiers" is a tab of the Model
  // Router (design system §8.1), so `g s` jumps straight to that tab — the
  // same place the legacy `/settings` route redirects to.
  s: { path: "/models?tab=providers" },
};

/** Returns true if a text-entry element currently has focus. */
function isInputFocused(): boolean {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) {
    return false;
  }
  const tag = el.tagName.toLowerCase();
  return (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    (el as HTMLElement).isContentEditable
  );
}

/**
 * Binds the global `g` + key navigation sequence. Mount once (in App, inside
 * the router). Suppressed while typing in an input and for modifier-key
 * combos; an unrecognised second key disarms the sequence so ordinary typing
 * is never hijacked.
 */
export function useGoNav(): void {
  const navigate = useNavigate();
  const armedUntil = useRef(0);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if (e.ctrlKey || e.altKey || e.metaKey || isInputFocused()) return;

      const key = e.key.toLowerCase();
      const now = Date.now();

      if (key === "g") {
        armedUntil.current = now + GO_SEQUENCE_WINDOW_MS;
        return;
      }

      if (armedUntil.current >= now) {
        armedUntil.current = 0;
        const target = GO_TARGETS[key];
        if (target) {
          e.preventDefault();
          navigate(target.path);
        }
      }
    }

    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, [navigate]);
}
