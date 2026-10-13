import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

import { EL_STATUS, type ElStatus } from "./status";

/**
 * One pill spec for status, tier and tag: 24px tall, fully rounded, 12px
 * semibold, white text on a solid `badge-*` fill (grey unless a status says
 * otherwise).
 */
const PILL =
  "inline-flex h-6 items-center justify-center gap-1.5 whitespace-nowrap rounded-full bg-el-badge-neutral px-3 text-xs leading-none font-semibold text-el-on-badge";

export interface StatusPillProps extends Omit<ComponentProps<"span">, "children"> {
  status: ElStatus;
  /**
   * Replace the fixed word. For the few API states the vocabulary has no word
   * for (see `statusView`); leave it off everywhere else.
   */
  label?: string;
  /** 104px minimum width instead of 120px, for pills inside table cells. */
  compact?: boolean;
}

/** `✓ Passed`: a glyph plus a word on a solid fill. Static, no hover. */
export function StatusPill({
  status,
  label,
  compact = false,
  className,
  ...rest
}: Readonly<StatusPillProps>) {
  const spec = EL_STATUS[status];
  return (
    <span
      data-status={status}
      className={cn(PILL, spec.fill, compact ? "min-w-26" : "min-w-30", className)}
      {...rest}
    >
      <span aria-hidden="true" className="w-3 text-center">
        {spec.glyph}
      </span>
      <span>{label ?? spec.word}</span>
    </span>
  );
}

export interface TierPillProps extends Omit<ComponentProps<"span">, "children"> {
  /** Capability tier number: 0 to 5. */
  tier: number;
  /** The capability the tier names, e.g. "coder". The routed model goes elsewhere. */
  capability?: string;
}

// The one documented use of a middle dot in the interface: the tier-and-
// capability form "T2 · coder". Every other list joins with words and commas.
const TIER_SEPARATOR = " · ";

/** `T2 · coder`: a grey mono pill naming a capability tier, not a model. */
export function TierPill({
  tier,
  capability,
  className,
  ...rest
}: Readonly<TierPillProps>) {
  const text = capability ? `T${tier}${TIER_SEPARATOR}${capability}` : `T${tier}`;
  return (
    <span className={cn(PILL, "font-mono font-medium tabular-nums", className)} {...rest}>
      {text}
    </span>
  );
}

export interface TagPillProps extends Omit<ComponentProps<"span">, "children"> {
  children: ReactNode;
}

/** A grey mono pill for a run id or a mode: `c718044a`, `no-llm`. */
export function TagPill({ children, className, ...rest }: Readonly<TagPillProps>) {
  return (
    <span className={cn(PILL, "font-mono font-medium", className)} {...rest}>
      {children}
    </span>
  );
}

export interface KbdProps extends Omit<ComponentProps<"kbd">, "children"> {
  children: ReactNode;
}

/** An outlined key cap, never filled: `Ctrl K`. */
export function Kbd({ children, className, ...rest }: Readonly<KbdProps>) {
  return (
    <kbd
      className={cn(
        "inline-flex h-6 items-center rounded-sm border border-el-divider px-2 font-mono text-xs leading-none font-medium text-el-muted",
        className,
      )}
      {...rest}
    >
      {children}
    </kbd>
  );
}
