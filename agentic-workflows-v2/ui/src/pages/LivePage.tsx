import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useWorkflowStream } from "../hooks/useWorkflowStream";
import { useRuns } from "../hooks/useRuns";
import { useWorkflowDAG } from "../hooks/useWorkflows";
import { useCli } from "../hooks/useCli";
import type { StepState } from "../hooks/useWorkflowStream";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import DagProgressList from "../components/live/DagProgressList";
import LogTail, { buildLogRows } from "../components/live/LogTail";
import ActiveStepCard from "../components/live/ActiveStepCard";
import LiveEvaluationCard from "../components/live/LiveEvaluationCard";
import LiveStepDetails from "../components/live/LiveStepDetails";
import TokenCounter from "../components/live/TokenCounter";
import LiveRunHeader from "../components/live/LiveRunHeader";
import BTopBar from "../components/layout/BTopBar";

/** Card chrome shared by the editorial live panels (theme-token radius/border). */
const CARD_STYLE = {
  borderRadius: "var(--b-rad-lg)",
  borderWidth: "var(--b-bw)",
} as const;

const HEADING_STYLE = { fontFamily: "var(--b-font-heading)" } as const;

const PANEL_LABEL_CLASS =
  "font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint";

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export default function LivePage() {
  const { runId } = useParams<{ runId: string }>();
  // "/live/latest" is a deep-link alias (sidebar, palette, g-e) — the stream
  // endpoint has no "latest" run id (the server accepts the socket and holds
  // it open forever), so resolve it to a real run before mounting the stream.
  if (runId === "latest") return <LatestRunGate />;
  return <LiveRunView runId={runId} />;
}

/**
 * Resolves the "/live/latest" alias: finds the newest running run from the
 * (polling) runs list and replaces the URL with its real id. While nothing is
 * active it renders an idle card instead of a stream that can never connect.
 */
