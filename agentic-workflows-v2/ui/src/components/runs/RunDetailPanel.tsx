import { useId, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Play, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRunDetail } from "../../hooks/useRuns";
import { useWorkflowDAG } from "../../hooks/useWorkflows";
import { useCli } from "../../hooks/useCli";
import { useApiAvailability } from "../../hooks/useApiAvailability";
import { getWorkflowEditor, runWorkflow } from "../../api/client";
import type { StepStatus } from "../../api/types";
import WorkflowDAG from "../dag/WorkflowDAG";
import RunDetailSteps from "./RunDetail";
import DurationDisplay from "../common/DurationDisplay";
import CopyId from "../common/CopyId";
import StatusBadge from "../common/StatusBadge";
import TierMark from "../common/TierMark";
import BAsciiBar from "../common/BAsciiBar";
import EvaluationRubricAccordion from "../evaluations/EvaluationRubricAccordion";
import InlineError from "../states/InlineError";
import NoData from "../states/NoData";
import { Button } from "../ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../ui/alert-dialog";

type EvalTone = "pass" | "review" | "fail";

/**
 * Evaluation scorecard colors by tone. `bar` is BAsciiBar's semantic color
 * prop (el-success / el-warning / el-danger).
 */
const EVAL_TONE: Record<
  EvalTone,
  { text: string; bar: "success" | "warning" | "danger" }
> = {
  pass: { text: "text-el-success", bar: "success" },
  review: { text: "text-el-warning", bar: "warning" },
  fail: { text: "text-el-danger", bar: "danger" },
};

/**
 * Hairline detail section: a sentence-case sans title over its content. One
 * box per section (no card nested in a card).
 */
