interface BAsciiBarProps {
  value: number; // 0..1
  width?: number; // character width
  color?: "b-green" | "b-clay" | "b-red" | "b-amber" | "b-blue";
  className?: string;
}

export default function BAsciiBar({
  value,
  width = 20,
  color = "b-green",
  className = "",
}: BAsciiBarProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const filled = Math.round(clamped * width);
  const empty = width - filled;
  const bar = "█".repeat(filled) + "░".repeat(empty);
  return (
    <span
      className={`font-mono text-[10px] leading-none text-${color} ${className}`}
    >
      {bar}
    </span>
  );
}
