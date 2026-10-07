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

export default function BAsciiBar({
  value,
  width = 20,
  color = "success",
  className = "",
}: Readonly<BAsciiBarProps>) {
  const clamped = Math.max(0, Math.min(1, value));
  const filled = Math.round(clamped * width);
  const empty = width - filled;
  const bar = "█".repeat(filled) + "░".repeat(empty);
  const pct = Math.round(clamped * 100);
  return (
    <span
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`${pct}%`}
      className={`font-mono text-micro leading-none ${COLOR_CLASSES[color]} ${className}`}
    >
      <span aria-hidden="true">{bar}</span>
    </span>
  );
}
