import { useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { Play, ArrowLeft, Loader2, Pencil } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useWorkflowDAG } from "../hooks/useWorkflows";
import { useRuns } from "../hooks/useRuns";
import { runWorkflow } from "../api/client";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import RunList from "../components/runs/RunList";
import RunConfigForm, {
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

export default function WorkflowDetailPage() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const workflowBuilderEnabled = isWorkflowBuilderEnabled();
  const {
    data: dag,
    isLoading: dagLoading,
    isError: dagError,
    error: dagQueryError,
  } = useWorkflowDAG(name);
  const { data: runs, isLoading: runsLoading } = useRuns(name);
  const dagErrorMessage =
    dagQueryError instanceof Error ? dagQueryError.message : "failed to load dag";
  const hasWorkflowSteps = (dag?.nodes.length ?? 0) > 0;
  const supportsDeterministicDemo =
    name === "test_deterministic" ||
    (!!dag &&
      dag.nodes.length > 0 &&
      dag.nodes.every((node) => node.tier?.toLowerCase().startsWith("tier0")));

  const configRef = useRef<RunConfigValues>({
    inputValues: {},
    executionProfile: { runtime: "subprocess" },
    rubricId: "",
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
      if (inp.type === "object" || inp.type === "array") {
        try {
          data[inp.name] = JSON.parse(val);
        } catch {
          data[inp.name] = val;
        }
      } else {
        data[inp.name] = val;
      }
    }
    return data;
  };

  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null);

  const runMutation = useMutation({
    mutationFn: async () => {
      const { executionProfile, rubricId, evaluation } = configRef.current;

      const buildEvalRequest = (sampleIndex: number) => {
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
      };

      const samples = evaluation.enabled && evaluation.selectedSamples.length > 0
        ? evaluation.selectedSamples
        : [0];
      const runsPerRecord = evaluation.enabled ? (evaluation.runsPerRecord ?? 1) : 1;
      const isBatch = samples.length > 1 || runsPerRecord > 1;

      const jobs: Array<{ sampleIndex: number }> = [];
      for (const s of samples) {
        for (let r = 0; r < runsPerRecord; r++) {
          jobs.push({ sampleIndex: s });
        }
      }

      if (!isBatch) {
        return runWorkflow({
          workflow: name!,
          input_data: buildInputData(),
          evaluation: buildEvalRequest(jobs[0] ? jobs[0].sampleIndex : 0),
          execution_profile: executionProfile,
        });
      }

      setBatchProgress({ done: 0, total: jobs.length });
      for (let i = 0; i < jobs.length; i++) {
        await runWorkflow({
          workflow: name!,
          input_data: buildInputData(),
          evaluation: buildEvalRequest(jobs[i]?.sampleIndex ?? 0),
          execution_profile: executionProfile,
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

  const runLabel = batchProgress
    ? `${batchProgress.done}/${batchProgress.total}`
    : runMutation.isPending
      ? "[…] starting"
      : configRef.current.evaluation.enabled
        ? "[▶] run + eval"
        : "[▶] run";

  return (
    <div className="flex h-full flex-col">
      <BTopBar path={`workflows/${name ?? ""}`}>
        <button
          type="button"
          onClick={() => navigate("/workflows")}
          className="btn-ghost"
        >
          <ArrowLeft className="h-3 w-3" />
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
            onClick={() => runMutation.mutate()}
            disabled={runMutation.isPending}
            className="btn-ghost"
          >
            <Play className="h-3 w-3" />
            <span>demo run</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => runMutation.mutate()}
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
        <div className="flex flex-1 flex-col overflow-hidden border-r border-b-line">
          {/* Slim DAG header */}
          <div className="flex items-center gap-3 border-b border-b-line bg-b-bg1 px-4 py-2">
            <span className="font-mono text-[10px] font-bold text-b-clay uppercase tracking-wider">
              ■ DAG PREVIEW
            </span>
            {dag && hasWorkflowSteps && (
              <span className="font-mono text-[10px] text-b-text-faint">
                {dag.nodes.length} nodes · {dag.edges.length} edges
              </span>
            )}
            {dag?.description && (
              <span className="hidden xl:block ml-auto font-mono text-[10px] text-b-text-dim truncate max-w-xs">
                {dag.description}
              </span>
            )}
          </div>

          {/* DAG canvas fills remaining height */}
          {dagLoading ? (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-text-dim">
              $ loading workflow graph
            </div>
          ) : dagError ? (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-red">
              [!] {dagErrorMessage}
            </div>
          ) : dag && hasWorkflowSteps ? (
            <div className="flex-1 overflow-hidden">
              <WorkflowDAG dagNodes={dag.nodes} dagEdges={dag.edges} />
            </div>
          ) : dag ? (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-text-dim">
              $ no workflow steps defined
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-red">
              $ failed to load dag
            </div>
          )}
        </div>

        {/* ── Right panel: Run config + Run history ── */}
        <div className="w-[340px] flex flex-col overflow-y-auto bg-b-bg0">
          {/* $ RUN CONFIGURATION header */}
          <div className="flex items-center justify-between border-b border-b-line bg-b-bg1 px-4 py-2">
            <span className="font-mono text-[10px] font-bold text-b-clay uppercase tracking-wider">
              $ RUN CONFIGURATION
            </span>
            <span className="font-mono text-[10px] text-b-green">
              {runMutation.isPending ? "running" : "ready"}
            </span>
          </div>

          <div className="flex-1">
            {dag ? (
              <div className="p-3">
                <RunConfigForm
                  inputs={dag.inputs ?? []}
                  workflowName={name!}
                  onChange={(values) => {
                    configRef.current = values;
                  }}
                />
              </div>
            ) : dagLoading ? (
              <div className="p-4 font-mono text-[11px] text-b-text-dim">
                $ loading…
              </div>
            ) : null}

            {/* Run history */}
            <div className="border-t border-b-line">
              <div className="flex items-center gap-2 bg-b-bg1 px-4 py-2">
                <span className="font-mono text-[10px] font-bold text-b-clay uppercase tracking-wider">
                  ▊ run history
                </span>
              </div>
              <div className="p-2">
                <RunList runs={runs} isLoading={runsLoading} />
              </div>
            </div>
          </div>
        </div>
      </div>

      {runMutation.isError && (
        <div className="border-t border-b-red bg-b-red/10 px-4 py-2 font-mono text-[11px] text-b-red">
          [!] {(runMutation.error as Error).message}
        </div>
      )}
    </div>
  );
}
