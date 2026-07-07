import type {
  AgentInfo,
  DAGResponse,
  DAGEdge,
  DAGNode,
  DatasetSampleDetailResponse,
  DatasetSampleListResponse,
  EvalComparisonRequest,
  EvalComparisonResponse,
  EvaluationDatasetsResponse,
  ListObserversResponse,
  ListPersonasResponse,
  ListToolsResponse,
  ProviderEndpointConfig,
  ProviderSettingsResponse,
  RunDetail,
  RunEvaluationDetailResponse,
  RunSummary,
  RunsSummary,
  StepModelParams,
  TierSettingsResponse,
  TierSettingsUpdateRequest,
  WorkflowEditorDocument,
  WorkflowEditorMutationRequest,
  WorkflowEditorSaveResponse,
  WorkflowEditorValidateResponse,
  WorkflowRunRequest,
  WorkflowRunResponse,
  ModelProbeResponse,
  ModelRecommendationResponse,
  ModelSortField,
  ModelTaskCategory,
} from "./types";

const BASE = "/api";

function toDisplayString(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const requestUrl =
    globalThis.window !== undefined && url.startsWith("/")
      ? new URL(url, globalThis.window.location.origin).toString()
      : url;

  const res = await fetch(requestUrl, init);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

type WorkflowEditorApiResponse = {
  name: string;
  path: string;
  yaml_text: string;
  document: Record<string, unknown>;
  step_count: number;
};

type WorkflowValidationApiResponse = {
  valid: boolean;
  name: string;
  step_count: number;
  yaml_text: string;
};

function toWorkflowEditorDocument(
  response: WorkflowEditorApiResponse
): WorkflowEditorDocument {
  const document = response.document ?? {};
  const rawSteps = Array.isArray(document.steps)
    ? document.steps.filter(
        (step): step is Record<string, unknown> =>
          typeof step === "object" && step !== null
      )
    : [];

  const nodes: DAGNode[] = rawSteps.map((step) => ({
    id: toDisplayString(step.name),
    agent: typeof step.agent === "string" ? step.agent : null,
    description: typeof step.description === "string" ? step.description : "",
    depends_on: Array.isArray(step.depends_on)
      ? step.depends_on.filter((value): value is string => typeof value === "string")
      : [],
    tier: typeof step.tier === "string" ? step.tier : null,
  }));

  const edges: DAGEdge[] = nodes.flatMap((node) =>
    node.depends_on.map((source) => ({ source, target: node.id }))
  );

  const steps = rawSteps.map((step) => ({
    name: toDisplayString(step.name),
    agent: typeof step.agent === "string" ? step.agent : null,
    description: typeof step.description === "string" ? step.description : null,
    tier: typeof step.tier === "string" ? step.tier : null,
    depends_on: Array.isArray(step.depends_on)
      ? step.depends_on.filter((value): value is string => typeof value === "string")
      : [],
    when: typeof step.when === "string" ? step.when : null,
    loop_until: typeof step.loop_until === "string" ? step.loop_until : null,
    loop_max: typeof step.loop_max === "number" ? step.loop_max : null,
    tools: Array.isArray(step.tools)
      ? step.tools.filter((value): value is string => typeof value === "string")
      : [],
    prompt_file: typeof step.prompt_file === "string" ? step.prompt_file : null,
    model:
      typeof step.model === "string"
        ? step.model
        : typeof step.model_override === "string"
          ? step.model_override
          : null,
    persona: typeof step.persona === "string" ? step.persona : null,
    observers: Array.isArray(step.observers)
      ? step.observers.filter(
          (value): value is string => typeof value === "string"
        )
      : null,
    model_params: toStepModelParams(step.model_params),
    metadata:
      typeof step.metadata === "object" && step.metadata !== null
        ? (step.metadata as Record<string, unknown>)
        : null,
  }));

  return {
    name: response.name,
    description:
      typeof document.description === "string" ? document.description : "",
    source: response.yaml_text,
    nodes,
    edges,
    steps,
    document,
    metadata:
      typeof document.metadata === "object" && document.metadata !== null
        ? (document.metadata as Record<string, unknown>)
        : null,
    read_only: false,
    updated_at: null,
  };
}

function toStepModelParams(value: unknown): StepModelParams | null {
  if (typeof value !== "object" || value === null) return null;
  const raw = value as Record<string, unknown>;
  const params: StepModelParams = {};
  if (typeof raw.temperature === "number") params.temperature = raw.temperature;
  if (typeof raw.top_p === "number") params.top_p = raw.top_p;
  if (typeof raw.max_tokens === "number") params.max_tokens = raw.max_tokens;
  return Object.keys(params).length > 0 ? params : null;
}

/** List available workflow names. */
export function listWorkflows(): Promise<{ workflows: string[] }> {
  return fetchJSON(`${BASE}/workflows`);
}

/** Get DAG structure for a workflow. */
export function getWorkflowDAG(name: string): Promise<DAGResponse> {
  return fetchJSON(`${BASE}/workflows/${encodeURIComponent(name)}/dag`);
}

/** Load editable workflow state for the builder UI. */
export function getWorkflowEditor(name: string): Promise<WorkflowEditorDocument> {
  return fetchJSON<WorkflowEditorApiResponse>(
    `${BASE}/workflows/${encodeURIComponent(name)}/editor`
  ).then(toWorkflowEditorDocument);
}

/** Save edited workflow source. */
export function saveWorkflowEditor(
  name: string,
  request: WorkflowEditorMutationRequest
): Promise<WorkflowEditorSaveResponse> {
  return fetchJSON<WorkflowEditorApiResponse>(`${BASE}/workflows/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml_text: request.source }),
  }).then((workflow) => ({
    saved: true,
    workflow: {
      ...toWorkflowEditorDocument(workflow),
      updated_at: new Date().toISOString(),
    },
  }));
}

/** Save a structured workflow document (JSON form of the YAML). */
export function saveWorkflowEditorDocument(
  name: string,
  document: Record<string, unknown>
): Promise<WorkflowEditorSaveResponse> {
  return fetchJSON<WorkflowEditorApiResponse>(
    `${BASE}/workflows/${encodeURIComponent(name)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document }),
    }
  ).then((workflow) => ({
    saved: true,
    workflow: {
      ...toWorkflowEditorDocument(workflow),
      updated_at: new Date().toISOString(),
    },
  }));
}

