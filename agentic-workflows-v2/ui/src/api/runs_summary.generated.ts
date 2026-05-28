/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/runs_summary.schema.json
 * Origin Pydantic model: agentic_v2.server.models.RunsSummaryResponse
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
/**
 * Aggregate statistics across all (or filtered) workflow runs.
 *
 * Attributes:
 *     total_runs: Total number of runs found.
 *     success: Count of runs with ``SUCCESS`` status.
 *     failed: Count of runs with ``FAILED`` status.
 *     avg_duration_ms: Mean duration in milliseconds, or None.
 *     workflows: Distinct workflow names seen.
 *     tokens_30d: Total tokens consumed in the last 30 days, or None.
 */
export interface RunsSummaryResponse {
  avg_duration_ms?: number | null;
  failed?: number;
  success?: number;
  tokens_30d?: number | null;
  total_runs?: number;
  workflows?: string[];
}
