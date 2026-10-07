/**
 * Capability-tier mark (T0–T5). Steps name a capability tier, never a model;
 * the router resolves the tier to a model at run time. The mark shows the
 * short "T3" form and carries the full meaning for pointer (title) and
 * screen-reader (sr-only) users, so the jargon is never unexplained.
 *
 * Accepts the shapes the API and YAML use: "t3", "T3", "tier3", "3", 3.
 * Colour follows the shared tier tokens (T0–T2 low, T3 mid, T4–T5 high) and
 * always rides alongside the text label.
 */

/** Numeric tier level, or null when the value carries no digit. */
export function tierLevel(tier: string | number | null | undefined): number | null {
  if (tier == null) return null;
  if (typeof tier === "number") return Number.isFinite(tier) ? tier : null;
  const match = /(\d+)/.exec(tier);
  return match ? Number(match[1]) : null;
}

/** Border + text classes for a tier level. */
export function tierToneClass(level: number | null): string {
  if (level == null) return "border-el-divider text-el-muted";
  if (level <= 2) return "border-el-tier-low text-el-tier-low";
  if (level === 3) return "border-el-tier-mid text-el-tier-mid";
  return "border-el-tier-high text-el-tier-high";
}

/** "Tier 3 — capability tier" (or the raw value when it has no level). */
export function tierDescription(tier: string | number | null | undefined): string {
  const level = tierLevel(tier);
  return level == null
    ? `${String(tier ?? "")} — capability tier`
    : `Tier ${level} — capability tier`;
}

interface TierMarkProps {
  tier: string | number | null | undefined;
  /** Visible text; defaults to "T<level>" (or the raw value). */
  label?: string;
  /** Override the tone classes (e.g. a named alias resolved by the caller). */
  toneClass?: string;
  className?: string;
  "data-testid"?: string;
}

export default function TierMark({
  tier,
  label,
  toneClass,
  className = "",
  "data-testid": testId,
}: Readonly<TierMarkProps>) {
  const level = tierLevel(tier);
  const text = label ?? (level == null ? String(tier ?? "") : `T${level}`);
  const description = tierDescription(tier);
  return (
    <span
      data-testid={testId}
      title={description}
      className={`inline-flex flex-none items-center rounded-sm border px-1 font-mono text-micro ${
        toneClass ?? tierToneClass(level)
      } ${className}`}
    >
      <span aria-hidden="true">{text}</span>
      <span className="sr-only">{description}</span>
    </span>
  );
}
