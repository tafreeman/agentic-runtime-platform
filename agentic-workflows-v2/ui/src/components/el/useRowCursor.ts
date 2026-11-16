import { useEffect, useRef, useState } from "react";

import {
  hasCommandModifier,
  isControlTarget,
  isInOverlay,
  isTypingTarget,
} from "./keyboardGuards";

export interface UseRowCursorOptions<Row> {
  rows: readonly Row[];
  getRowKey: (row: Row) => string;
  /** Controlled cursor. Leave undefined to let the hook keep its own. */
  cursorKey?: string | null;
  onCursorChange?: (key: string) => void;
  /** Called with the cursor row on Enter. */
  onRowActivate?: (row: Row) => void;
  /** Bind `j`, `k` and Enter on the window. */
  enabled: boolean;
}

export interface RowCursor {
  /** The row the cursor is on; the first row until the user moves it. */
  activeKey: string | null;
  /** Move the cursor without moving DOM focus (a Tab onto a row's link). */
  select: (key: string) => void;
  /** Ref callback registering a row element so `j`/`k` can focus it. */
  rowRef: (key: string) => (el: HTMLTableRowElement | null) => void;
}

/**
 * Roving row cursor for a table. `j` / `k` move it and focus the row (a
 * `tabIndex={-1}` target, so Tab still goes link to link); Enter activates
 * the cursor row. Keys stand down while the user types, while focus is on a
 * control that handles Enter itself, and while a dialog or menu is open.
 */
export function useRowCursor<Row>({
  rows,
  getRowKey,
  cursorKey,
  onCursorChange,
  onRowActivate,
  enabled,
}: Readonly<UseRowCursorOptions<Row>>): RowCursor {
  const [ownKey, setOwnKey] = useState<string | null>(null);
  const rowEls = useRef(new Map<string, HTMLTableRowElement>());
  const emitted = useRef<string | null>(null);

  const keys = rows.map(getRowKey);
  const wanted = cursorKey === undefined ? ownKey : cursorKey;
  const activeKey = wanted !== null && keys.includes(wanted) ? wanted : (keys[0] ?? null);

  function select(key: string): void {
    if (key === emitted.current) return;
    emitted.current = key;
    if (cursorKey === undefined) setOwnKey(key);
    onCursorChange?.(key);
  }

  function move(delta: 1 | -1): void {
    const index = activeKey === null ? -1 : keys.indexOf(activeKey);
    if (index < 0) return;
    const next = keys[Math.min(Math.max(index + delta, 0), keys.length - 1)];
    if (next === undefined) return;
    select(next);
    rowEls.current.get(next)?.focus();
  }

  function activate(): void {
    const row = rows.find((r) => getRowKey(r) === activeKey);
    if (row !== undefined) onRowActivate?.(row);
  }

  // The window listener is bound once; it reads the newest closures from here.
  const latest = useRef({ move, activate });
  useEffect(() => {
    latest.current = { move, activate };
    emitted.current = activeKey;
  });

  useEffect(() => {
    if (!enabled) return;
    function onKeyDown(event: KeyboardEvent): void {
      if (event.defaultPrevented || hasCommandModifier(event)) return;
      const focused = document.activeElement;
      if (isInOverlay(focused)) return;
      if (event.key === "j" || event.key === "k") {
        if (!isTypingTarget(focused)) latest.current.move(event.key === "j" ? 1 : -1);
      } else if (event.key === "Enter" && !isControlTarget(focused)) {
        latest.current.activate();
      }
    }
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, [enabled]);

  function rowRef(key: string): (el: HTMLTableRowElement | null) => void {
    return (el) => {
      if (el) rowEls.current.set(key, el);
      else rowEls.current.delete(key);
    };
  }

  return { activeKey, select, rowRef };
}
