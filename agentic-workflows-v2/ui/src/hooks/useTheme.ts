import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "paper" | "bolt";

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
    const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
    if (saved === "dark" || saved === "paper" || saved === "bolt") return saved;
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME;
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
  }, []);

  return [theme, setTheme];
}
