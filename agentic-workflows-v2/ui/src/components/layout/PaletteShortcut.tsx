import { isApplePlatform } from "../../lib/platform";

interface PaletteShortcutProps {
  /** `keycap`: bordered caps (header search). `inline`: plain text (legends). */
  readonly variant?: "keycap" | "inline";
  readonly className?: string;
}

const KEYCAP =
  "rounded-sm border border-el-divider bg-el-canvas px-1 py-px font-mono text-micro leading-none text-el-secondary";
const INLINE = "font-mono text-micro text-el-secondary";

/**
 * The command-palette shortcut as `<kbd>` markup: "⌘K" on Apple platforms,
 * "Ctrl K" elsewhere. A key combination is an outer `<kbd>` wrapping one
 * `<kbd>` per key (HTML spec). The ⌘ glyph is announced as "Command".
 */
export default function PaletteShortcut({
  variant = "keycap",
  className = "",
}: PaletteShortcutProps) {
  const apple = isApplePlatform();
  const keyClass = variant === "keycap" ? KEYCAP : INLINE;

  return (
    <kbd
      data-testid="palette-shortcut"
      data-platform={apple ? "apple" : "other"}
      className={`inline-flex flex-none items-center gap-1 font-mono ${className}`}
    >
      {apple ? (
        <>
          <kbd className={keyClass} aria-hidden="true">
            ⌘
          </kbd>
          <span className="sr-only">Command</span>
        </>
      ) : (
        <kbd className={keyClass}>Ctrl</kbd>
      )}
      <kbd className={keyClass}>K</kbd>
    </kbd>
  );
}
