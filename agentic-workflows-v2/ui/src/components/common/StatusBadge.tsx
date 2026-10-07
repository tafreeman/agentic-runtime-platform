import type { StepStatus } from "../../api/types";

// Status always carries a text label (never color alone, §11.3). Running is
// info-blue like the graph's running state — vermilion stays reserved for
// selection/emphasis — and its pulse stops under reduced motion (globals.css).
const config: Record<StepStatus, { label: string; color: string; animate?: boolean }> = {
  pending:   { label: "[----]", color: "text-el-neutral" },
  running:   { label: "[RUN]",  color: "text-el-info",    animate: true },
  success:   { label: "[OK ]",  color: "text-el-success" },
  failed:    { label: "[ERR]",  color: "text-el-danger" },
  skipped:   { label: "[WARN]", color: "text-el-warning" },
  cancelled: { label: "[----]", color: "text-el-neutral" },
};

interface Props {
  status: string;
  size?: "sm" | "md";
}

export default function StatusBadge({ status, size = "sm" }: Readonly<Props>) {
  const cfg = config[status as StepStatus] ?? config.pending;
  const sizeClass = size === "sm" ? "text-xs" : "text-sm";
  const animateClass = cfg.animate ? "animate-pulse" : "";
  const plainLabel = cfg.label.replace(/[\[\]\s-]/g, "") || status;

  return (
    <span
      role="status"
      aria-label={plainLabel}
      className={`inline-block font-mono tabular-nums ${cfg.color} ${sizeClass} ${animateClass}`}
    >
      <span aria-hidden="true">{cfg.label}</span>
    </span>
  );
}
