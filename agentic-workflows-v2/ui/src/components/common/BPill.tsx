import type { ReactNode } from "react";

export type BPillTone = "ok" | "err" | "warn" | "info" | "dim" | "clay";

const TONE_CLASSES: Record<BPillTone, string> = {
  ok: "text-b-green border-b-green/40 bg-b-green/10",
  err: "text-b-red border-b-red/40 bg-b-red/10",
  warn: "text-b-amber border-b-amber/40 bg-b-amber/10",
  info: "text-b-blue border-b-blue/40 bg-b-blue/10",
  dim: "text-b-text-dim border-b-line bg-transparent",
  clay: "text-b-clay border-b-clay/40 bg-b-clay-soft",
};

interface BPillProps {
  tone?: BPillTone;
  children: ReactNode;
  className?: string;
}

export default function BPill({ tone = "dim", children, className = "" }: BPillProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm border px-[7px] py-[2px] font-mono text-[10px] uppercase tracking-[0.5px] ${TONE_CLASSES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
