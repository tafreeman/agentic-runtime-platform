import type { StepStatus } from "../../api/types";

const config: Record<StepStatus, { label: string; color: string; animate?: boolean }> = {
  pending:   { label: "[----]", color: "text-b-text-dim" },
  running:   { label: "[RUN]",  color: "text-b-clay",     animate: true },
  success:   { label: "[OK ]",  color: "text-b-green" },
  failed:    { label: "[ERR]",  color: "text-b-red" },
  skipped:   { label: "[WARN]", color: "text-b-amber" },
  cancelled: { label: "[----]", color: "text-b-text-dim" },
};

interface Props {
  status: StepStatus | string;
  size?: "sm" | "md";
}

export default function StatusBadge({ status, size = "sm" }: Props) {
  const cfg = config[status as StepStatus] ?? config.pending;
  const sizeClass = size === "sm" ? "text-xs" : "text-sm";
  const animateClass = cfg.animate ? "animate-pulse" : "";

  return (
    <span
      className={`inline-block font-mono tabular-nums ${cfg.color} ${sizeClass} ${animateClass}`}
    >
      {cfg.label}
    </span>
  );
}
