/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/workflow_editor_step.schema.json
 * Origin Pydantic model: agentic_v2.server.models.WorkflowEditorStep
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
/**
 * HTTP wire shape for a single step inside a workflow editor document.
 *
 * Mirrors the step-level fields that the workflow YAML parser produces and
 * that the React editor surfaces for visualisation and editing.
 *
 * Attributes:
 *     name: Step identifier (unique within the workflow).
 *     agent: Agent persona/tier string (e.g. ``"tier2_coder"``), or None.
 *     description: Human-readable step description.
 *     tier: Explicit model tier override, or None.
 *     depends_on: Names of steps this step depends on.
 *     when: Optional conditional expression string.
 *     loop_until: Loop termination expression, or None.
 *     loop_max: Maximum loop iterations, or None.
 *     tools: Tool names allowlisted for this step.
 *     prompt_file: Path to an external prompt file, or None.
 *     model: Per-step model id override, or None.
 *     persona: Persona registry id for the system prompt, or None.
 *     observers: Observer channels enabled for this step, or None for all.
 *     model_params: Sampling parameter overrides, or None.
 *     metadata: Arbitrary step-level metadata bag, or None.
 */
export interface WorkflowEditorStep {
  agent?: string | null;
  depends_on: string[];
  description?: string | null;
  loop_max?: number | null;
  loop_until?: string | null;
  metadata?: {
    [k: string]: unknown;
  } | null;
  model?: string | null;
  model_params?: StepModelParams | null;
  name: string;
  observers?: string[] | null;
  persona?: string | null;
  prompt_file?: string | null;
  tier?: string | null;
  tools?: string[];
  when?: string | null;
}
/**
 * Per-step sampling parameter overrides carried in editor documents.
 *
 * Attributes:
 *     temperature: Sampling temperature (0--2), or None for the default.
 *     top_p: Nucleus sampling probability mass (0--1], or None.
 *     max_tokens: Response token cap, or None for the provider default.
 */
export interface StepModelParams {
  max_tokens?: number | null;
  temperature?: number | null;
  top_p?: number | null;
}
