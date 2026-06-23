import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "paper";

const STORAGE_KEY = "ui_theme";
const DEFAULT_THEME: Theme = "dark";

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
    // A previously stored "bolt" theme (now removed) falls back to dark.
    if (saved === "bolt") return "dark";
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME;
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setThemeCallback = useCallback((t: Theme) => {
    setTheme(t);
  }, [setTheme]);

  return [theme, setThemeCallback];
}
