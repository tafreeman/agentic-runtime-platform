import {
  Circle,
  CircleCheck,
  CircleDot,
  CircleSlash,
  CircleX,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

/**
 * The one status vocabulary (design system §11.3): `[shape] Label`, in the
 * status colour, never colour alone. Every run, step, evaluation and live
 * status in the UI renders through this marker so the same state always reads
 * the same way: same icon, same sentence-case word, same token.
 *
 * Labels are the existing wire values in sentence case — no invented states.
 * Running is info-blue like the graph's running state (vermilion stays the
 * selection mark).
 */
export type StatusTone = "success" | "info" | "warning" | "danger" | "neutral";

export interface StatusMeta {
  readonly label: string;
  readonly tone: StatusTone;
  readonly Icon: LucideIcon;
}

const SUCCESS = { tone: "success", Icon: CircleCheck } as const;
const DANGER = { tone: "danger", Icon: CircleX } as const;
const INFO = { tone: "info", Icon: CircleDot } as const;
const WARNING = { tone: "warning", Icon: TriangleAlert } as const;
const NEUTRAL = { tone: "neutral", Icon: Circle } as const;

const STATUS_META: Record<string, StatusMeta> = {
  // Step / run lifecycle (server StepStatus + run-record values).
  pending: { label: "Pending", ...NEUTRAL },
  running: { label: "Running", ...INFO },
  in_progress: { label: "Running", ...INFO },
  retrying: { label: "Retrying", ...INFO },
  success: { label: "Success", ...SUCCESS },
  completed: { label: "Completed", ...SUCCESS },
  failed: { label: "Failed", ...DANGER },
  error: { label: "Error", ...DANGER },
  skipped: { label: "Skipped", ...WARNING },
  cancelled: { label: "Cancelled", tone: "neutral", Icon: CircleSlash },
  // Live stream lifecycle (useWorkflowStream's workflowStatus).
  connecting: { label: "Connecting", ...NEUTRAL },
  evaluating: { label: "Evaluating", ...INFO },
  // Evaluation outcomes.
  passed: { label: "Passed", ...SUCCESS },
  review: { label: "Review", ...WARNING },
};

/** Text colour per tone — every value is ≥4.5:1 on the el surfaces. */
export const STATUS_TONE_TEXT: Record<StatusTone, string> = {
  success: "text-el-success",
  info: "text-el-info",
  warning: "text-el-warning",
  danger: "text-el-danger",
  neutral: "text-el-muted",
};

function sentenceCase(raw: string): string {
  const words = raw.replaceAll("_", " ").trim();
  if (!words) return "Unknown";
  return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase();
}

/** Icon, sentence-case label and tone for any status string. */
export function statusMeta(status: string | null | undefined): StatusMeta {
  const key = (status ?? "").trim().toLowerCase();
  return STATUS_META[key] ?? { label: sentenceCase(key), ...NEUTRAL };
}

interface Props {
  status: string | null | undefined;
  /** Override the label (e.g. an evaluation's "Passed"/"Failed"). */
  label?: string;
  size?: "sm" | "md";
  /**
   * Pulse the running icon. Opt-in for the one live indicator in a view
   * (§13: no more than one or two pulsing marks); ledgers stay still.
   * The pulse is motion-safe only.
   */
  pulse?: boolean;
  className?: string;
}

export default function StatusBadge({
  status,
  label,
  size = "sm",
  pulse = false,
  className = "",
}: Readonly<Props>) {
  const meta = statusMeta(status);
  const sizeClass = size === "sm" ? "text-xs" : "text-sm";
  const iconSize = size === "sm" ? "size-3.5" : "size-4";
  const pulseClass =
    pulse && meta.tone === "info" ? "motion-safe:animate-pulse" : "";
  const { Icon } = meta;

  return (
    <span
      data-status={meta.tone}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap font-medium ${STATUS_TONE_TEXT[meta.tone]} ${sizeClass} ${className}`}
    >
      <Icon aria-hidden="true" className={`flex-none ${iconSize} ${pulseClass}`} />
      <span>{label ?? meta.label}</span>
    </span>
  );
}
