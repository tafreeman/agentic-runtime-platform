import type { ReactNode } from "react";

export type BPillTone = "ok" | "err" | "warn" | "info" | "dim" | "clay";

// Tiny category tag (design system §10.5): 2px radius, never a pill shape,
// short lowercase sans label (no tracked uppercase, no monospace costume).
// Run/step/evaluation *status* uses the shared StatusBadge marker instead. Status tones pair each color with its *-soft tint (text is
// >=4.5:1 on it); the caller always supplies the text label, so color never
// carries status alone. "clay" is the one vermilion tone and stays outlined
// (no fill) so it reads as a quiet mark rather than a second emphasis.
const TONE_CLASSES: Record<BPillTone, string> = {
  ok: "text-el-success border-el-success/40 bg-el-success-soft",
  err: "text-el-danger border-el-danger/40 bg-el-danger-soft",
  warn: "text-el-warning border-el-warning/40 bg-el-warning-soft",
  info: "text-el-info border-el-info/40 bg-el-info-soft",
  dim: "text-el-muted border-el-divider bg-transparent",
  clay: "text-el-accent-strong border-el-accent-strong/40 bg-transparent",
};

interface BPillProps {
  tone?: BPillTone;
  children: ReactNode;
  className?: string;
}

export default function BPill({ tone = "dim", children, className = "" }: Readonly<BPillProps>) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm border px-1.5 py-px text-micro font-medium ${TONE_CLASSES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
