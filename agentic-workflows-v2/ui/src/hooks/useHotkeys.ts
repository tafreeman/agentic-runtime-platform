import { useEffect } from "react";

export type HotkeyAction =
  | "new"       // n — trigger "new" action on current page
  | "filter"    // f or / — focus filter input
  | "next"      // j — move selection down
  | "prev"      // k — move selection up
  | "escape";   // Esc — close panel/modal, clear filter

export type HotkeyMap = Partial<Record<HotkeyAction, () => void>>;

/** Returns true if a text-entry element currently has focus. */
function isInputFocused(): boolean {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return false;
  const tag = el.tagName.toLowerCase();
  return (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    (el as HTMLElement).isContentEditable
  );
}

/**
 * Binds global keyboard shortcuts and unbinds them on unmount.
 *
 * Hotkeys are suppressed when any text input has focus (guard active),
 * except for Escape which always fires so users can dismiss overlays.
 *
 * @param handlers - Map of action name to callback.
 */
export function useHotkeys(handlers: HotkeyMap): void {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      // Esc always fires — used to dismiss/clear regardless of input state.
      if (e.key === "Escape") {
        handlers.escape?.();
        return;
      }

      // Suppress all other hotkeys when the user is typing.
      if (isInputFocused()) return;

      // Ignore modifier-key combos (Ctrl+f, Alt+n, etc.)
      if (e.ctrlKey || e.altKey || e.metaKey) return;

      switch (e.key) {
        case "n":
          handlers.new?.();
          break;
        case "f":
        case "/":
          e.preventDefault(); // prevent browser find-bar on "/"
          handlers.filter?.();
          break;
        case "j":
          handlers.next?.();
          break;
        case "k":
          handlers.prev?.();
          break;
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handlers]);
}
