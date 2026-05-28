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
  | StepCompleteEvent
  | StepErrorEvent
  | WorkflowEndEvent
  | ErrorEvent
  | EvaluationStartEvent
  | EvaluationCompleteEvent;

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
