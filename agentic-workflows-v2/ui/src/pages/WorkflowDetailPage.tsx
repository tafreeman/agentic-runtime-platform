import { useId, useMemo, useRef, useState } from "react";
import { Link, useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Play, ArrowLeft, Loader2, Pencil, CircleAlert } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useWorkflowDAG } from "../hooks/useWorkflows";
import { useRuns } from "../hooks/useRuns";
import { runWorkflow } from "../api/client";
import { useApiAvailability } from "../hooks/useApiAvailability";
import { describeApiError } from "../lib/apiErrors";
import InlineError from "../components/states/InlineError";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import RunList from "../components/runs/RunList";
import RunConfigForm, {
  type InitialEvaluationConfig,
  type RunConfigValues,
} from "../components/runs/RunConfigForm";
import { isWorkflowBuilderEnabled } from "../config/featureFlags";
import BTopBar from "../components/layout/BTopBar";

function defaultInputValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

/** Parse object/array-typed inputs from JSON, falling back to the raw string. */
function coerceInputValue(
  type: string | undefined,
  val: string,
): unknown {
  if (type === "object" || type === "array") {
    try {
      return JSON.parse(val);
    } catch {
      return val;
    }
  }
  return val;
}

/**
 * Capability-tier mark classes for a tier hint ("tier0".."tier5"), using the
 * shared tier tokens the DAG step nodes use: T0–T2 low, T3 mid, T4–T5 high.
 * The tier label always rides alongside the color, never color alone.
 */
function tierClass(tier: string): string {
  const match = /(\d+)/.exec(tier);
  if (!match) return "border-el-divider text-el-muted";
  const level = Number(match[1]);
  if (level <= 2) return "border-el-tier-low text-el-tier-low";
  if (level === 3) return "border-el-tier-mid text-el-tier-mid";
  return "border-el-tier-high text-el-tier-high";
}

/** Thrown before any request when required run inputs are empty. */
class RunInputError extends Error {}

/** Summary + remedy for a failed run start (client validation or API). */
function describeRunError(error: unknown): { summary: string; remedy: string } {
  if (error instanceof RunInputError) {
    return {
      summary: error.message,
      remedy: "Fill in the required inputs, then run again.",
    };
  }
  const { summary, remedy } = describeApiError(error);
  return { summary, remedy };
}

/**
 * Top-bar action chrome: visually compact (28px) to sit in the 36px bar, with
 * the hit area expanded to 36px by an invisible ::after.
 */
const BAR_ACTION_CLASS =
  "focus-ring relative inline-flex h-7 items-center gap-1.5 rounded-md px-3 font-mono text-micro transition-colors after:absolute after:-inset-1 disabled:cursor-not-allowed disabled:opacity-45";
const BAR_GHOST_CLASS = `${BAR_ACTION_CLASS} border border-el-divider text-el-secondary hover:bg-el-hover hover:text-el-ink`;
const BAR_PRIMARY_CLASS = `${BAR_ACTION_CLASS} bg-el-action font-semibold text-el-action-ink hover:bg-el-action/90`;

/** Panel section overline. */
const PANEL_OVERLINE_CLASS =
  "font-mono text-micro font-bold uppercase tracking-wider text-el-secondary";

/** Distinct, ordered tier hints present across the DAG nodes. */
function collectTiers(nodes: { tier?: string | null }[] | undefined): string[] {
  const seen = new Set<string>();
  for (const node of nodes ?? []) {
    if (node.tier) seen.add(node.tier);
  }
  return [...seen];
}

/** Label for the primary run button across batch/pending/eval/idle states. */
function runButtonLabel(
  batchProgress: { done: number; total: number } | null,
  isPending: boolean,
  evaluationEnabled: boolean,
): string {
  if (batchProgress) return `${batchProgress.done}/${batchProgress.total}`;
  if (isPending) return "[…] starting";
  if (evaluationEnabled) return "[▶] run + eval";
  return "[▶] run";
}

/**
 * Build the per-sample evaluation request payload, resolving which dataset
 * source (eval-set repository, dataset repository/local, or none) applies.
 */