function DetailCard({
  title,
  children,
}: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <section className="overflow-hidden rounded-lg border border-el-divider bg-el-surface">
      <h2 className="m-0 border-b border-el-divider px-3 py-2 font-sans text-xs font-semibold text-el-ink">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Choose the evaluation tone from a normalized 0..1 score. */
function evalToneFor(evalPct: number | null): EvalTone {
  if (evalPct !== null && evalPct > 0.75) return "pass";
  if (evalPct !== null && evalPct > 0.5) return "review";
  return "fail";
}

export interface RunDetailPanelProps {
  /** The run's storage filename (used to fetch detail + evaluation data). */
  filename: string;
  /**
   * When provided, renders a close [x] button in the header and calls this on
   * click — used by the RunsPage master–detail inspector. Omitted on the
   * standalone deep-link page, where BTopBar's back button covers "close".
   */
  onClose?: () => void;
  /**
   * "aside" (default) keeps the single scrollable column that fits the
   * ~520px master–detail inspector; "page" spreads the same cards across a
   * two-column grid (DAG left, evaluation + steps right) on the standalone
   * `/runs/:filename` route, restoring the pre-redesign full-page layout.
   */
  layout?: "aside" | "page";
}

/**
 * Full run detail — status header, workflow DAG, step list, and evaluation
 * scorecard. Reused by both the standalone `/runs/:filename` route
 * (RunDetailPage) and the RunsPage master–detail inspector aside, so the
 * layout is a single scrollable column (no fixed side-by-side split) to stay
 * legible at the aside's ~520px width as well as full page width.
 */
export default function RunDetailPanel({
  filename,
  onClose,
  layout = "aside",
}: Readonly<RunDetailPanelProps>) {
  const { data: run, isLoading, isError, error, refetch } =
    useRunDetail(filename);
  const {
    data: dag,
    isLoading: dagLoading,
    isError: dagError,
    error: dagErrorValue,
  } = useWorkflowDAG(run?.workflow_name);
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"spans" | "yaml">("spans");
  const navigate = useNavigate();
  const { setCli } = useCli();
  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const replayReasonId = useId();

  // "Replay with same inputs" — starts a NEW run of the same workflow with
  // the inputs captured in this run's log, then jumps to the live view.
  const replay = useMutation({
    mutationFn: () =>
      runWorkflow({
        workflow: run?.workflow_name ?? "",
        input_data: (run?.inputs ?? {}) as Record<string, unknown>,
      }),
    onSuccess: (resp) => navigate(`/live/${encodeURIComponent(resp.run_id)}`),
  });

  // Workflow YAML for the panel's second tab; fetched lazily on first open.
  const yamlQuery = useQuery({
    queryKey: ["workflow-editor", run?.workflow_name],
    queryFn: () => getWorkflowEditor(run?.workflow_name ?? ""),
    enabled: activeTab === "yaml" && Boolean(run?.workflow_name),
  });

  const runSteps = run?.steps ?? [];

  // Build step states from completed run data
  const stepStates = useMemo(
    () =>
      new Map(
        runSteps.map((s) => [
          s.step_name,
          {
            // status on the wire is `string`; cast to the known enum union.
            status: s.status as StepStatus,
            // duration_ms can be null for incomplete steps; coerce to undefined.
            durationMs: s.duration_ms ?? undefined,
            modelUsed: s.model_used ?? undefined,
            tokensUsed: s.tokens_used ?? undefined,
            modelInferred: s.metadata?.model_inferred === true,
          },
        ])
      ),
    [runSteps]
  );

  const edgeCounts = useMemo(() => {
    if (!dag) return new Map<string, number>();

    const counts = new Map<string, number>();
    for (const edge of dag.edges) {
      const source = runSteps.find((s) => s.step_name === edge.source);
      const target = runSteps.find((s) => s.step_name === edge.target);
      if (!source || !target) continue;
      if (source.status !== "success") continue;
      if (target.status === "pending") continue;

      counts.set(`${edge.source}->${edge.target}`, 1);
    }
    return counts;
  }, [dag, runSteps]);

  const kickbackEdges = useMemo(() => {
    if (!dag) return new Set<string>();
    const isReviewOrTest = (name: string) => /(review|test)/i.test(name);
    const isDevRework = (name: string) => /(rework|developer|generate|fix)/i.test(name);

    return new Set(
      dag.edges
        .filter((edge) => isReviewOrTest(edge.source) && isDevRework(edge.target))
        .map((edge) => `${edge.source}->${edge.target}`)
    );
  }, [dag]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-el-muted">
        Loading run…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex h-full items-center justify-center px-4 py-8">
        <InlineError
          className="w-full max-w-md"
          message="Couldn't load this run."
          error={error}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-el-muted">
        Run not found
      </div>
    );
  }

  // A success rate over zero recorded steps (or a missing/NaN rate) has no
  // underlying data — show "—", not a fabricated "0%".
  const hasSuccessRate =
    typeof run.success_rate === "number" &&
    Number.isFinite(run.success_rate) &&
    (run.step_count ?? 0) > 0;
  const successPercent = hasSuccessRate
    ? run.success_rate <= 1
      ? run.success_rate * 100
      : run.success_rate
    : null;

  // Replay is only offered when it can actually succeed: older run logs
  // captured no `inputs`, and replaying those against a workflow with
  // required inputs fails server-side validation after the fact (the run
  // dies on the live page with "Missing required input"). The DAG response
  // already carries the declared input schema, so block the doomed case up
  // front. When the DAG hasn't loaded (or failed), stay enabled — the
  // server still validates and the live view surfaces any failure.
  const capturedInputs = (run.inputs ?? {}) as Record<string, unknown>;
  const missingRequiredInputs = (dag?.inputs ?? [])
    .filter(
      (input) =>
        input.required &&
        input.default == null &&
        !(input.name in capturedInputs)
    )
    .map((input) => input.name);
  const replayBlocked = missingRequiredInputs.length > 0;
  const replayBlockedReason = replayBlocked
    ? `run log has no captured value for required input${
        missingRequiredInputs.length > 1 ? "s" : ""
      }: ${missingRequiredInputs.join(", ")}`
    : undefined;
  const replayTitle =
    replayBlockedReason ?? "Start a new run with this run's captured inputs";
  // Visible reason whenever replay is unavailable (API down beats a missing
  // input: it is the thing to fix first). Wired via aria-describedby.
  const replayDisabledReason = apiDown
    ? apiDownReason
    : replayBlockedReason
      ? `Replay unavailable: ${replayBlockedReason}.`
      : undefined;

  const evalData = run.extra?.evaluation;
  const routing = run.extra?.routing;
  const evalPct =
    evalData?.weighted_score === undefined
      ? null
      : Math.max(0, Math.min(1, evalData.weighted_score / 100));

  const evalTone = EVAL_TONE[evalToneFor(evalPct)];

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header band (§11.4): identity, then state + key metrics on their own
          wrapping line, so the name never collapses in a narrow inspector;
          the close control stays top-right. */}
      <div className="flex items-start gap-3 border-b border-el-divider bg-el-surface px-4 py-3">
        <div className="min-w-0 flex-1">
          <h1
            className="truncate font-display text-[18px] font-semibold text-el-ink"
            style={{ letterSpacing: "-0.3px" }}
          >
            {run.workflow_name}
          </h1>
          <div className="mt-0.5">
            <CopyId
              text={run.run_id}
              // ::after grows the 16px id line to a 32px hit area, mostly
              // downward into the band's padding (not over the title).
              className="relative text-micro after:absolute after:inset-x-0 after:-top-1 after:-bottom-3"
            />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-micro text-el-secondary">
            <StatusBadge status={run.status} />
            <span className="tabular-nums">
              <span className="text-el-muted">Duration </span>
              {run.total_duration_ms == null ? (
                <NoData />
              ) : (
                <DurationDisplay ms={run.total_duration_ms} />
              )}
            </span>
            <span className="tabular-nums">
              <span className="text-el-muted">Steps </span>
              {run.step_count ?? <NoData />}
              {run.failed_step_count ? (
                <span className="text-el-danger">
                  /{run.failed_step_count}
                  <span className="sr-only"> failed</span>
                </span>
              ) : null}
            </span>
            <span className="tabular-nums">
              <span className="text-el-muted">Step success </span>
              {successPercent === null ? (
                <NoData />
              ) : (
                <span
                  className={
                    successPercent > 85 ? "text-el-success" : "text-el-warning"
                  }
                >
                  {successPercent.toFixed(0)}%
                </span>
              )}
            </span>
          </div>
        </div>
        {onClose && (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={onClose}
            aria-label="Close inspector"
            title="Close (Esc)"
            className="h-9 w-9 flex-none"
          >
            <X aria-hidden="true" />
          </Button>
        )}
      </div>

      {/* Action bar — replay + spans/yaml tabs, per the design kit inspector */}
      <div className="border-b border-el-divider bg-el-canvas px-4 py-2">
        <div className="flex items-center gap-2">
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={
                  apiDown || replay.isPending || !run.workflow_name || replayBlocked
                }
                title={replayTitle}
                aria-describedby={replayDisabledReason ? replayReasonId : undefined}
                className="h-9"
              >
                <Play aria-hidden="true" />
                {replay.isPending ? "Replaying…" : "Replay with same inputs"}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Start a new run?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will execute {run.workflow_name} again using the captured
                  inputs from {run.run_id}. Provider calls and usage may occur.
                  The existing run remains unchanged.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => {
                    // CLI equivalent: the same workflow with the captured
                    // inputs saved to a JSON file (`agentic run --input`).
                    setCli(`agentic run ${run.workflow_name} --input <inputs.json>`);
                    replay.mutate();
                  }}
                >
                  Start replay
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <div className="ml-auto flex items-center gap-1" role="tablist">
            {(["spans", "yaml"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                aria-selected={activeTab === tab}
                onClick={() => setActiveTab(tab)}
                className={`focus-ring-inset min-h-9 border-b-2 px-3 text-xs transition-colors ${
                  activeTab === tab
                    ? "border-el-accent text-el-ink"
                    : "border-transparent text-el-muted hover:text-el-ink"
                }`}
              >
                {tab === "spans" ? "Spans" : "YAML"}
              </button>
            ))}
          </div>
        </div>
        {replayDisabledReason ? (
          <p id={replayReasonId} className="mt-1 text-micro text-el-muted">
            {replayDisabledReason}
          </p>
        ) : null}
        {replay.isError && (
          <InlineError
            className="mt-2"
            message="Replay failed; this run is unchanged."
            error={replay.error}
          />
        )}
      </div>

      {activeTab === "yaml" ? (
        <div className="flex-1 overflow-y-auto p-3">
          <DetailCard title={`${run.workflow_name}.yaml`}>
            {yamlQuery.isLoading ? (
              <div className="p-4 text-xs text-el-muted">
                Loading workflow YAML…
              </div>
            ) : yamlQuery.isError ? (
              <div className="p-4">
                <InlineError
                  message="Couldn't load the workflow YAML."
                  error={yamlQuery.error}
                  onRetry={() => void yamlQuery.refetch()}
                />
              </div>
            ) : yamlQuery.data?.source ? (
              <pre className="overflow-x-auto whitespace-pre p-4 font-mono text-micro leading-relaxed text-el-secondary">
                {yamlQuery.data.source}
              </pre>
            ) : (
              <div className="p-4 text-xs text-el-muted">
                Workflow YAML unavailable
              </div>
            )}
          </DetailCard>
        </div>
      ) : (
      /* Spans tab — DAG, evaluation, and step detail. "aside" keeps a single
         scrollable column that fits the ~520px inspector; "page" spreads the
         cards across two columns like the pre-redesign full-page route.
         auto-rows-max: below xl the cards stack in one column, and with
         `auto` rows the overflow-hidden DAG card (min-content 0) collapsed to
         its 2px border once the column outgrew the scroll box. items-start
         keeps the DAG card from stretching to the tall right column at xl. */
      <div
        data-testid={`run-detail-${layout}-layout`}
        className={
          layout === "page"
            ? "grid min-h-0 flex-1 auto-rows-max grid-cols-1 content-start items-start gap-3 overflow-y-auto p-3 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]"
            : "flex-1 space-y-3 overflow-y-auto p-3"
        }
      >
        <DetailCard title="Workflow DAG">
          <div className={layout === "page" ? "h-[520px]" : "h-[320px]"}>
            {dag ? (
              <WorkflowDAG
                dagNodes={dag.nodes}
                dagEdges={dag.edges}
                stepStates={stepStates}
                edgeCounts={edgeCounts}
                kickbackEdges={kickbackEdges}
                onNodeClick={setSelectedStep}
              />
            ) : dagLoading ? (
              <div className="flex h-full items-center justify-center text-xs text-el-muted">
                Loading graph…
              </div>
            ) : dagError ? (
              <div className="flex h-full items-center justify-center p-4">
                <InlineError
                  className="w-full"
                  message="Couldn't load the workflow DAG."
                  error={dagErrorValue}
                />
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-el-muted">
                Graph unavailable
              </div>
            )}
          </div>
        </DetailCard>

        <div className={layout === "page" ? "space-y-3" : "contents"}>
        {routing && (
          <DetailCard title="Routing provenance">
            <div className="space-y-4 p-4 text-xs">
              <dl className="grid gap-x-5 gap-y-2 sm:grid-cols-2">
                <div>
                  <dt className="text-el-muted">Policy source</dt>
                  <dd className="mt-0.5 font-semibold text-el-ink">{routing.source}</dd>
                </div>
                <div>
                  <dt className="text-el-muted">Selected pack</dt>
                  <dd className="mt-0.5 font-mono text-el-secondary">
                    {routing.pack
                      ? `${routing.pack.id}@${routing.pack.version}`
                      : "built-in routing"}
                  </dd>
                </div>
                {routing.requested_model_override && (
                  <div className="sm:col-span-2">
                    <dt className="text-el-muted">Direct override</dt>
                    <dd className="mt-0.5 font-mono text-el-secondary">{routing.requested_model_override}</dd>
                  </div>
                )}
              </dl>
              {routing.resolved_steps.length > 0 && (
                <div className="relative overflow-x-auto border-t border-el-divider-soft pt-3">
                  <table className="w-full text-left">
                    <thead className="text-micro font-semibold uppercase tracking-[0.8px] text-el-muted">
                      <tr><th className="pb-2 pr-4">Step</th><th className="pb-2 pr-4">Tier</th><th className="pb-2 pr-4">Provider</th><th className="pb-2">Resolved model</th></tr>
                    </thead>
                    <tbody className="font-mono text-micro text-el-secondary">
                      {routing.resolved_steps.map((step, index) => (
                        <tr key={`${step.step}-${index}`} className="border-t border-el-divider-soft">
                          <td className="py-2 pr-4">{step.step}</td>
                          <td className="py-2 pr-4">
                            {step.tier == null ? "—" : <TierMark tier={step.tier} />}
                          </td>
                          <td className="py-2 pr-4">{step.provider ?? "—"}</td>
                          <td className="py-2">{step.model ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </DetailCard>
        )}
        {evalData && evalPct !== null && (
          <section className="rounded-lg border border-el-divider bg-el-surface p-[18px]">
            <div className="flex items-center justify-between gap-2">
              <h2 className="m-0 font-sans text-xs font-semibold text-el-ink">Evaluation</h2>
              <StatusBadge status={evalData.passed ? "passed" : "failed"} />
            </div>
            <div className="mt-3 flex items-end gap-3.5">
              <div className="flex flex-col items-center">
                <div
                  className={`font-display text-[42px] font-semibold leading-[0.9] ${evalTone.text}`}
                >
                  {evalData.grade}
                </div>
                <div className="mt-1 text-micro text-el-muted">Grade</div>
              </div>
              <div className="pb-1 text-micro text-el-secondary">
                Weighted score{" "}
                <span className="font-semibold tabular-nums text-el-ink">
                  {evalData.weighted_score.toFixed(1)}
                </span>{" "}
                / 100
              </div>
            </div>
            <div className="mt-3">
              <BAsciiBar value={evalPct} color={evalTone.bar} />
            </div>
          </section>
        )}

        {evalData && (
          <DetailCard title="Score detail">
            <div className="p-3">
              <EvaluationRubricAccordion filename={filename} />
            </div>
          </DetailCard>
        )}

        <DetailCard title={`Steps · ${run.steps.length}`}>
          <div className="p-2">
            <RunDetailSteps
              steps={run.steps}
              selectedStep={selectedStep}
              onSelectStep={setSelectedStep}
            />
          </div>
        </DetailCard>
        </div>
      </div>
      )}
    </div>
  );
}