function LatestRunGate() {
  const navigate = useNavigate();
  const { data: runs, isLoading } = useRuns();

  const activeRun = useMemo(
    () =>
      (runs ?? []).find(
        (r) => r.status === "running" || r.status === "in_progress"
      ),
    [runs]
  );

  useEffect(() => {
    if (!activeRun) return;
    const id = activeRun.run_id ?? activeRun.filename;
    navigate(`/live/${encodeURIComponent(id)}`, { replace: true });
  }, [activeRun, navigate]);

  const resolving = isLoading || Boolean(activeRun);

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="live/latest" />
      <div className="flex flex-1 items-center justify-center bg-b-bg0 p-[18px]">
        <div
          className="border-b-line bg-b-bg1 px-[28px] py-[24px] text-center"
          style={CARD_STYLE}
          data-testid="live-idle-card"
        >
          {resolving ? (
            <div className="font-mono text-[11px] text-b-text-dim">
              $ resolving latest run…
            </div>
          ) : (
            <>
              <div className="font-mono text-[11px] text-b-text-dim">
                $ no active run — trigger one from workflows
              </div>
              <Link
                to="/workflows"
                aria-label="Go to workflows"
                data-testid="live-idle-workflows-link"
                className="mt-3 inline-block font-mono text-[10.5px] text-b-clay hover:underline"
              >
                workflows →
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function LiveRunView({ runId }: Readonly<{ runId: string | undefined }>) {
  const navigate = useNavigate();
  const { setCli } = useCli();
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const { stepStates, events, workflowStatus, evaluation, error } = useWorkflowStream(
    runId ?? null
  );

  const workflowStartEvent = events.find((e) => e.type === "workflow_start");
  const inferredName = useMemo(() => {
    if (!runId) return undefined;
    const lastDash = runId.lastIndexOf("-");
    if (lastDash <= 0) return undefined;
    return runId.slice(0, lastDash);
  }, [runId]);
  const wfName =
    workflowStartEvent?.type === "workflow_start"
      ? workflowStartEvent.workflow_name
      : inferredName;
  const { data: dag, isLoading: dagLoading } = useWorkflowDAG(wfName);

  // CLI twin for the bottom strip: how this run's workflow is launched.
  useEffect(() => {
    if (wfName) setCli(`agentic run ${wfName}`);
  }, [wfName, setCli]);

  const edgeCounts = useMemo(() => {
    if (!dag) return new Map<string, number>();

    const counts = new Map<string, number>();
    const incoming = new Map<string, string[]>();
    for (const edge of dag.edges) {
      const key = `${edge.source}->${edge.target}`;
      incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
      counts.set(key, 0);
    }

    const completedSuccess = new Set<string>();
    for (const event of events) {
      if (
        (event.type === "step_end" || event.type === "step_complete") &&
        event.status === "success"
      ) {
        completedSuccess.add(event.step);
      }

      if (event.type === "step_start") {
        for (const source of incoming.get(event.step) ?? []) {
          if (!completedSuccess.has(source)) continue;
          const edgeId = `${source}->${event.step}`;
          counts.set(edgeId, (counts.get(edgeId) ?? 0) + 1);
        }
      }
    }

    return counts;
  }, [dag, events]);

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

  // Step progress counter
  const completedCount = useMemo(() => {
    let count = 0;
    if (stepStates) {
      for (const [, state] of stepStates) {
        if (state.status === "success" || state.status === "failed" || state.status === "skipped") count++;
      }
    }
    return count;
  }, [stepStates]);

  const totalSteps = dag?.nodes.length ?? 0;
  const progressPct =
    totalSteps > 0 ? Math.round((completedCount / totalSteps) * 100) : 0;

  const runningStep = useMemo(() => {
    if (!stepStates || stepStates.size === 0) return null;
    for (const [name, state] of stepStates) {
      if (state.status === "running") return name;
    }
    return null;
  }, [stepStates]);

  useEffect(() => {
    if (!runningStep) return;
    setSelectedStep((prev) => (prev === runningStep ? prev : runningStep));
  }, [runningStep]);

  const isActive =
    workflowStatus === "connecting" ||
    workflowStatus === "running" ||
    workflowStatus === "evaluating";

  // Wall-clock elapsed from the first step start; ticks while the run is live,
  // freezes once a terminal status arrives.
  const startTimeMs = useMemo(() => {
    let earliest: number | null = null;
    for (const [, state] of stepStates) {
      if (!state.startTime) continue;
      const t = new Date(state.startTime).getTime();
      if (!Number.isNaN(t) && (earliest === null || t < earliest)) earliest = t;
    }
    return earliest;
  }, [stepStates]);

  // "started {relative}" prefers the workflow_start event, falls back to the
  // earliest step start; both are real stream timestamps.
  const startedAtMs = useMemo(() => {
    if (workflowStartEvent && "timestamp" in workflowStartEvent && workflowStartEvent.timestamp) {
      const t = new Date(workflowStartEvent.timestamp).getTime();
      if (!Number.isNaN(t)) return t;
    }
    return startTimeMs;
  }, [workflowStartEvent, startTimeMs]);

  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!isActive || startedAtMs === null) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [isActive, startedAtMs]);

  const elapsedFmt =
    startTimeMs === null ? "0:00" : formatElapsed(nowMs - startTimeMs);

  // The step driving the ACTIVE STEP card: the selected one, else whatever runs.
  const focusName = selectedStep ?? runningStep;
  const focusStep: StepState | undefined = focusName
    ? stepStates.get(focusName)
    : undefined;

  let runTone: "ok" | "err" | "clay" = "clay";
  if (workflowStatus === "completed") {
    runTone = "ok";
  } else if (workflowStatus === "failed" || workflowStatus === "error") {
    runTone = "err";
  }

  // LOG TAIL rows + the purely client-side "pause tail" toggle. While paused,
  // the stream keeps buffering (events state keeps growing); the visible rows
  // are frozen at the pause point and "resume" re-attaches the tail.
  const logRows = useMemo(() => buildLogRows(events), [events]);
  const [pausedAtCount, setPausedAtCount] = useState<number | null>(null);
  const tailPaused = pausedAtCount !== null;
  const visibleLogRows = tailPaused ? logRows.slice(0, pausedAtCount) : logRows;
  const bufferedCount = tailPaused
    ? Math.max(0, logRows.length - pausedAtCount)
    : 0;

  return (
    <div className="flex h-full flex-col">
      <BTopBar path={`live/${runId ?? ""}`}>
        <button
          type="button"
          aria-label="Go back"
          onClick={() => navigate(-1)}
          className="btn-ghost"
        >
          <ArrowLeft aria-hidden="true" className="h-3 w-3" />
          <span>[esc] back</span>
        </button>
      </BTopBar>

      {workflowStatus === "evaluating" && (
        <div role="status" className="border-b border-b-blue bg-b-blue/10 px-4 py-1.5 font-mono text-[11px] text-b-blue">
          [~] evaluating workflow output…
        </div>
      )}
      {error && (
        <div role="alert" className="border-b border-b-red bg-b-red/10 px-4 py-2 font-mono text-[11px] text-b-red">
          [!] {error}
        </div>
      )}

      {/* Content — execution header strip + two-column DAG/log layout */}
      <div className="flex-1 overflow-y-auto bg-b-bg0 p-[18px]">
        <div className="flex flex-col gap-[14px]">
          <LiveRunHeader
            runId={runId}
            workflowName={wfName}
            workflowStatus={workflowStatus}
            statusTone={runTone}
            startedAtMs={startedAtMs}
            nowMs={nowMs}
            elapsedLabel={elapsedFmt}
            completedCount={completedCount}
            totalSteps={totalSteps}
            progressPct={progressPct}
            paused={tailPaused}
            bufferedCount={bufferedCount}
            onTogglePause={() =>
              setPausedAtCount(tailPaused ? null : logRows.length)
            }
          />

          <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1.62fr_1fr]">
            {/* Left column: DAG progress (graph + per-step rows) + stat tiles */}
            <div className="flex min-w-0 flex-col gap-[14px]">
              <div
                className="border-b-line bg-b-bg1 p-[16px_18px]"
                style={CARD_STYLE}
              >
                <div className={`mb-[10px] ${PANEL_LABEL_CLASS}`}>
                  dag progress
                </div>

                {/* Live DAG — ReactFlow stays the engine */}
                <div className="h-[300px] min-w-0">
                  {dag ? (
                    <WorkflowDAG
                      dagNodes={dag.nodes}
                      dagEdges={dag.edges}
                      stepStates={stepStates}
                      edgeCounts={edgeCounts}
                      kickbackEdges={kickbackEdges}
                      disconnected={workflowStatus === "error"}
                      onNodeClick={setSelectedStep}
                    />
                  ) : dagLoading && wfName ? (
                    <div className="flex h-full items-center justify-center">
                      <div className="h-32 w-full max-w-sm animate-pulse rounded-none bg-b-bg2" />
                    </div>
                  ) : (
                    <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
                      {workflowStatus === "connecting"
                        ? "$ connecting…"
                        : "$ waiting for dag…"}
                    </div>
                  )}
                </div>

                {/* Per-step progress rows: type tag · name · duration chip */}
                <div className="mt-[12px] border-t border-b-line-soft pt-[8px]">
                  <DagProgressList
                    nodes={dag?.nodes}
                    stepStates={stepStates}
                    selectedStep={selectedStep}
                    onSelectStep={setSelectedStep}
                  />
                </div>
              </div>

              {/* Stat tiles: TOKENS / STEPS */}
              <div className="grid grid-cols-2 gap-[12px]">
                <div
                  className="border-b-line bg-b-bg1 p-[15px_17px]"
                  style={CARD_STYLE}
                >
                  <div className="font-mono text-[9.5px] uppercase tracking-[1.2px] text-b-text-faint">
                    tokens
                  </div>
                  <div
                    className="mt-[8px] text-[30px] font-semibold tabular-nums text-b-clay"
                    style={{ ...HEADING_STYLE, letterSpacing: "-1px" }}
                  >
                    <TokenCounter events={events} variant="stat" />
                  </div>
                </div>
                <div
                  className="border-b-line bg-b-bg1 p-[15px_17px]"
                  style={CARD_STYLE}
                >
                  <div className="font-mono text-[9.5px] uppercase tracking-[1.2px] text-b-text-faint">
                    steps
                  </div>
                  <div
                    className="mt-[8px] text-[30px] font-semibold tabular-nums text-b-text"
                    style={{ ...HEADING_STYLE, letterSpacing: "-1px" }}
                  >
                    {completedCount}
                    <span className="text-[18px] text-b-text-dim">
                      /{totalSteps || 0}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Right column: log tail, active step, evaluation, drill-down */}
            <div className="flex min-w-0 flex-col gap-[14px]">
              <div
                className="flex min-h-[220px] flex-1 flex-col border-b-line bg-b-bg1 p-[14px_16px]"
                style={CARD_STYLE}
              >
                <LogTail
                  rows={visibleLogRows}
                  paused={tailPaused}
                  bufferedCount={bufferedCount}
                />
              </div>

              <ActiveStepCard focusName={focusName} step={focusStep} />

              {evaluation && (
                <LiveEvaluationCard
                  evaluation={evaluation}
                  onOpenScorecard={() => navigate("/evaluations")}
                />
              )}

              {/* Expandable per-step drill-down list, behind the active-step card */}
              <div
                className="border-b-line bg-b-bg1 p-[14px_16px]"
                style={CARD_STYLE}
              >
                <div className={`mb-[10px] ${PANEL_LABEL_CLASS}`}>
                  step details
                </div>
                <LiveStepDetails
                  stepStates={stepStates}
                  stepOrder={dag?.nodes.map((n) => n.id)}
                  selectedStep={selectedStep}
                  onSelectStep={setSelectedStep}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