function buildEvalRequest(
  evaluation: RunConfigValues["evaluation"],
  rubricId: string,
  sampleIndex: number,
) {
  if (!evaluation.enabled) return undefined;
  if (evaluation.datasetSource === "eval_set" && evaluation.evalSetId) {
    return {
      enabled: true as const,
      dataset_source: "repository" as const,
      dataset_id: evaluation.evalSetId,
      sample_index: sampleIndex,
      rubric_id: rubricId || undefined,
    };
  }
  if (evaluation.datasetSource !== "none" && evaluation.datasetId) {
    return {
      enabled: true as const,
      dataset_source: evaluation.datasetSource as "repository" | "local",
      dataset_id: evaluation.datasetId,
      sample_index: sampleIndex,
      rubric_id: rubricId || undefined,
    };
  }
  return {
    enabled: true as const,
    dataset_source: "none" as const,
    sample_index: sampleIndex,
    rubric_id: rubricId || undefined,
  };
}

/** Dataset sources accepted from the `eval_source` deep-link param. */
const DEEP_LINK_SOURCES = ["repository", "local", "eval_set"] as const;

type DeepLinkSource = (typeof DEEP_LINK_SOURCES)[number];

/**
 * Parse the run-prefill deep link (`?eval_source=&eval_dataset=&samples=&runs=`)
 * into RunConfigForm seed values, or undefined when absent/invalid.
 */
function parseEvalDeepLink(
  params: URLSearchParams,
): InitialEvaluationConfig | undefined {
  const source = params.get("eval_source");
  const dataset = params.get("eval_dataset");
  if (!dataset || !DEEP_LINK_SOURCES.includes(source as DeepLinkSource)) {
    return undefined;
  }
  const typedSource = source as DeepLinkSource;
  const runsRaw = params.get("runs");
  const runs = runsRaw ? Number.parseInt(runsRaw, 10) : Number.NaN;
  return {
    datasetSource: typedSource,
    datasetId: typedSource === "eval_set" ? "" : dataset,
    evalSetId: typedSource === "eval_set" ? dataset : undefined,
    sampleText: params.get("samples") ?? "0",
    runsPerRecord: Number.isInteger(runs) && runs > 0 ? runs : undefined,
  };
}

/** Expand selected samples × runs-per-record into a flat job list. */
function buildJobList(
  evaluation: RunConfigValues["evaluation"],
): Array<{ sampleIndex: number }> {
  const samples =
    evaluation.enabled && evaluation.selectedSamples.length > 0
      ? evaluation.selectedSamples
      : [0];
  const runsPerRecord = evaluation.enabled ? (evaluation.runsPerRecord ?? 1) : 1;

  const jobs: Array<{ sampleIndex: number }> = [];
  for (const s of samples) {
    for (let r = 0; r < runsPerRecord; r++) {
      jobs.push({ sampleIndex: s });
    }
  }
  return jobs;
}

