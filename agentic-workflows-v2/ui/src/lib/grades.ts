/**
 * Shared grade + score helpers for run / evaluation displays.
 *
 * Eval scores arrive as either a 0..1 fraction or a 0..100 percentage depending
 * on the source, so every consumer must normalize before thresholding. Keeping
 * this logic in one place stops the Dashboard / Runs / RunList / Evaluations
 * copies from drifting — previously the same run could grade differently on
 * different screens, and a 0..1 score silently failed every pass-rate check.
 */

/** Normalize a 0..1 or 0..100 score to a 0..100 percentage; null when absent. */
export function scoreToPercent(
  score: number | null | undefined,
): number | null {
  if (score == null || Number.isNaN(score)) return null;
  return score <= 1 ? score * 100 : score;
}

/**
 * One-letter grade for a run: the server-provided letter wins (trimmed, so an
 * empty string falls through); otherwise it is derived from the normalized
 * score. Returns null when neither is available — callers render an em-dash.
 */
export function gradeLetter(
  grade: string | null | undefined,
  score: number | null | undefined,
): string | null {
  const trimmed = grade?.trim();
  if (trimmed) return trimmed.toUpperCase();
  const pct = scoreToPercent(score);
  if (pct == null) return null;
  if (pct >= 90) return "A";
  if (pct >= 80) return "B";
  if (pct >= 70) return "C";
  if (pct >= 60) return "D";
  return "F";
}

/** Tailwind text-color class for a one-letter grade (faint when absent). */
export function gradeColorClass(grade: string | null | undefined): string {
  const g = grade?.toUpperCase();
  if (g === "S" || g === "A") return "text-b-green";
  if (g === "B" || g === "C") return "text-b-amber";
  if (g === "D" || g === "F") return "text-b-red";
  return "text-b-text-faint";
}

/** Whether a run passed: S/A/B grades, or a normalized score >= 75. */
export function isPassingScore(
  grade: string | null | undefined,
  score: number | null | undefined,
): boolean {
  const g = grade?.trim().toUpperCase();
  if (g) return g === "S" || g === "A" || g === "B";
  const pct = scoreToPercent(score);
  return pct != null && pct >= 75;
}
