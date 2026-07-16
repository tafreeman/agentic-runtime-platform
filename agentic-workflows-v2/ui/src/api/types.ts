// ---------------------------------------------------------------------------
// AUTO-GENERATED re-exports — do NOT hand-edit the generated files.
//
// Wire-format types below are derived from the Python Pydantic contracts via
// `python -m scripts.generate_ts_types` (produces JSON Schemas) followed by
// `npm run generate:types` (compiles them to TypeScript). The `wire-format-drift`
// CI job fails any PR that changes a Python contract without regenerating.
// ---------------------------------------------------------------------------

// StepResultRecord → canonical alias StepResult for existing UI consumers.
import type { StepResultRecord as StepResult } from "./step_result.generated";
export type { StepResult };

// DAGResponse, DAGNodeModel, DAGEdgeModel, WorkflowInputSchemaItem
// NOTE: imported locally (not just re-exported) because WorkflowEditorDocument
// below extends DAGResponse — a bare `export type {...} from` would not bring
// these names into local scope. Do not collapse to a re-export-only form.
import type {
  DAGResponse,
  DAGNodeModel,
  DAGEdgeModel,
  WorkflowInputSchemaItem,
} from "./dag_response.generated";
export type { DAGResponse, DAGNodeModel, DAGEdgeModel, WorkflowInputSchemaItem };

// WorkflowInputSchemaResponse (full DAG + inputs)
export type { WorkflowInputSchemaResponse } from "./workflow_input_schema.generated";

// WorkflowEditorStep + StepModelParams
import type {
  StepModelParams,
  WorkflowEditorStep,
} from "./workflow_editor_step.generated";
export type { StepModelParams, WorkflowEditorStep };

// RunsSummaryResponse (aggregate run statistics)
export type { RunsSummaryResponse } from "./runs_summary.generated";

// ---------------------------------------------------------------------------
// Compatibility aliases — legacy names kept so existing consumers compile
// without changes. These thin aliases re-expose the generated types under
// the names that were previously hand-defined in this file.
// ---------------------------------------------------------------------------

// DAGNode / DAGEdge were the old hand-written names for DAGNodeModel / DAGEdgeModel.
export type { DAGNodeModel as DAGNode, DAGEdgeModel as DAGEdge } from "./dag_response.generated";

// WorkflowInputSchema was the old hand-written name for WorkflowInputSchemaItem.
export type { WorkflowInputSchemaItem as WorkflowInputSchema } from "./dag_response.generated";

// RunsSummary was the old hand-written name for RunsSummaryResponse.
export type { RunsSummaryResponse as RunsSummary } from "./runs_summary.generated";

/** Mirrors server StepStatus enum. */
export type StepStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "skipped"
  | "cancelled";

export interface WorkflowEditorDocument extends DAGResponse {
  source: string;
  steps?: WorkflowEditorStep[];
  metadata?: Record<string, unknown> | null;
  read_only?: boolean;
  updated_at?: string | null;
  /** Raw YAML document as JSON — the source of truth for structured edits. */
  document?: Record<string, unknown> | null;
}

export interface WorkflowEditorMutationRequest {
  source: string;
}

export interface WorkflowEditorValidationIssue {
  level: "error" | "warning";
  message: string;
  path?: string | null;
}

export interface WorkflowEditorValidateResponse {
  valid: boolean;
  issues: WorkflowEditorValidationIssue[];
  workflow?: WorkflowEditorDocument;
}

export interface WorkflowEditorSaveResponse {
  saved: boolean;
  workflow: WorkflowEditorDocument;
}

/** Summary of a single run (from GET /api/runs). */
export interface RunSummary {
  filename: string;
  run_id: string | null;
  workflow_name: string | null;
  status: string | null;
  success_rate: number | null;
  total_duration_ms: number | null;
  step_count: number | null;
  failed_step_count: number | null;
  start_time: string | null;
  end_time: string | null;
  evaluation_score?: number | null;
  evaluation_grade?: string | null;
}

