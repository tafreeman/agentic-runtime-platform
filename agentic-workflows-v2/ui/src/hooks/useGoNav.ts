import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useCli } from "./useCli";

/** How long a leading `g` stays "armed" waiting for its second key. */
const GO_SEQUENCE_WINDOW_MS = 1500;

interface GoTarget {
  readonly path: string;
  readonly cli: string;
}

/**
 * `g`-then-key page shortcuts from the console design kit (`g r` → Runs,
 * `g e` → live execution, …). Keys match the hints rendered in the sidebar.
 */
export const GO_TARGETS: Readonly<Record<string, GoTarget>> = {
  d: { path: "/", cli: "agentic dashboard" },
  e: { path: "/live/latest", cli: "agentic runs watch latest --follow" },
  r: { path: "/runs", cli: "agentic runs list" },
  t: { path: "/telemetry", cli: "agentic runs stats" },
  m: { path: "/models", cli: "agentic models list" },
  l: { path: "/evaluations", cli: "agentic evals list" },
  w: { path: "/workflows", cli: "agentic workflows list" },
  a: { path: "/datasets", cli: "agentic datasets list" },
  s: { path: "/settings", cli: "agentic settings show" },
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
 * both the router and {@link CliProvider}). Suppressed while typing in an
 * input and for modifier-key combos; an unrecognised second key disarms the
 * sequence so ordinary typing is never hijacked.
 */
export function useGoNav(): void {
  const navigate = useNavigate();
  const { setCli } = useCli();
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
          setCli(target.cli);
          navigate(target.path);
        }
      }
    }

    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, [navigate, setCli]);
}
