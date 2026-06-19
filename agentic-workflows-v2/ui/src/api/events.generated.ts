/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/events.schema.json
 * Origin Pydantic model: agentic_v2.contracts.events.ExecutionEvent
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
export type ExecutionEvent =
  | WorkflowStartEvent
  | StepStartEvent
  | StepEndEvent
  | TokenDeltaEvent
  | StepCompleteEvent
  | StepErrorEvent
  | WorkflowEndEvent
  | ErrorEvent
  | EvaluationStartEvent
  | EvaluationCompleteEvent
  | ApprovalRequiredEvent
  | ApprovalDecisionEvent;

export interface WorkflowStartEvent {
  run_id: string;
  timestamp: string;
  type?: 'workflow_start';
  workflow_name: string;
}
export interface StepStartEvent {
  input?: {
    [k: string]: unknown;
  } | null;
  run_id: string;
  step: string;
  timestamp: string;
  type?: 'step_start';
}
export interface StepEndEvent {
  duration_ms: number;
  error?: string | null;
  input?: {
    [k: string]: unknown;
  } | null;
  model_used?: string | null;
  output?: {
    [k: string]: unknown;
  } | null;
  run_id: string;
  status: string;
  step: string;
  tier?: number | null;
  timestamp: string;
  tokens_used?: number | null;
  type?: 'step_end';
}
/**
 * Incremental text delta streamed from an LLM completion.
 *
 * Emitted per chunk while the EK adapter streams a step's response. Carries
 * the same correlation fields as the sibling step events (``run_id``,
 * ``step``, ``timestamp``) plus the ``delta`` text fragment. After the stream
 * is exhausted the caller emits a ``step_complete`` with the assembled text.
 */
export interface TokenDeltaEvent {
  delta: string;
  run_id: string;
  step: string;
  timestamp: string;
  type?: 'token_delta';
}
export interface StepCompleteEvent {
  duration_ms: number;
  error?: string | null;
  input?: {
    [k: string]: unknown;
  } | null;
  model_used?: string | null;
  output?: {
    [k: string]: unknown;
  } | null;
  outputs?: {
    [k: string]: unknown;
  } | null;
  run_id: string;
  status: string;
  step: string;
  tier?: number | null;
  timestamp: string;
  tokens_used?: number | null;
  type?: 'step_complete';
}
export interface StepErrorEvent {
  duration_ms: number;
  error?: string | null;
  input?: {
    [k: string]: unknown;
  } | null;
  model_used?: string | null;
  output?: {
    [k: string]: unknown;
  } | null;
  outputs?: {
    [k: string]: unknown;
  } | null;
  run_id: string;
  status?: string | null;
  step: string;
  tier?: number | null;
  timestamp: string;
  tokens_used?: number | null;
  type?: 'step_error';
}
export interface WorkflowEndEvent {
  run_id: string;
  status: string;
  timestamp: string;
  type?: 'workflow_end';
}
export interface ErrorEvent {
  error: string;
  run_id: string;
  timestamp: string;
  type?: 'error';
}
export interface EvaluationStartEvent {
  run_id: string;
  timestamp: string;
  type?: 'evaluation_start';
}
export interface EvaluationCompleteEvent {
  criteria?: {
    [k: string]: unknown;
  }[];
  grade: string;
  overall_score: number;
  pass_threshold?: number;
  passed?: boolean;
  rubric: string;
  run_id: string;
  timestamp: string;
  type?: 'evaluation_complete';
  weighted_score: number;
}
/**
 * Emitted when a tool call is gated and approval is being requested.
 *
 * Surfaced so a server/UI follow-on can drive an interactive pause/resume
 * flow. ``tool_args`` are intentionally omitted from the wire shape — they may
 * carry payloads and should not be broadcast unredacted.
 */
export interface ApprovalRequiredEvent {
  agent_or_step?: string | null;
  call_id: string;
  run_id: string;
  timestamp: string;
  tool_name: string;
  type?: 'approval_required';
}
/**
 * Emitted once an approval request has been resolved (approved/denied).
 */
export interface ApprovalDecisionEvent {
  agent_or_step?: string | null;
  call_id: string;
  decision: string;
  provider?: string | null;
  run_id: string;
  timestamp: string;
  tool_name: string;
  type?: 'approval_decision';
}