/** Validate edited workflow source without saving. */
export function validateWorkflowEditor(
  name: string,
  request: WorkflowEditorMutationRequest
): Promise<WorkflowEditorValidateResponse> {
  return fetchJSON<WorkflowValidationApiResponse>(`${BASE}/workflows/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: request.source, name }),
  }).then((response) => ({
    valid: response.valid,
    issues: [],
    workflow: {
      name: response.name,
      description: "",
      source: response.yaml_text,
      nodes: [],
      edges: [],
      steps: [],
      metadata: null,
      read_only: false,
      updated_at: null,
    },
  }));
}

/** Validate a structured workflow document without saving. */
export function validateWorkflowEditorDocument(
  name: string,
  document: Record<string, unknown>
): Promise<WorkflowEditorValidateResponse> {
  return fetchJSON<WorkflowValidationApiResponse>(`${BASE}/workflows/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document, name }),
  }).then((response) => ({
    valid: response.valid,
    issues: [],
    workflow: {
      name: response.name,
      description: "",
      source: response.yaml_text,
      nodes: [],
      edges: [],
      steps: [],
      metadata: null,
      read_only: false,
      updated_at: null,
    },
  }));
}

/** List past runs. */
export function listRuns(workflow?: string, limit = 50): Promise<RunSummary[]> {
  const params = new URLSearchParams();
  if (workflow) params.set("workflow", workflow);
  params.set("limit", String(limit));
  return fetchJSON(`${BASE}/runs?${params}`);
}

/** Get full run detail. */
export function getRunDetail(filename: string): Promise<RunDetail> {
  return fetchJSON(`${BASE}/runs/${encodeURIComponent(filename)}`);
}

/** Get aggregate run stats. */
export function getRunsSummary(workflow?: string): Promise<RunsSummary> {
  const params = workflow ? `?workflow=${encodeURIComponent(workflow)}` : "";
  return fetchJSON(`${BASE}/runs/summary${params}`);
}

