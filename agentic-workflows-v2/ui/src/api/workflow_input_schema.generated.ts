/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/workflow_input_schema.schema.json
 * Origin Pydantic model: agentic_v2.server.models.WorkflowInputSchemaResponse
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
/**
 * Full DAG + input-schema wire response for ``GET /api/workflows/{name}/dag``.
 *
 * Extends :class:`DAGResponse` by carrying a typed ``inputs`` list so that
 * callers receive a fully-validated response rather than an opaque dict.
 *
 * Attributes:
 *     name: Workflow name.
 *     description: Workflow description from the YAML definition.
 *     nodes: List of DAG nodes (steps).
 *     edges: List of directed dependency edges.
 *     inputs: Ordered list of declared workflow input parameters.
 */
export interface WorkflowInputSchemaResponse {
  description?: string;
  edges: DAGEdgeModel[];
  inputs?: WorkflowInputSchemaItem[];
  name: string;
  nodes: DAGNodeModel[];
}
/**
 * A directed dependency edge in the workflow DAG visualization.
 *
 * Attributes:
 *     source: Name of the predecessor step.
 *     target: Name of the dependent step.
 */
export interface DAGEdgeModel {
  source: string;
  target: string;
}
/**
 * HTTP wire shape for a single workflow input parameter descriptor.
 *
 * Each item in the ``inputs`` list returned by
 * ``GET /api/workflows/{name}/dag`` describes one declared workflow
 * input: its name, type, description, default value, whether it is
 * required, and any allowed enum values.
 *
 * Attributes:
 *     name: Input parameter name as declared in the workflow YAML.
 *     type: Data type string (e.g. ``"string"``, ``"integer"``).
 *     description: Human-readable description of the parameter.
 *     default: Default value, or ``None`` when no default is set.
 *     required: ``True`` if the parameter must be supplied by the caller.
 *     enum: Restricted set of allowed string values, or ``None``.
 */
export interface WorkflowInputSchemaItem {
  default?: unknown;
  description?: string;
  enum?: string[] | null;
  name: string;
  required?: boolean;
  type?: string;
}
/**
 * A single node (step) in the workflow DAG visualization.
 *
 * Attributes:
 *     id: Step name used as the unique node identifier.
 *     agent: Agent name assigned to execute this step, or None.
 *     description: Human-readable step description.
 *     depends_on: List of predecessor step names.
 *     tier: Model tier hint (often embedded in the agent name).
 */
export interface DAGNodeModel {
  agent?: string | null;
  depends_on: string[];
  description?: string;
  id: string;
  tier?: string | null;
}
