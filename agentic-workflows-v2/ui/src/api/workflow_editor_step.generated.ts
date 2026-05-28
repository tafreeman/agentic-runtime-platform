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
  name: string;
  prompt_file?: string | null;
  tier?: string | null;
  tools?: string[];
  when?: string | null;
}
