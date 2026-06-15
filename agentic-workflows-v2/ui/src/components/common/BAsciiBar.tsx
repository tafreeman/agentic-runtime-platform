interface BAsciiBarProps {
  readonly value: number; // 0..1
  readonly width?: number; // character width
  readonly color?: "b-green" | "b-clay" | "b-red" | "b-amber" | "b-blue";
  readonly className?: string;
}

export default function BAsciiBar({
  value,
  width = 20,
  color = "b-green",
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
      className={`font-mono text-[10px] leading-none text-${color} ${className}`}
    >
      <span aria-hidden="true">{bar}</span>
    </span>
  );
}
