import { useEffect } from "react";

import { cn } from "@/lib/utils";

export interface ViewSwitchItem<Id extends string> {
  readonly id: Id;
  readonly label: string;
}

export interface ViewSwitchProps<Id extends string> {
  items: readonly ViewSwitchItem<Id>[];
  /** The id of the current view. */
  value: Id;
  onChange: (id: Id) => void;
  /** Accessible name of the group. */
  label?: string;
  /**
   * Bind the keys 1, 2, 3... to the views, in order. Off by default so a
   * second segmented control on the same page (a status filter) never fights
   * it; turn it on for the one run-view switch.
   */
  shortcuts?: boolean;
  className?: string;
}

function isTextField(node: EventTarget | null): boolean {
  if (!(node instanceof HTMLElement)) return false;
  return (
    node.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(node.tagName)
  );
}

/** True when the key press belongs to a text field or is a modified shortcut. */
function isTyping(event: KeyboardEvent): boolean {
  if (event.ctrlKey || event.altKey || event.metaKey) return true;
  return isTextField(event.target) || isTextField(document.activeElement);
}

function useDigitShortcuts<Id extends string>(
  items: readonly ViewSwitchItem<Id>[],
  enabled: boolean,
  onChange: (id: Id) => void,
): void {
  useEffect(() => {
    if (!enabled) return;
    function onKeyDown(event: KeyboardEvent): void {
      if (!/^[1-9]$/.test(event.key) || isTyping(event)) return;
      const item = items[Number(event.key) - 1];
      if (item) onChange(item.id);
    }
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, [items, enabled, onChange]);
}

/**
 * Record, Tier board, Rewind: the readings of one run, as a segmented switch.
 * Lives right-aligned in the screen header beside the one primary action.
 * Buttons with `aria-pressed`, all reachable by Tab; the current segment is
 * raised on `surface-raised`. At 760px and below it takes the full row.
 */
export function ViewSwitch<Id extends string>({
  items,
  value,
  onChange,
  label = "View",
  shortcuts = false,
  className,
}: Readonly<ViewSwitchProps<Id>>) {
  useDigitShortcuts(items, shortcuts, onChange);

  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "inline-flex gap-0.5 rounded-md bg-el-subtle p-[3px] max-[760px]:order-3 max-[760px]:flex max-[760px]:basis-full",
        className,
      )}
    >
      {items.map((item, index) => {
        const pressed = item.id === value;
        return (
          <button
            key={item.id}
            type="button"
            aria-pressed={pressed}
            aria-keyshortcuts={shortcuts ? String(index + 1) : undefined}
            onClick={() => onChange(item.id)}
            className={cn(
              "focus-ring flex h-[30px] items-center justify-center rounded-sm px-3 text-[13px] leading-none font-medium transition-colors duration-150 max-[760px]:flex-1",
              pressed
                ? "bg-el-raised text-el-ink shadow-[0_0_0_1px_rgb(var(--el-divider))]"
                : "text-el-muted hover:text-el-ink",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