/** Full run detail (from GET /api/runs/{filename}). */
export interface RunDetail {
  run_id: string;
  workflow_name: string;
  status: string;
  success_rate: number;
  total_duration_ms: number;
  step_count: number;
  failed_step_count: number;
  start_time: string;
  end_time: string;
  steps: StepResult[];
  dataset?: Record<string, unknown> | null;
  /** Raw workflow inputs captured at run time — replayable via POST /api/run. */
  inputs?: Record<string, unknown> | null;
  extra?: {
    evaluation_requested?: boolean;
    evaluation?: EvaluationResult | null;
    routing?: RunRoutingProvenance;
    [key: string]: unknown;
  } | null;
}

export interface RunRoutingStep {
  step: string;
  tier?: number | null;
  model?: string | null;
  provider?: string | null;
}

export interface RunRoutingProvenance {
  source: "run" | "workflow" | "global" | "default";
  requested_model_override?: string | null;
  pack?: ModelPack | null;
  resolved_steps: RunRoutingStep[];
}

/** Execution profile for runtime configuration. */
export interface ExecutionProfileRequest {
  runtime: "subprocess" | "docker";
  max_attempts?: number;
  max_duration_minutes?: number;
  container_image?: string;
}

/** POST /api/run request. */
export interface WorkflowRunRequest {
  workflow: string;
  input_data: Record<string, unknown>;
  run_id?: string;
  evaluation?: WorkflowEvaluationRequest;
  execution_profile?: ExecutionProfileRequest;
  /**
   * Full prefixed model id (e.g. "ollama:qwen3:8b") applied to every step for
   * this run — langchain adapter only. Omit/null for tier defaults.
   */
  model_override?: string | null;
  /** Immutable named routing-pack selection for this run. */
  model_pack?: ModelPackRef | null;
}

/** POST /api/run response. */
export interface WorkflowRunResponse {
  run_id: string;
  status: StepStatus;
}

/**
 * GET /api/health response. `no_llm_mode` is read live by the server from
 * `AGENTIC_NO_LLM` on every request -- prefer it over any client build-time
 * flag when displaying the server's actual current mode.
 */
export interface HealthCheckResponse {
  status: string;
  version: string;
  no_llm_mode: boolean;
}

export interface WorkflowEvaluationRequest {
  enabled: boolean;
  enforce_hard_gates?: boolean;
  dataset_source: "none" | "repository" | "local";
  dataset_id?: string;
  local_dataset_path?: string;
  sample_index?: number;
  rubric?: string;
  rubric_id?: string;
}

export interface EvaluationDatasetOption {
  id: string;
  name: string;
  source: "repository" | "local";
  description: string;
  sample_count: number | null;
}

export interface EvaluationSetOption {
  id: string;
  name: string;
  description: string;
  datasets: string[];
}

export interface EvaluationDatasetsResponse {
  repository: EvaluationDatasetOption[];
  local: EvaluationDatasetOption[];
  eval_sets: EvaluationSetOption[];
}

export interface EvaluationCriterionScore {
  criterion: string;
  score: number;
  weight: number;
  max_score: number;
}

