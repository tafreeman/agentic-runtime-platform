/** Semantic status colors (el-* tokens). */
type BAsciiBarColor = "success" | "accent" | "danger" | "warning" | "info";

// Static class map (dynamic `text-${color}` was invisible to Tailwind's
// scanner).
const COLOR_CLASSES: Record<BAsciiBarColor, string> = {
  success: "text-el-success",
  accent: "text-el-accent-strong",
  danger: "text-el-danger",
  warning: "text-el-warning",
  info: "text-el-info",
};

interface BAsciiBarProps {
  readonly value: number; // 0..1
  readonly width?: number; // character width
  readonly color?: BAsciiBarColor;
  readonly className?: string;
}

/**
 * Compact score/rate bar. (The name is historical: it used to print
 * "████░░░░" block characters; it now draws a thin hairline track with a
 * scaled fill, so the value reads as a measurement rather than ASCII art.)
 * `width` keeps its old meaning — roughly that many monospace characters
 * wide — so existing layouts hold.
 */
export default function BAsciiBar({
  value,
  width = 20,
  color = "success",
  className = "",
}: Readonly<BAsciiBarProps>) {
  const clamped = Math.max(0, Math.min(1, value));
  const pct = Math.round(clamped * 100);
  return (
    <span
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`${pct}%`}
      className={`inline-flex max-w-full items-center text-micro leading-none ${COLOR_CLASSES[color]} ${className}`}
      style={{ width: `${width * 0.6}em` }}
    >
      <span
        aria-hidden="true"
        className="block h-1.5 w-full overflow-hidden rounded-sm bg-el-divider-soft"
      >
        <span
          className="block h-full w-full origin-left bg-current"
          style={{ transform: `scaleX(${clamped})` }}
        />
      </span>
    </span>
  );
}
