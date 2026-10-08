import { useId, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { compareRuns } from "../../api/client";
import type {
  EvalCandidateSummary,
  EvalComparisonResponse,
  RunSummary,
} from "../../api/types";
import BPill from "../common/BPill";
import StatusBadge from "../common/StatusBadge";
import NoData from "../states/NoData";
import { useApiAvailability } from "../../hooks/useApiAvailability";
import { describeApiError } from "../../lib/apiErrors";
import { gradeColorClass, gradeLetter, scoreToPercent } from "../../lib/grades";

/** How many recent runs each candidate picker offers. */
const PICKER_LIMIT = 8;

/** Null-safe fixed-point score for the delta table ("—" when absent). */
function formatScore(score: number | null): string {
  if (score == null || Number.isNaN(score)) return "—";
  return score.toFixed(1);
}

/** Sign-prefixed delta ("+1.5" / "-2.0"), "—" when absent. */
function formatDelta(delta: number | null): string {
  if (delta == null || Number.isNaN(delta)) return "—";
  return `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`;
}

/** Delta = A − B, so a positive delta means candidate A did better. */
function deltaColorClass(delta: number | null): string {
  if (delta == null || delta === 0) return "text-el-muted";
  return delta > 0 ? "text-el-success" : "text-el-danger";
}

/** Color for one side's score cell: green on the better side, red on worse. */
function sideColorClass(delta: number | null, side: "a" | "b"): string {
  if (delta == null || delta === 0) return "text-el-ink";
  const better = delta > 0 ? "a" : "b";
  return side === better ? "text-el-success" : "text-el-danger";
}


/** One candidate picker column (A or B) fed from the recent-runs list. */
function RunPickerColumn({
  slot,
  runs,
  selected,
  blockedFilename,
  onSelect,
}: Readonly<{
  slot: "A" | "B";
  runs: RunSummary[];
  selected: string | null;
  blockedFilename: string | null;
  onSelect: (filename: string | null) => void;
}>) {
  return (
    // min-w-0: a grid item defaults to its min-content width, so long run
    // filenames would push column B past the card edge instead of truncating.
    <div className="min-w-0">
      <span className="mb-1.5 block text-xs font-medium text-el-secondary">
        Candidate {slot}
      </span>
      <div className="flex max-h-32 flex-col gap-1.5 overflow-y-auto">
        {runs.length === 0 ? (
          <span className="text-xs text-el-muted">No runs yet</span>
        ) : (
          runs.map((r) => {
            const isSelected = selected === r.filename;
            // The same run cannot occupy both slots — a self-comparison is
            // always a tie, so the other slot's pick is blocked here.
            const isBlocked = r.filename === blockedFilename;
            return (
              <button
                key={r.filename}
                type="button"
                aria-pressed={isSelected}
                aria-label={`pick ${r.filename} for candidate ${slot}`}
                disabled={isBlocked}
                onClick={() => onSelect(isSelected ? null : r.filename)}
                className={`focus-ring flex min-h-9 items-center gap-2 rounded-md border px-2 py-1.5 font-mono text-micro transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                  isSelected
                    ? "border-el-accent-strong bg-el-accent-soft text-el-ink"
                    : "border-el-divider bg-el-subtle text-el-secondary hover:border-el-ink/40 hover:text-el-ink"
                }`}
              >
                <span className="min-w-0 flex-1 truncate text-left">
                  {r.filename}
                </span>
                <span className="max-w-[40%] flex-none truncate text-micro text-el-muted">
                  {r.workflow_name ?? "—"}
                </span>
                <StatusBadge status={r.status} className="flex-none" />
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

/** Header card for one scored candidate; the winner carries the accent rule. */
function CandidateCard({
  slot,
  candidate,
  isWinner,
}: Readonly<{
  slot: "a" | "b";
  candidate: EvalCandidateSummary;
  isWinner: boolean;
}>) {
  const pct = scoreToPercent(candidate.weighted_score);
  const letter = gradeLetter(candidate.grade, candidate.weighted_score);
  return (
    <div
      data-testid={`candidate-${slot}`}
      className={`rounded-md border bg-el-subtle p-3 ${
        isWinner ? "border-el-accent-strong" : "border-el-divider"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-el-secondary">
          Candidate {slot.toUpperCase()}
        </span>
        {isWinner && <BPill tone="clay">winner</BPill>}
      </div>
      <div className="mt-1.5 truncate font-display text-[13px] font-semibold text-el-ink">
        {candidate.workflow_name ?? "—"}
      </div>
      <div className="truncate font-mono text-micro text-el-muted">
        {candidate.run_id ?? candidate.filename}
      </div>
      <div className="mt-2 flex items-center gap-3">
        <span
          className={`font-display text-[20px] font-semibold leading-none ${gradeColorClass(letter)}`}
        >
          {letter ?? <NoData />}
        </span>
        <span className="font-mono text-micro text-el-ink tabular-nums">
          {pct == null ? <NoData /> : pct.toFixed(1)}
        </span>
        <StatusBadge status={candidate.passed ? "passed" : "failed"} />
      </div>
    </div>
  );
}

/** Comparison payload: candidate strip + per-criterion delta table. */
function ComparisonResult({
  result,
}: Readonly<{ result: EvalComparisonResponse }>) {
  const isTie = result.winner === "tie";
  return (
    <div data-testid="compare-result" className="mt-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-el-muted">
        <span>
          <span className="font-semibold text-el-ink">Result</span> · rubric{" "}
          <span className="font-mono">{result.rubric_id}</span>
        </span>
        <span className="flex items-center gap-2">
          Δ weighted{" "}
          <span
            className={`tabular-nums ${deltaColorClass(result.weighted_score_delta)}`}
          >
            {formatDelta(result.weighted_score_delta)}
          </span>
          {isTie && <BPill tone="dim">tie</BPill>}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2">
        <CandidateCard
          slot="a"
          candidate={result.candidate_a}
          isWinner={result.winner === "a"}
        />
        <CandidateCard
          slot="b"
          candidate={result.candidate_b}
          isWinner={result.winner === "b"}
        />
      </div>

      <div className="relative overflow-x-auto rounded-lg border border-el-divider bg-el-subtle">
        <table className="w-full font-mono text-micro">
          <thead>
            <tr className="border-b border-el-divider text-left font-sans text-micro font-semibold uppercase tracking-[0.5px] text-el-muted">
              <th className="px-3 py-2">Criterion</th>
              <th className="w-[80px] px-3 py-2 text-right">A</th>
              <th className="w-[80px] px-3 py-2 text-right">B</th>
              <th className="w-[80px] px-3 py-2 text-right">Δ (A−B)</th>
            </tr>
          </thead>
          <tbody>
            {result.criteria_deltas.map((d) => (
              <tr key={d.criterion} className="border-b border-el-divider-soft">
                <td className="truncate px-3 py-2 text-el-ink">
                  {d.criterion}
                </td>
                <td
                  className={`px-3 py-2 text-right tabular-nums ${sideColorClass(d.delta, "a")}`}
                >
                  {formatScore(d.score_a)}
                </td>
                <td
                  className={`px-3 py-2 text-right tabular-nums ${sideColorClass(d.delta, "b")}`}
                >
                  {formatScore(d.score_b)}
                </td>
                <td
                  data-testid={`delta-${d.criterion}`}
                  className={`px-3 py-2 text-right tabular-nums ${deltaColorClass(d.delta)}`}
                >
                  {formatDelta(d.delta)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * "Compare runs" band for the Evaluations page: pick two completed runs,
 * score both head-to-head under one rubric (POST /api/eval/compare), and
 * render the winner strip plus a per-criterion delta table.
 */
export default function RunComparePanel({
  runs,
}: Readonly<{ runs: RunSummary[] }>) {
  const [runA, setRunA] = useState<string | null>(null);
  const [runB, setRunB] = useState<string | null>(null);
  const [rubricId, setRubricId] = useState("");
  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const apiDownReasonId = useId();

  const compareMutation = useMutation({ mutationFn: compareRuns });

  // Recent runs, grouped by workflow so same-workflow candidates sit together
  // (cross-workflow comparisons are allowed but rarely meaningful). sort() is
  // stable, so recency order from the API is preserved within each group.
  const pickerRuns = useMemo(
    () =>
      runs
        .slice(0, PICKER_LIMIT)
        .toSorted((x, y) =>
          (x.workflow_name ?? "~").localeCompare(y.workflow_name ?? "~"),
        ),
    [runs],
  );

  const canCompare =
    runA != null && runB != null && !compareMutation.isPending && !apiDown;
  const compareFailure = compareMutation.isError
    ? describeApiError(compareMutation.error)
    : null;

  const handleCompare = () => {
    if (!runA || !runB) return;
    compareMutation.mutate({
      run_a: runA,
      run_b: runB,
      rubric_id: rubricId.trim() || null,
    });
  };

  return (
    <section
      className="relative overflow-hidden rounded-lg border border-el-divider bg-el-surface px-5 py-[18px]"
      aria-label="compare runs"
    >
      <div className="mb-3.5">
        <h2 className="m-0 font-sans text-[15px] font-semibold text-el-ink">Compare runs</h2>
        <p className="mt-0.5 text-xs text-el-muted">
          Scores two recorded runs head-to-head under one rubric.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1.2fr)_minmax(0,1fr)]">
        <RunPickerColumn
          slot="A"
          runs={pickerRuns}
          selected={runA}
          blockedFilename={runB}
          onSelect={setRunA}
        />
        <RunPickerColumn
          slot="B"
          runs={pickerRuns}
          selected={runB}
          blockedFilename={runA}
          onSelect={setRunB}
        />

        <div>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-el-secondary">
              Rubric ID <span className="font-normal text-el-muted">(optional)</span>
            </span>
            <input
              value={rubricId}
              onChange={(event) => setRubricId(event.target.value)}
              placeholder="Default rubric"
              className="focus-ring w-full rounded-md border border-el-control-border bg-el-canvas px-2 py-1.5 font-mono text-micro text-el-ink placeholder:text-el-muted focus:border-el-focus"
            />
          </label>
          <button
            type="button"
            disabled={!canCompare}
            onClick={handleCompare}
            aria-describedby={apiDown ? apiDownReasonId : undefined}
            className="focus-ring mt-3 flex min-h-9 w-full items-center justify-center rounded-md bg-el-action px-2 py-2 text-xs font-semibold text-el-action-ink transition-colors hover:bg-el-action/90 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {compareMutation.isPending ? "Comparing…" : "Compare runs"}
          </button>
          {apiDown && (
            <p id={apiDownReasonId} className="mt-2 text-micro text-el-muted">
              {apiDownReason}
            </p>
          )}
          {compareMutation.isPending && (
            <div className="mt-2 text-micro text-el-muted">
              Scoring both runs under one rubric…
            </div>
          )}
          {compareFailure && (
            <div role="alert" className="mt-2 text-micro text-el-danger">
              <span className="block">Comparison failed: {compareFailure.summary}</span>
              <span className="block text-el-secondary">
                {compareFailure.remedy}
              </span>
            </div>
          )}
        </div>
      </div>

      {compareMutation.data && <ComparisonResult result={compareMutation.data} />}
    </section>
  );
}
