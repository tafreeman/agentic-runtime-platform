import { useCallback, useSyncExternalStore } from "react";

export type Theme = "dark" | "paper";

const STORAGE_KEY = "ui_theme";
const DEFAULT_THEME: Theme = "paper";

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* localStorage unavailable (private mode, etc.) */
  }
}

function readStoredTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "dark" || saved === "paper") return saved;
    // Removed legacy themes migrate to the Evidence Ledger default.
    if (saved === "bolt") return "paper";
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME;
}

// One shared value so every consumer (sidebar, mobile nav, toaster) shows the
// same theme; each useTheme() call used to hold its own copy and drift.
let current: Theme | null = null;
const listeners = new Set<() => void>();

function getTheme(): Theme {
  current ??= readStoredTheme();
  return current;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    // With no consumers mounted, drop the cache so the next mount re-reads
    // storage instead of trusting a value that may be stale.
    if (listeners.size === 0) current = null;
  };
}

function setSharedTheme(next: Theme): void {
  current = next;
  applyTheme(next);
  listeners.forEach((listener) => listener());
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const theme = useSyncExternalStore(subscribe, getTheme, () => DEFAULT_THEME);

  // The document attribute is applied on first use as well as on change.
  if (typeof document !== "undefined" && document.documentElement.dataset.theme !== theme) {
    applyTheme(theme);
  }

  const setTheme = useCallback((t: Theme) => setSharedTheme(t), []);
  return [theme, setTheme];
}
