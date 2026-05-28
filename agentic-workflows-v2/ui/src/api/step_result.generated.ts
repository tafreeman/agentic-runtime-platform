/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/step_result.schema.json
 * Origin Pydantic model: agentic_v2.server.models.StepResultRecord
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
/**
 * HTTP wire shape for a single step in ``GET /api/runs/{filename}``.
 *
 * This is the canonical Pydantic model for the dict produced by
 * ``build_step_record()`` in ``agentic_v2.workflows.run_logger``.
 * Field names reflect the HTTP wire names: ``input``/``output`` (not the
 * internal ``input_data``/``output_data``), and ``tokens_used`` extracted
 * from step metadata.
 *
 * ``extra="forbid"`` ensures any future ``build_step_record()`` additions
 * surface immediately at runtime rather than silently drifting.
 *
 * Attributes:
 *     step_name: Identifier of the step within the workflow DAG.
 *     status: Terminal status string (e.g. ``"success"``, ``"failed"``).
 *     agent_role: Agent persona/role name assigned to this step.
 *     tier: Model tier integer (0=no LLM, 1=1–3B, 2=7–14B, 3=32B+), or None.
 *     model_used: Resolved model identifier used for execution.
 *     duration_ms: Wall-clock execution time in milliseconds, or None if step
 *         did not complete (``end_time`` absent).
 *     retry_count: Number of retry attempts made (0 = first attempt succeeded).
 *     tokens_used: Token count extracted from step metadata, or None.
 *     input: Step input data (truncated dict).
 *     output: Step output data (truncated dict).
 *     error: Error message if the step failed, else None.
 *     error_type: Exception class name if the step failed, else None.
 *     start_time: ISO-8601 start timestamp, or None.
 *     end_time: ISO-8601 end timestamp, or None.
 *     metadata: Remaining step metadata after ``tokens_used`` extraction, or None.
 */
export interface StepResultRecord {
  agent_role?: string | null;
  duration_ms?: number | null;
  end_time?: string | null;
  error?: string | null;
  error_type?: string | null;
  input: {
    [k: string]: unknown;
  };
  metadata?: {
    [k: string]: unknown;
  } | null;
  model_used?: string | null;
  output: {
    [k: string]: unknown;
  };
  retry_count?: number;
  start_time?: string | null;
  status: string;
  step_name: string;
  tier?: number | null;
  tokens_used?: number | null;
}