/** Trigger a workflow run. */
export function runWorkflow(
  request: WorkflowRunRequest
): Promise<WorkflowRunResponse> {
  return fetchJSON(`${BASE}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** List repository and local datasets for evaluation mode. */
export function listEvaluationDatasets(): Promise<EvaluationDatasetsResponse> {
  return fetchJSON(`${BASE}/eval/datasets`);
}

/** Preview how dataset sample fields will map to workflow inputs. */
export function previewDatasetInputs(
  workflowName: string,
  datasetSource: string,
  datasetId: string,
  sampleIndex: number
): Promise<{
  compatible: boolean;
  reasons: string[];
  adapted_inputs: Record<string, unknown>;
  dataset_meta: Record<string, unknown>;
}> {
  const params = new URLSearchParams({
    dataset_source: datasetSource,
    dataset_id: datasetId,
    sample_index: String(sampleIndex),
  });
  return fetchJSON(
    `${BASE}/workflows/${encodeURIComponent(workflowName)}/preview-dataset-inputs?${params}`
  );
}

/** List available agents. */
export function listAgents(): Promise<{ agents: AgentInfo[] }> {
  return fetchJSON(`${BASE}/agents`);
}

/** Get full rubric evaluation detail for a scored run. */
export function getRunEvaluationDetail(
  filename: string
): Promise<RunEvaluationDetailResponse> {
  return fetchJSON(`${BASE}/runs/${encodeURIComponent(filename)}/evaluation`);
}

/** Re-score a previously-completed run by replaying its captured log. */
export function evaluateRun(
  filename: string
): Promise<RunEvaluationDetailResponse> {
  return fetchJSON(`${BASE}/runs/${encodeURIComponent(filename)}/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
}

function encodeDatasetPath(datasetSource: string, datasetId: string): string {
  const encodedDatasetId = datasetId
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");

  return `${encodeURIComponent(datasetSource)}/${encodedDatasetId}`;
}

/** List paginated dataset sample summaries. */
export function listDatasetSamples(
  datasetSource: string,
  datasetId: string,
  offset = 0,
  limit = 20,
  workflow?: string
): Promise<DatasetSampleListResponse> {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  if (workflow) params.set("workflow", workflow);
  const datasetPath = encodeDatasetPath(datasetSource, datasetId);
  return fetchJSON(
    `${BASE}/eval/datasets/${datasetPath}/samples?${params}`
  );
}

/** Get full detail for a single dataset sample. */
export function getDatasetSampleDetail(
  datasetSource: string,
  datasetId: string,
  sampleIndex: number,
  workflow?: string
): Promise<DatasetSampleDetailResponse> {
  const params = new URLSearchParams();
  if (workflow) params.set("workflow", workflow);
  const queryString = params.toString();
  const datasetPath = encodeDatasetPath(datasetSource, datasetId);
  const url = `${BASE}/eval/datasets/${datasetPath}/samples/${sampleIndex}`;
  return fetchJSON(queryString ? `${url}?${queryString}` : url);
}

/** Get local hardware-aware model recommendations. */
export function getModelRecommendations(
  category: ModelTaskCategory | "all" = "all",
  sortBy: ModelSortField = "downloads",
): Promise<ModelRecommendationResponse> {
  const params = new URLSearchParams({ category, sort_by: sortBy });
  return fetchJSON(`${BASE}/model-finder/recommendations?${params}`);
}

/**
 * Re-probe LLM providers and load the full known model catalog with per-model
 * tier and live availability. Drives the model-router "rescan".
 */
export function probeModels(): Promise<ModelProbeResponse> {
  return fetchJSON(`${BASE}/models/probe`);
}

/** List pre-canned personas for the node persona picker. */
export function listPersonas(): Promise<ListPersonasResponse> {
  return fetchJSON(`${BASE}/personas`);
}

/** List tools available for per-step allowlisting. */
export function listTools(): Promise<ListToolsResponse> {
  return fetchJSON(`${BASE}/tools`);
}

/** List observer channels a step can enable. */
export function listObservers(): Promise<ListObserversResponse> {
  return fetchJSON(`${BASE}/observers`);
}

/** Get user-configured provider endpoints. */
export function getProviderSettings(): Promise<ProviderSettingsResponse> {
  return fetchJSON(`${BASE}/settings/providers`);
}

/** Replace the provider endpoint list. */
export function putProviderSettings(
  providers: ProviderEndpointConfig[]
): Promise<ProviderSettingsResponse> {
  return fetchJSON(`${BASE}/settings/providers`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ providers }),
  });
}

/** Get tier rankings and model capability tags. */
export function getTierSettings(): Promise<TierSettingsResponse> {
  return fetchJSON(`${BASE}/settings/tiers`);
}

/** Update tier rerank overrides and/or capability tags (merge-per-key). */
export function putTierSettings(
  update: TierSettingsUpdateRequest
): Promise<TierSettingsResponse> {
  return fetchJSON(`${BASE}/settings/tiers`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
}

/** Score two completed runs under one rubric, head-to-head. */
export function compareRuns(
  request: EvalComparisonRequest
): Promise<EvalComparisonResponse> {
  return fetchJSON(`${BASE}/eval/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** Health check. */
export function healthCheck(): Promise<{ status: string; version: string }> {
  return fetchJSON(`${BASE}/health`);
}
