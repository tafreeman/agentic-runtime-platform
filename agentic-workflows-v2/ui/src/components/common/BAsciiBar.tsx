/** Legacy Direction B names are kept so existing call sites stay valid. */
type BAsciiBarColor =
  | "b-green"
  | "b-clay"
  | "b-red"
  | "b-amber"
  | "b-blue"
  | "success"
  | "accent"
  | "danger"
  | "warning"
  | "info";

// Static class map (dynamic `text-${color}` was invisible to Tailwind's
// scanner and depended on legacy b-* classes being emitted elsewhere).
const COLOR_CLASSES: Record<BAsciiBarColor, string> = {
  "b-green": "text-el-success",
  success: "text-el-success",
  "b-clay": "text-el-accent-strong",
  accent: "text-el-accent-strong",
  "b-red": "text-el-danger",
  danger: "text-el-danger",
  "b-amber": "text-el-warning",
  warning: "text-el-warning",
  "b-blue": "text-el-info",
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