export interface EvaluationResult {
  enabled: boolean;
  rubric: string;
  criteria: EvaluationCriterionScore[];
  overall_score: number;
  weighted_score: number;
  grade: string;
  passed: boolean;
  pass_threshold: number;
  /** True when the LLM judge layer did not contribute to the hybrid score. */
  judge_skipped?: boolean | null;
  /** Why the judge was skipped, when it was. */
  judge_skip_reason?: string | null;
  /** False when no expected/golden text existed — overlap term was inactive. */
  expected_text_present?: boolean | null;
  generated_at: string;
  dataset?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// WebSocket execution events
// ---------------------------------------------------------------------------
// The server-originating wire shapes below are AUTO-GENERATED from the
// Pydantic contract in `agentic_v2/contracts/events.py`. Regenerate with:
//
//     python scripts/generate_ts_types.py              # in agentic-workflows-v2/
//     npm run generate:types                           # in agentic-workflows-v2/ui/
//
// The `wire-format-drift` CI job fails any PR that changes the Python
// contract without regenerating the TypeScript mirror. See CONTRIBUTING.md.
export type {
  WorkflowStartEvent,
  StepStartEvent,
  StepEndEvent,
  TokenDeltaEvent,
  StepCompleteEvent,
  StepErrorEvent,
  WorkflowEndEvent,
  EvaluationStartEvent,
  EvaluationCompleteEvent,
} from "./events.generated";

import type { ExecutionEvent as WireExecutionEvent } from "./events.generated";

/**
 * Client-only WebSocket event shapes emitted by the streaming channel
 * itself (connection lifecycle, transport-level errors, keepalive pings).
 *
 * These are NOT part of the Python `ExecutionEvent` contract — the server
 * never wraps them in a Pydantic model — so they stay hand-defined here.
 */
export type ChannelEvent =
  | { type: "error"; run_id: string; error: string }
  | { type: "keepalive" }
  | { type: "connection_established"; run_id: string; message: string };

/**
 * Union of every event type the UI handles on the execution WebSocket.
 *
 * Wire events come from `events.generated.ts` (Pydantic-derived).
 * Channel events are transport-level and defined above.
 */
export type ExecutionEvent = WireExecutionEvent | ChannelEvent;

/** Agent info (from GET /api/agents). */
export interface AgentInfo {
  name: string;
  description: string;
  tier: string;
}

// ---------------------------------------------------------------------------
// Epic 6 — Evaluation detail types
// ---------------------------------------------------------------------------

export interface EvaluationCriterionDetail {
  criterion: string;
  weight: number;
  raw_score: number;
  normalized_score: number;
  weighted_contribution: number;
  floor?: number | null;
  floor_violated: boolean;
}

export interface ScoreLayers {
  layer1_objective: number;
  layer2_judge?: number | null;
  layer3_similarity: number;
  layer3_efficiency: number;
  layer3_advisory: number;
}

export interface HardGates {
  required_outputs_present: boolean;
  overall_status_success: boolean;
  no_critical_step_failures: boolean;
  release_build_verified: boolean;
  schema_contract_valid: boolean;
  dataset_workflow_compatible: boolean;
}

export interface FloorViolation {
  criterion: string;
  floor: number;
  normalized_score: number;
}

export interface EvaluationStepScore {
  step_name: string;
  status: string;
  score: number;
  [key: string]: unknown;
}

export interface RunEvaluationDetail {
  enabled: boolean;
  rubric: string;
  rubric_id: string;
  rubric_version: string;
  criteria: EvaluationCriterionDetail[];
  overall_score: number;
  weighted_score: number;
  objective_weighted_score: number;
  grade: string;
  grade_capped: boolean;
  passed: boolean;
  pass_threshold: number;
  hard_gates?: HardGates | null;
  hard_gate_failures: string[];
  floor_violations: FloorViolation[];
  step_scores: EvaluationStepScore[];
  score_layers?: ScoreLayers | null;
  hybrid_weights: Record<string, number>;
  judge?: Record<string, unknown> | null;
  /** True when the LLM judge layer did not contribute to the hybrid score. */
  judge_skipped?: boolean;
  /** Why the judge was skipped (e.g. no backend configured), when it was. */
  judge_skip_reason?: string | null;
  /** Machine-readable skip cause: "not_configured" | "judge_error". */
  judge_skip_code?: string | null;
  /** False when no expected/golden text existed — overlap term was inactive. */
  expected_text_present?: boolean | null;
  generated_at: string;
  dataset?: Record<string, unknown> | null;
}

/** Response for GET /api/runs/{filename}/evaluation */
export interface RunEvaluationDetailResponse {
  filename: string;
  run_id: string | null;
  workflow_name: string | null;
  status: string | null;
  evaluation_requested: boolean;
  dataset?: Record<string, unknown> | null;
  evaluation?: RunEvaluationDetail | null;
  /** Why evaluation is null although requested (e.g. judge_required unmet). */
  evaluation_error?: string | null;
}

// ---------------------------------------------------------------------------
// Epic 6 — Dataset sample browser types
// ---------------------------------------------------------------------------

export interface DatasetSampleSummary {
  sample_index: number;
  sample_id?: string | null;
  task_id?: string | null;
  title: string;
  summary: string;
  field_names: string[];
}

/** Response for GET /api/eval/datasets/sample-list */
export interface DatasetSampleListResponse {
  dataset_source: string;
  dataset_id: string;
  sample_count: number;
  offset: number;
  limit: number;
  samples: DatasetSampleSummary[];
}

/** Response for GET /api/eval/datasets/sample-detail */
export interface DatasetSampleDetailResponse {
  dataset_source: string;
  dataset_id: string;
  sample_index: number;
  sample_id?: string | null;
  task_id?: string | null;
  field_names: string[];
  summary: string;
  sample: Record<string, unknown>;
  dataset_meta: Record<string, unknown>;
  workflow_preview?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Local model finder types
// ---------------------------------------------------------------------------

export type ModelTaskCategory =
  | "general"
  | "swe"
  | "biomed"
  | "physics"
  | "math"
  | "vision";

export type ModelSortField =
  | "downloads"
  | "release_date"
  | "likes"
  | "forks"
  | "fit";

export interface LocalAccelerator {
  kind: "gpu" | "npu";
  name: string;
  memory_gb?: number | null;
  vendor?: string | null;
  /** Vendor-rated peak throughput in TOPS, when known. */
  tops?: number | null;
}

export interface SystemProfile {
  os: string;
  architecture: string;
  cpu_name: string;
  cpu_cores_logical: number;
  cpu_cores_physical?: number | null;
  cpu_max_mhz?: number | null;
  ram_gb: number;
  accelerators: LocalAccelerator[];
  /** Aggregate system TOPS estimate across accelerators, when known. */
  system_tops?: number | null;
  estimated_cinebench_r23_multi: number;
  estimated_tokens_per_second_7b_q4: number;
  performance_tier: "entry" | "mainstream" | "workstation" | "accelerated";
  notes: string[];
}

export interface ModelCandidate {
  id: string;
  name: string;
  provider: string;
  categories: ModelTaskCategory[];
  downloads: number;
  likes: number;
  forks: number;
  release_date: string;
  parameters_b: number;
  quantization: string;
  min_ram_gb: number;
  recommended_ram_gb: number;
  min_vram_gb: number;
  context_tokens: number;
  license: string;
  url: string;
  fit_score: number;
  fit_reason: string;
  runnable: boolean;
}

export interface ModelRecommendationResponse {
  profile: SystemProfile;
  models: ModelCandidate[];
  sort_order: string[];
  category: ModelTaskCategory | "all";
}

/**
 * One model from the live provider probe — the static tier-chain catalog plus
 * models discovered live from Ollama, LM Studio, and local runtimes. `cloud`,
 * `capabilities`, and `running` are present only when the provider exposes
 * those facts.
 */
export interface ProbedModel {
  id: string;
  provider: string;
  tier: number;
  available: boolean;
  /** True for Ollama cloud-hosted models (ollama.com / remote_host). */
  cloud?: boolean;
  /** Model capabilities from /api/tags, e.g. "tools", "thinking", "vision". */
  capabilities?: string[];
  /** True when the model is currently loaded in memory (/api/ps). */
  running?: boolean;
}

/**
 * Response from `GET /api/models/probe` — re-probes which LLM providers have
 * credentials and returns the full known model catalog with per-model tier and
 * availability. `no_llm_mode` reflects whether the runtime is forced onto the
 * deterministic placeholder model.
 */
export interface ModelProbeResponse {
  available_providers: string[];
  unavailable_providers: string[];
  tier_defaults: Record<string, string>;
  models: ProbedModel[];
  no_llm_mode: boolean;
}

/** Response from `POST /api/models/lmstudio/load`. */
export interface LmStudioLoadResponse {
  model: string;
  status: "loaded" | "already_loaded";
  instance_id: string | null;
  load_time_seconds: number | null;
  running: boolean;
}

// ---------------------------------------------------------------------------
// Catalog types (personas / tools / observers) — GET /api/personas|tools|observers
// ---------------------------------------------------------------------------

export interface PersonaInfo {
  id: string;
  name: string;
  role: string;
  description: string;
  tags: string[];
  prompt_preview: string;
}

export interface ListPersonasResponse {
  personas: PersonaInfo[];
}

export interface ToolInfo {
  name: string;
  description: string;
  tiers: number[];
}

export interface ListToolsResponse {
  tools: ToolInfo[];
}

export interface ObserverInfo {
  id: string;
  description: string;
}

export interface ListObserversResponse {
  observers: ObserverInfo[];
}

// ---------------------------------------------------------------------------
// Provider settings — GET/PUT /api/settings/providers
// ---------------------------------------------------------------------------

export type ProviderType =
  | "openai"
  | "anthropic"
  | "gh"
  | "ollama"
  | "foundry_local"
  | "custom";

export interface ProviderEndpointConfig {
  id: string;
  type: ProviderType;
  label: string;
  base_url?: string | null;
  /** Name of the env var holding the credential — never the secret itself. */
  api_key_env?: string | null;
  default_model?: string | null;
  enabled: boolean;
  options: Record<string, unknown>;
}

export interface ProviderSettingsResponse {
  providers: ProviderEndpointConfig[];
  provider_types: ProviderType[];
  env_configured_providers: string[];
}

export interface ProviderProbeResponse {
  provider_id: string;
  status: "available" | "unavailable" | "error";
  checked_at: string;
  latency_ms: number;
  discovered_model_count: number;
  error_category?: string | null;
  detail: string;
}

// ---------------------------------------------------------------------------
// Tier settings — GET/PUT /api/settings/tiers
// ---------------------------------------------------------------------------

export interface TierChain {
  tier: number;
  default_chain: string[];
  override: string[];
  effective: string[];
}

export interface TierModelInfo {
  id: string;
  provider: string;
  capabilities: string[];
  capability_overridden: boolean;
}

export interface TierSettingsResponse {
  tiers: TierChain[];
  models: TierModelInfo[];
  known_capabilities: string[];
}

export interface TierSettingsUpdateRequest {
  tier_overrides?: Record<string, string[]>;
  model_capabilities?: Record<string, string[]>;
}

// ---------------------------------------------------------------------------
// Versioned model packs — /api/settings/model-packs
// ---------------------------------------------------------------------------

export interface ModelPackRef {
  id: string;
  version: number;
}

export type ModelPackSource =
  | "effective"
  | "defaults"
  | "explicit"
  | "duplicate"
  | "imported";

export interface ModelPack {
  id: string;
  name: string;
  description: string;
  version: number;
  created_at: string;
  updated_at: string;
  archived: boolean;
  tier_chains: Record<string, string[]>;
  allowed_providers: string[];
  capability_requirements: Record<string, string[]>;
  model_capabilities: Record<string, string[]>;
  judge_model?: string | null;
  source: ModelPackSource;
}

export interface ModelPackCreateRequest {
  id: string;
  name: string;
  description?: string;
  source?: ModelPackSource;
  tier_chains?: Record<string, string[]>;
  allowed_providers?: string[];
  capability_requirements?: Record<string, string[]>;
  model_capabilities?: Record<string, string[]>;
  judge_model?: string | null;
}

export interface ModelPackUpdateRequest {
  name?: string;
  description?: string;
  tier_chains?: Record<string, string[]>;
  allowed_providers?: string[];
  capability_requirements?: Record<string, string[]>;
  model_capabilities?: Record<string, string[]>;
  judge_model?: string | null;
}

export interface ModelPackListResponse {
  packs: ModelPack[];
  active?: ModelPackRef | null;
  workflow_bindings: Record<string, ModelPackRef>;
}

export interface ModelPackIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  tier?: number | null;
  model?: string | null;
}

export interface ModelPackValidationResponse {
  ref: ModelPackRef;
  valid: boolean;
  issues: ModelPackIssue[];
  candidate_chains: Record<string, string[]>;
}

export interface ModelPackDependenciesResponse {
  ref: ModelPackRef;
  globally_active: boolean;
  workflows: string[];
  recent_run_ids: string[];
}

export interface ModelPackExportResponse {
  schema_version: 1;
  pack: ModelPack;
}

// ---------------------------------------------------------------------------
// Eval comparison — POST /api/eval/compare
// ---------------------------------------------------------------------------

export interface EvalComparisonRequest {
  run_a: string;
  run_b: string;
  rubric_id?: string | null;
  enforce_hard_gates?: boolean;
  judge_model?: string | null;
}

export interface EvalCandidateSummary {
  filename: string;
  run_id: string | null;
  workflow_name: string | null;
  weighted_score: number;
  overall_score: number;
  grade: string;
  passed: boolean;
  criteria: EvaluationCriterionDetail[];
}

export interface CriterionDelta {
  criterion: string;
  score_a: number | null;
  score_b: number | null;
  delta: number | null;
}

export interface EvalComparisonResponse {
  candidate_a: EvalCandidateSummary;
  candidate_b: EvalCandidateSummary;
  criteria_deltas: CriterionDelta[];
  weighted_score_delta: number;
  winner: "a" | "b" | "tie";
  rubric_id: string;
}

// ---------------------------------------------------------------------------
// Chat playground — POST /api/chat (SSE stream)
// ---------------------------------------------------------------------------
// Hand-maintained mirror of the Pydantic contract in
// `agentic_v2/contracts/chat.py`. The endpoint answers HTTP 200 with
// `text/event-stream` frames (`data: <json>\n\n`); every stream terminates
// with exactly one `done` OR one `error` event. Provider failures (unknown
// prefix, missing key, 401, 429, connection refused) arrive as in-stream
// `error` events — never as HTTP 4xx/5xx (only FastAPI request validation
// stays a native 422).

/** Author role for one chat playground message. */
export type ChatRole = "system" | "user" | "assistant";

export interface ChatTextPart {
  type: "text";
  text: string;
}

export interface ChatImagePart {
  type: "image_url";
  url: string;
  detail?: "auto" | "low" | "high";
}

export type ChatContentPart = ChatTextPart | ChatImagePart;

/** One turn of the playground transcript. */
export interface ChatMessage {
  role: ChatRole;
  content: string | ChatContentPart[];
}

interface ChatRequestBase {
  /** Running transcript; the server requires at least one message. */
  messages: ChatMessage[];
  /** Sampling temperature (0.0–2.0); the server defaults it to 0.2. */
  temperature?: number;
}

/** Direct-model overload for POST /api/chat. */
export interface ModelChatRequest extends ChatRequestBase {
  /** FULL prefixed id, e.g. "openrouter:meta-llama/llama-3.1-8b-instruct:free". */
  model: string;
  tier?: never;
}

/** Tier-routed overload for POST /api/chat. */
export interface TierChatRequest extends ChatRequestBase {
  tier: 1 | 2 | 3 | 4 | 5;
  model?: never;
}

/** POST /api/chat accepts exactly one routing constructor. */
export type ChatRequest = ModelChatRequest | TierChatRequest;

/** Incremental completion text. */
export interface ChatTokenEvent {
  type: "token";
  delta: string;
}

/** Selected model for a tier request, emitted before completion output. */
export interface ChatRouteEvent {
  type: "route";
  requested_tier: 1 | 2 | 3 | 4 | 5;
  model: string;
}

/** A safe raster image returned by a multimodal model. */
export interface ChatMediaEvent {
  type: "media";
  mime_type: "image/png" | "image/jpeg" | "image/webp" | "image/gif";
  url: string;
  alt: string;
}

/** Terminal success frame — echoes the model that produced the reply. */
export interface ChatDoneEvent {
  type: "done";
  model: string;
}

/** Terminal failure frame; `category` is an ErrorCode value (e.g. "auth_error"). */
export interface ChatErrorEvent {
  type: "error";
  message: string;
  category: string;
}

/** Discriminated union ("type") of every frame on the chat stream. */
export type ChatStreamEvent =
  | ChatRouteEvent
  | ChatTokenEvent
  | ChatMediaEvent
  | ChatDoneEvent
  | ChatErrorEvent;

/** The discriminator values carried by `ChatStreamEvent`. */
export type ChatStreamEventType = ChatStreamEvent["type"];