export default function WorkflowDetailPage() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialEvaluation = useMemo(
    () => parseEvalDeepLink(searchParams),
    [searchParams],
  );
  const workflowBuilderEnabled = isWorkflowBuilderEnabled();
  const {
    data: dag,
    isLoading: dagLoading,
    isError: dagError,
    error: dagQueryError,
  } = useWorkflowDAG(name);
  const {
    data: runs,
    isLoading: runsLoading,
    isError: runsError,
    error: runsQueryError,
    refetch: refetchRuns,
  } = useRuns(name);
  const dagFailure = dagError ? describeApiError(dagQueryError) : null;
  const runsFailure = runsError ? describeApiError(runsQueryError) : null;
  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const apiDownReasonId = useId();
  const hasWorkflowSteps = (dag?.nodes.length ?? 0) > 0;
  const tiers = collectTiers(dag?.nodes);
  const supportsDeterministicDemo =
    name === "test_deterministic" ||
    (!!dag &&
      dag.nodes.length > 0 &&
      dag.nodes.every((node) => node.tier?.toLowerCase().startsWith("tier0")));

  const configRef = useRef<RunConfigValues>({
    inputValues: {},
    executionProfile: { runtime: "subprocess" },
    rubricId: "",
    modelOverride: "",
    modelPack: null,
    evaluation: {
      enabled: false,
      datasetSource: "none",
      datasetId: "",
      evalSetId: "",
      selectedSamples: [0],
      runsPerRecord: 1,
    },
  });

  const buildInputData = (): Record<string, unknown> => {
    const data: Record<string, unknown> = {};
    if (!dag?.inputs) return data;
    const vals = configRef.current.inputValues;
    for (const inp of dag.inputs) {
      const val = vals[inp.name] ?? defaultInputValue(inp.default);
      if (!val && !inp.required) continue;
      data[inp.name] = coerceInputValue(inp.type, val);
    }
    return data;
  };

  /** Required inputs that would be sent empty — mirrors buildInputData. */
  const missingRequiredInputs = (): string[] => {
    if (!dag?.inputs) return [];
    const vals = configRef.current.inputValues;
    return dag.inputs
      .filter((inp) => {
        if (!inp.required) return false;
        const val = vals[inp.name] ?? defaultInputValue(inp.default);
        return !val.trim();
      })
      .map((inp) => inp.name);
  };

  const buildDemoInputData = (): Record<string, unknown> => {
    const data: Record<string, unknown> = {};
    for (const input of dag?.inputs ?? []) {
      const configured = configRef.current.inputValues[input.name];
      const declared = defaultInputValue(input.default);
      let value = configured || declared || input.enum?.[0] || "";
      if (!value && input.required) {
        if (input.type === "number") value = "1";
        else if (input.type === "boolean") value = "true";
        else if (input.type === "object") value = "{}";
        else if (input.type === "array") value = "[]";
        else value = "hello";
      }
      if (value || input.required) {
        data[input.name] = coerceInputValue(input.type, value);
      }
    }
    return data;
  };

  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null);

  const runMutation = useMutation({
    mutationFn: async () => {
      const { executionProfile, rubricId, evaluation, modelOverride, modelPack } =
        configRef.current;
      // Dataset-backed evaluation fills inputs from the dataset sample
      // server-side, so only enforce form inputs for plain runs.
      const probeEval = buildEvalRequest(evaluation, rubricId, 0);
      const datasetBacked =
        probeEval != null && probeEval.dataset_source !== "none";
      if (!datasetBacked) {
        const missing = missingRequiredInputs();
        if (missing.length > 0) {
          throw new RunInputError(
            `required input${missing.length > 1 ? "s" : ""} ${missing
              .map((m) => `'${m}'`)
              .join(", ")} must not be empty`,
          );
        }
      }
      // Only serialize model_override when a concrete override is selected —
      // "" means "tier default" and must stay off the wire.
      const overrideField = modelOverride
        ? { model_override: modelOverride }
        : {};
      const packField = modelPack ? { model_pack: modelPack } : {};

      const jobs = buildJobList(evaluation);
      const isBatch = jobs.length > 1;

      if (!isBatch) {
        return runWorkflow({
          workflow: name!,
          input_data: buildInputData(),
          evaluation: buildEvalRequest(
            evaluation,
            rubricId,
            jobs[0] ? jobs[0].sampleIndex : 0,
          ),
          execution_profile: executionProfile,
          ...packField,
          ...overrideField,
        });
      }

      setBatchProgress({ done: 0, total: jobs.length });
      for (let i = 0; i < jobs.length; i++) {
        await runWorkflow({
          workflow: name!,
          input_data: buildInputData(),
          evaluation: buildEvalRequest(
            evaluation,
            rubricId,
            jobs[i]?.sampleIndex ?? 0,
          ),
          execution_profile: executionProfile,
          ...packField,
          ...overrideField,
        });
        setBatchProgress({ done: i + 1, total: jobs.length });
      }
      return null;
    },
    onSuccess: (data) => {
      setBatchProgress(null);
      if (data) {
        navigate(`/live/${data.run_id}`);
      } else {
        navigate(`/workflows/${encodeURIComponent(name!)}`);
      }
    },
    onError: () => {
      setBatchProgress(null);
    },
  });

  const demoMutation = useMutation({
    mutationFn: () =>
      runWorkflow({
        workflow: name!,
        input_data: buildDemoInputData(),
        evaluation: undefined,
        execution_profile: { runtime: "subprocess" },
      }),
    onSuccess: (data) => navigate(`/live/${data.run_id}`),
  });

  const runLabel = runButtonLabel(
    batchProgress,
    runMutation.isPending,
    configRef.current.evaluation.enabled,
  );
  const runFailure =
    runMutation.isError || demoMutation.isError
      ? describeRunError(demoMutation.error ?? runMutation.error)
      : null;

  let runStatus: { label: string; text: string; dot: string };
  if (runMutation.isPending) {
    runStatus = {
      label: "running",
      text: "text-el-info",
      dot: "animate-pulse bg-el-info motion-reduce:animate-none",
    };
  } else if (apiDown) {
    runStatus = { label: "api offline", text: "text-el-danger", dot: "bg-el-danger" };
  } else {
    runStatus = { label: "ready", text: "text-el-success", dot: "bg-el-success" };
  }

  return (
    <div className="flex h-full flex-col">
      <BTopBar path={`workflows/${name ?? ""}`}>
        <button
          type="button"
          aria-label="Go back"
          onClick={() => navigate("/workflows")}
          className={BAR_GHOST_CLASS}
        >
          <ArrowLeft aria-hidden="true" className="h-3 w-3" />
          <span>[b] back</span>
        </button>
        {workflowBuilderEnabled && name && (
          <Link
            to={`/workflows/${encodeURIComponent(name)}/edit`}
            className={BAR_GHOST_CLASS}
          >
            <Pencil aria-hidden="true" className="h-3 w-3" />
            <span>[e] edit</span>
          </Link>
        )}
        {supportsDeterministicDemo && (
          <button
            type="button"
            onClick={() => { if (demoMutation.isPending) return; demoMutation.mutate(); }}
            disabled={demoMutation.isPending || apiDown}
            aria-describedby={apiDown ? apiDownReasonId : undefined}
            className={BAR_GHOST_CLASS}
          >
            <Play aria-hidden="true" className="h-3 w-3" />
            <span>{demoMutation.isPending ? "starting demo…" : "demo run"}</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => { if (runMutation.isPending) return; runMutation.mutate(); }}
          disabled={runMutation.isPending || apiDown}
          aria-describedby={apiDown ? apiDownReasonId : undefined}
          className={BAR_PRIMARY_CLASS}
          data-testid="run-button"
        >
          {runMutation.isPending ? (
            <Loader2
              aria-hidden="true"
              className="h-3 w-3 animate-spin motion-reduce:animate-none"
            />
          ) : (
            <Play aria-hidden="true" className="h-3 w-3" />
          )}
          <span>{runLabel}</span>
        </button>
      </BTopBar>

      {/* Body: [DAG center] [run config right]. Below md the two stack in
          one scrolling column — the graph keeps a real 360px canvas instead
          of collapsing to zero width beside a full-width config panel. */}
      <div className="flex flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">

        {/* ── Center: DAG ── */}
        <div className="flex h-[360px] min-w-0 flex-none flex-col overflow-hidden border-b border-el-divider md:h-auto md:flex-1 md:border-r md:border-b-0">
          {/* DAG header — serif workflow name, hairline meta, tier badges */}
          <div className="border-b border-el-divider bg-el-surface px-4 py-[10px]">
            <div className="flex items-center gap-3">
              <span className={PANEL_OVERLINE_CLASS}>■ DAG PREVIEW</span>
              {name && (
                <span className="truncate font-display text-[15px] font-semibold tracking-[-0.4px] text-el-ink">
                  {name}
                </span>
              )}
              {dag && hasWorkflowSteps && (
                <span className="font-mono text-micro tabular-nums text-el-muted">
                  {dag.nodes.length} nodes · {dag.edges.length} edges
                </span>
              )}
              {dag?.description && (
                <span className="ml-auto hidden max-w-xs truncate font-mono text-micro text-el-muted xl:block">
                  {dag.description}
                </span>
              )}
            </div>
            {tiers.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {tiers.map((tier) => (
                  <span
                    key={tier}
                    className={`rounded-sm border px-[5px] py-px font-mono text-micro uppercase tracking-[0.3px] ${tierClass(tier)}`}
                  >
                    {tier}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* DAG canvas fills remaining height */}
          {dagLoading && (
            <div className="flex flex-1 items-center justify-center font-mono text-micro text-el-muted">
              $ loading workflow graph
            </div>
          )}
          {!dagLoading && dagFailure && (
            // An unreachable API is already announced by the shell's offline
            // banner — a quiet note here, not a second alert.
            dagFailure.unreachable ? (
              <div className="flex flex-1 items-center justify-center font-mono text-micro text-el-muted">
                $ workflow graph unavailable while the API is unreachable
              </div>
            ) : (
              <div
                role="alert"
                className="flex flex-1 flex-col items-center justify-center gap-1 px-4 text-center font-mono text-micro text-el-danger"
              >
                <span className="flex items-start gap-1.5">
                  <CircleAlert
                    aria-hidden="true"
                    className="mt-0.5 size-3.5 flex-none"
                  />
                  <span>{dagFailure.summary}</span>
                </span>
                <span className="text-el-secondary">{dagFailure.remedy}</span>
              </div>
            )
          )}
          {!dagLoading && !dagError && dag && hasWorkflowSteps && (
            <div className="flex-1 overflow-hidden">
              <WorkflowDAG dagNodes={dag.nodes} dagEdges={dag.edges} />
            </div>
          )}
          {!dagLoading && !dagError && dag && !hasWorkflowSteps && (
            <div className="flex flex-1 items-center justify-center font-mono text-micro text-el-muted">
              $ no workflow steps defined
            </div>
          )}
          {!dagLoading && !dagError && !dag && (
            <div className="flex flex-1 items-center justify-center font-mono text-micro text-el-danger">
              $ failed to load dag
            </div>
          )}
        </div>

        {/* ── Right panel: Run config + Run history ── */}
        <div className="flex w-full flex-none flex-col bg-el-canvas md:w-[340px] md:overflow-y-auto">
          {/* $ RUN CONFIGURATION header — live status dot */}
          <div className="flex items-center justify-between border-b border-el-divider bg-el-surface px-4 py-2">
            <span className={PANEL_OVERLINE_CLASS}>$ RUN CONFIGURATION</span>
            <span
              className={`flex items-center gap-1.5 font-mono text-micro ${runStatus.text}`}
            >
              <span
                aria-hidden="true"
                className={`h-[5px] w-[5px] rounded-full ${runStatus.dot}`}
              />
              {runStatus.label}
            </span>
          </div>
          {apiDown && (
            <p
              id={apiDownReasonId}
              className="border-b border-el-divider bg-el-surface px-4 py-2 text-micro text-el-muted"
            >
              Runs are disabled: {apiDownReason}
            </p>
          )}

          <div className="flex-1">
            {dag && (
              <div className="p-3">
                <RunConfigForm
                  inputs={dag.inputs ?? []}
                  workflowName={name!}
                  initialEvaluation={initialEvaluation}
                  onChange={(values) => {
                    configRef.current = values;
                  }}
                />
              </div>
            )}
            {!dag && dagLoading && (
              <div className="p-4 font-mono text-micro text-el-muted">
                $ loading…
              </div>
            )}

            {/* Run history */}
            <div className="border-t border-el-divider">
              <div className="flex items-center gap-2 bg-el-surface px-4 py-2">
                <span className={PANEL_OVERLINE_CLASS}>▊ run history</span>
              </div>
              <div className="p-2">
                {runsFailure && !runs ? (
                  runsFailure.unreachable ? (
                    <p className="px-2 py-3 font-mono text-micro text-el-muted">
                      run history unavailable while the API is unreachable
                    </p>
                  ) : (
                    <InlineError
                      message={`failed to load run history: ${runsFailure.summary} ${runsFailure.remedy}`}
                      onRetry={() => void refetchRuns()}
                    />
                  )
                ) : (
                  <RunList runs={runs} isLoading={runsLoading} />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {runFailure && (
        <div
          role="alert"
          className="border-t border-el-danger bg-el-danger-soft px-4 py-2 font-mono text-micro text-el-danger"
        >
          <span className="flex items-start gap-1.5">
            <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 flex-none" />
            <span>{runFailure.summary}</span>
          </span>
          <span className="block pl-5 text-el-ink">{runFailure.remedy}</span>
        </div>
      )}
    </div>
  );
}
