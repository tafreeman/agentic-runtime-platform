import type { StepStatus } from "../../api/types";

/**
 * Design-language status chips (ARP Console mock): colored dot + uppercase
 * mono label — "● PASSING" green, "● FAILED" red, "● RUNNING" cyan,
 * "● QUEUED" blue, "● DEGRADED" amber (opt-in via the `degraded` prop).
 */
type ChipKey =
  | "passing"
  | "degraded"
  | "failed"
  | "running"
  | "queued"
  | "skipped"
  | "cancelled";

interface ChipConfig {
  label: string;
  color: string;
  animate?: boolean;
}

const chips: Record<ChipKey, ChipConfig> = {
  passing:   { label: "● PASSING",   color: "text-b-green" },
  degraded:  { label: "● DEGRADED",  color: "text-b-amber" },
  failed:    { label: "● FAILED",    color: "text-b-red" },
  running:   { label: "● RUNNING",   color: "text-b-clay", animate: true },
  queued:    { label: "● QUEUED",    color: "text-b-blue" },
  skipped:   { label: "● SKIPPED",   color: "text-b-amber" },
  cancelled: { label: "● CANCELLED", color: "text-b-text-dim" },
};

/** Run-level aliases seen on RunSummary/RunDetail alongside StepStatus. */
type StatusAlias = "ok" | "completed" | "error" | "in_progress" | "queued";

const statusToChip: Record<StepStatus | StatusAlias, ChipKey> = {
  success: "passing",
  ok: "passing",
  completed: "passing",
  failed: "failed",
  error: "failed",
  running: "running",
  in_progress: "running",
  pending: "queued",
  queued: "queued",
  skipped: "skipped",
  cancelled: "cancelled",
};

function chipFor(status: string): ChipKey | undefined {
  return status in statusToChip
    ? statusToChip[status as StepStatus | StatusAlias]
    : undefined;
}

interface Props {
  status: string | null | undefined;
  size?: "sm" | "md";
  /**
   * Render the amber "● DEGRADED" chip instead of "● PASSING" when the run
   * finished successfully but individual steps failed. Callers derive this
   * from real data (e.g. `failed_step_count > 0`) — it is never inferred
   * here, and it is ignored for non-passing statuses.
   */
  degraded?: boolean;
}

export default function StatusBadge({
  status,
  size = "sm",
  degraded = false,
}: Readonly<Props>) {
  const raw = (status ?? "unknown").toLowerCase();
  const mapped = chipFor(raw);
  const key = mapped === "passing" && degraded ? "degraded" : mapped;
  const cfg: ChipConfig = key
    ? chips[key]
    : { label: `● ${raw.toUpperCase()}`, color: "text-b-text-dim" };
  const sizeClass = size === "sm" ? "text-[10px]" : "text-[11px]";
  const animateClass = cfg.animate ? "animate-pulse" : "";
  const plainLabel = cfg.label.replace("● ", "");

  return (
    <span
      role="status"
      aria-label={plainLabel}
      data-testid="status-badge"
      className={`inline-block whitespace-nowrap font-mono uppercase tracking-[0.5px] ${cfg.color} ${sizeClass} ${animateClass}`}
    >
      <span aria-hidden="true">{cfg.label}</span>
    </span>
  );
}
