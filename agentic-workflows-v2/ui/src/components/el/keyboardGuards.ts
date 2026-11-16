/**
 * Pure DOM checks that decide whether a bare-key shortcut (`j`, `k`, `/`,
 * Enter) belongs to the page or to whatever currently has focus. Shared by
 * the DataTable row cursor and the FilterBar `/` shortcut.
 */

const TYPING_TAGS = new Set(["input", "textarea", "select"]);

/** Elements that handle Enter (or a click) themselves. */
const CONTROL_SELECTOR = [
  "a",
  "button",
  "input",
  "select",
  "textarea",
  "summary",
  '[role="button"]',
  '[role="link"]',
  '[role="tab"]',
  '[role="switch"]',
  '[role="checkbox"]',
  '[role="menuitem"]',
  '[role="option"]',
  '[contenteditable=""]',
  '[contenteditable="true"]',
].join(",");

/** Surfaces that own the keyboard while open; the page behind must stay quiet. */
const OVERLAY_SELECTOR = [
  '[role="dialog"]',
  '[role="alertdialog"]',
  '[role="menu"]',
  '[role="listbox"]',
].join(",");

/** Focus is "nowhere in particular": nothing, <body> or <html>. */
function isPageLevel(el: Element | null): boolean {
  return !el || el === document.body || el === document.documentElement;
}

/** True while the user is typing: input, textarea, select or contenteditable. */
export function isTypingTarget(el: Element | null): boolean {
  if (!el || isPageLevel(el)) return false;
  if (TYPING_TAGS.has(el.tagName.toLowerCase())) return true;
  // jsdom does not implement `isContentEditable`, so read the attribute too.
  const attr = el.getAttribute("contenteditable");
  return (
    (el instanceof HTMLElement && el.isContentEditable === true) ||
    attr === "" ||
    attr === "true" ||
    attr === "plaintext-only"
  );
}

/** True when the element (or an ancestor) is a control that acts on Enter or click. */
export function isControlTarget(el: Element | null): boolean {
  if (!el || isPageLevel(el)) return false;
  return el.closest(CONTROL_SELECTOR) !== null;
}

/** True when the element sits inside an open dialog, menu or listbox. */
export function isInOverlay(el: Element | null): boolean {
  if (!el || isPageLevel(el)) return false;
  return el.closest(OVERLAY_SELECTOR) !== null;
}

/** A key press with Ctrl, Alt or Meta held is a browser or app shortcut, not ours. */
export function hasCommandModifier(event: KeyboardEvent): boolean {
  return event.ctrlKey || event.altKey || event.metaKey;
}
