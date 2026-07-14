import { useMemo, useRef, useState } from "react";
import { Link, useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Play, ArrowLeft, Loader2, Pencil } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useWorkflowDAG } from "../hooks/useWorkflows";
import { useRuns } from "../hooks/useRuns";
import { runWorkflow } from "../api/client";
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
 * Resolve a theme-aware accent color for a tier hint. Mirrors the tier-badge
 * coloring used by the DAG step nodes so the language stays consistent.
 */
function tierColor(tier: string): string {
  const t = tier.toLowerCase();
  if (t.startsWith("tier0")) return "rgb(var(--b-text-dim))";
  if (t.startsWith("tier1")) return "rgb(var(--b-blue))";
  if (t.startsWith("tier2")) return "rgb(var(--b-purple))";
  return "rgb(var(--b-clay))";
}

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
  const { data: runs, isLoading: runsLoading, isError: runsError, refetch: refetchRuns } = useRuns(name);
  const dagErrorMessage =
    dagQueryError instanceof Error ? dagQueryError.message : "failed to load dag";
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

  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null);

  const runMutation = useMutation({
    mutationFn: async () => {
      const { executionProfile, rubricId, evaluation, modelOverride } =
        configRef.current;
      // Dataset-backed evaluation fills inputs from the dataset sample
      // server-side, so only enforce form inputs for plain runs.
      const probeEval = buildEvalRequest(evaluation, rubricId, 0);
      const datasetBacked =
        probeEval != null && probeEval.dataset_source !== "none";
      if (!datasetBacked) {
        const missing = missingRequiredInputs();
        if (missing.length > 0) {
          throw new Error(
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

  const runLabel = runButtonLabel(
    batchProgress,
    runMutation.isPending,
    configRef.current.evaluation.enabled,
  );

  return (
    <div className="flex h-full flex-col">
      <BTopBar path={`workflows/${name ?? ""}`}>
        <button
          type="button"
          aria-label="Go back"
          onClick={() => navigate("/workflows")}
          className="btn-ghost"
        >
          <ArrowLeft aria-hidden="true" className="h-3 w-3" />
          <span>[b] back</span>
        </button>
        {workflowBuilderEnabled && name && (
          <Link
            to={`/workflows/${encodeURIComponent(name)}/edit`}
            className="btn-ghost"
          >
            <Pencil className="h-3 w-3" />
            <span>[e] edit</span>
          </Link>
        )}
        {supportsDeterministicDemo && (
          <button
            type="button"
            onClick={() => { if (runMutation.isPending) return; runMutation.mutate(); }}
            disabled={runMutation.isPending}
            className="btn-ghost"
          >
            <Play className="h-3 w-3" />
            <span>demo run</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => { if (runMutation.isPending) return; runMutation.mutate(); }}
          disabled={runMutation.isPending}
          className="btn-primary"
          data-testid="run-button"
        >
          {runMutation.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Play className="h-3 w-3" />
          )}
          <span>{runLabel}</span>
        </button>
      </BTopBar>

      {/* Three-panel body: [DAG center] [run config right] */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── Center: DAG ── */}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden border-r border-b-line">
          {/* DAG header — serif workflow name, hairline meta, tier badges */}
          <div className="border-b border-b-line bg-b-bg1 px-4 py-[10px]">
            <div className="flex items-center gap-3">
              <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-b-clay">
                ■ DAG PREVIEW
              </span>
              {name && (
                <span
                  className="truncate text-b-text"
                  style={{
                    fontFamily: "var(--b-font-heading)",
                    fontSize: "15px",
                    fontWeight: 600,
                    letterSpacing: "-0.4px",
                  }}
                >
                  {name}
                </span>
              )}
              {dag && hasWorkflowSteps && (
                <span className="font-mono text-[10px] tabular-nums text-b-text-faint">
                  {dag.nodes.length} nodes · {dag.edges.length} edges
                </span>
              )}
              {dag?.description && (
                <span className="ml-auto hidden max-w-xs truncate font-mono text-[10px] text-b-text-dim xl:block">
                  {dag.description}
                </span>
              )}
            </div>
            {tiers.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {tiers.map((tier) => {
                  const color = tierColor(tier);
                  return (
                    <span
                      key={tier}
                      className="font-mono text-[8.5px] uppercase tracking-[0.3px]"
                      style={{
                        color,
                        border: `1px solid ${color}`,
                        borderRadius: "var(--b-rad-sm)",
                        padding: "1px 5px",
                      }}
                    >
                      {tier}
                    </span>
                  );
                })}
              </div>
            )}
          </div>

          {/* DAG canvas fills remaining height */}
          {dagLoading && (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-text-dim">
              $ loading workflow graph
            </div>
          )}
          {!dagLoading && dagError && (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-red">
              [!] {dagErrorMessage}
            </div>
          )}
          {!dagLoading && !dagError && dag && hasWorkflowSteps && (
            <div className="flex-1 overflow-hidden">
              <WorkflowDAG dagNodes={dag.nodes} dagEdges={dag.edges} />
            </div>
          )}
          {!dagLoading && !dagError && dag && !hasWorkflowSteps && (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-text-dim">
              $ no workflow steps defined
            </div>
          )}
          {!dagLoading && !dagError && !dag && (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-red">
              $ failed to load dag
            </div>
          )}
        </div>

        {/* ── Right panel: Run config + Run history ── */}
        <div className="flex w-full flex-col overflow-y-auto bg-b-bg0 md:w-[340px]">
          {/* $ RUN CONFIGURATION header — live status dot */}
          <div className="flex items-center justify-between border-b border-b-line bg-b-bg1 px-4 py-2">
            <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-b-clay">
              $ RUN CONFIGURATION
            </span>
            <span
              className={`flex items-center gap-1.5 font-mono text-[10px] ${
                runMutation.isPending ? "text-b-clay" : "text-b-green"
              }`}
            >
              <span
                aria-hidden="true"
                className={`h-[5px] w-[5px] rounded-full ${
                  runMutation.isPending
                    ? "animate-b-pulse bg-b-clay"
                    : "bg-b-green"
                }`}
              />
              {runMutation.isPending ? "running" : "ready"}
            </span>
          </div>

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
              <div className="p-4 font-mono text-[11px] text-b-text-dim">
                $ loading…
              </div>
            )}

            {/* Run history */}
            <div className="border-t border-b-line">
              <div className="flex items-center gap-2 bg-b-bg1 px-4 py-2">
                <span className="font-mono text-[10px] font-bold text-b-clay uppercase tracking-wider">
                  ▊ run history
                </span>
              </div>
              <div className="p-2">
                {runsError ? (
                  <InlineError
                    message="failed to load run history"
                    onRetry={() => void refetchRuns()}
                  />
                ) : (
                  <RunList runs={runs} isLoading={runsLoading} />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {runMutation.isError && (
        <div
          className="border-t border-b-red bg-b-red/10 px-4 py-2 font-mono text-[11px] text-b-red"
          style={{ borderTopWidth: "var(--b-bw)" }}
        >
          [!] {runMutation.error.message}
        </div>
      )}
    </div>
  );
}
