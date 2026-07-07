import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { compareRuns } from "../../api/client";
import type {
  EvalCandidateSummary,
  EvalComparisonResponse,
  RunSummary,
} from "../../api/types";
import BPill from "../common/BPill";
import { gradeColorClass, gradeLetter, scoreToPercent } from "../../lib/grades";

/** Card chrome shared with the Evaluations page bands: theme radius + border. */
const CARD_STYLE = {
  borderWidth: "var(--b-bw)",
  borderRadius: "var(--b-rad-lg)",
} as const;

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
  if (delta == null || delta === 0) return "text-b-text-dim";
  return delta > 0 ? "text-b-green" : "text-b-red";
}

/** Color for one side's score cell: green on the better side, red on worse. */
function sideColorClass(delta: number | null, side: "a" | "b"): string {
  if (delta == null || delta === 0) return "text-b-text";
  const better = delta > 0 ? "a" : "b";
  return side === better ? "text-b-green" : "text-b-red";
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
    <div>
      <span className="mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
        CANDIDATE {slot}
      </span>
      <div className="flex max-h-32 flex-col gap-1.5 overflow-y-auto">
        {runs.length === 0 ? (
          <span className="font-mono text-[10px] text-b-text-dim">
            no runs yet
          </span>
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
                className={`flex items-center gap-2 border px-2 py-1.5 font-mono text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                  isSelected
                    ? "border-b-clay bg-b-bg2 text-b-text"
                    : "border-b-line bg-b-bg2 text-b-text-mid hover:border-b-clay/50 hover:text-b-text"
                }`}
                style={{ borderRadius: "var(--b-rad-sm)" }}
              >
                <span className="min-w-0 flex-1 truncate text-left">
                  {r.filename}
                </span>
                <span className="max-w-[40%] flex-none truncate text-[9px] text-b-text-dim">
                  {r.workflow_name ?? "—"}
                </span>
                <span className="flex-none text-[9px] text-b-text-dim">
                  {r.status ?? "—"}
                </span>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

/** Header card for one scored candidate; the winner carries the clay accent. */
function CandidateCard({
  slot,
  candidate,
  isWinner,
}: Readonly<{
  slot: "a" | "b";
  candidate: EvalCandidateSummary;
  isWinner: boolean;
}>) {
  const pct = scoreToPercent(candidate.weighted_score) ?? 0;
  const letter = gradeLetter(candidate.grade, candidate.weighted_score);
  return (
    <div
      data-testid={`candidate-${slot}`}
      className={`border bg-b-bg2 p-3 ${
        isWinner ? "border-b-clay" : "border-b-line"
      }`}
      style={{ borderRadius: "var(--b-rad-sm)", borderWidth: "var(--b-bw)" }}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
          CANDIDATE {slot.toUpperCase()}
        </span>
        {isWinner && <BPill tone="clay">winner</BPill>}
      </div>
      <div
        className="mt-1.5 truncate text-[13px] font-semibold text-b-text"
        style={{ fontFamily: "var(--b-font-heading)" }}
      >
        {candidate.workflow_name ?? "—"}
      </div>
      <div className="truncate font-mono text-[10px] text-b-text-dim">
        {candidate.run_id ?? candidate.filename}
      </div>
      <div className="mt-2 flex items-center gap-3">
        <span
          className={`text-[20px] font-semibold leading-none ${gradeColorClass(letter)}`}
          style={{ fontFamily: "var(--b-font-heading)" }}
        >
          {letter ?? "—"}
        </span>
        <span className="font-mono text-[11px] text-b-text tabular-nums">
          {pct.toFixed(1)}
        </span>
        <BPill tone={candidate.passed ? "ok" : "err"}>
          {candidate.passed ? "pass" : "fail"}
        </BPill>
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
      <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
        <span>RESULT · rubric {result.rubric_id}</span>
        <span className="flex items-center gap-2">
          Δ WEIGHTED{" "}
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

      <div
        className="overflow-x-auto border border-b-line bg-b-bg2"
        style={CARD_STYLE}
      >
        <table className="w-full font-mono text-[11px]">
          <thead>
            <tr className="border-b border-b-line text-left text-[10px] uppercase tracking-[0.5px] text-b-text-faint">
              <th className="px-3 py-2">CRITERION</th>
              <th className="w-[80px] px-3 py-2 text-right">A</th>
              <th className="w-[80px] px-3 py-2 text-right">B</th>
              <th className="w-[80px] px-3 py-2 text-right">Δ (A−B)</th>
            </tr>
          </thead>
          <tbody>
            {result.criteria_deltas.map((d) => (
              <tr key={d.criterion} className="border-b border-b-line-soft">
                <td className="truncate px-3 py-2 text-b-text">
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

  const canCompare = runA != null && runB != null && !compareMutation.isPending;

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
      className="relative overflow-hidden border bg-b-bg1 px-5 py-[18px]"
      style={{
        borderColor: "rgb(var(--b-clay))",
        borderWidth: "var(--b-bw)",
        borderRadius: "var(--b-rad-lg)",
      }}
      aria-label="compare runs"
    >
      <div
        className="absolute inset-x-0 top-0 h-[3px] bg-b-clay"
        aria-hidden="true"
      />
      <div className="mb-3.5 font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-clay">
        COMPARE RUNS · scores two runs head-to-head under one rubric
      </div>

      <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-[1.2fr_1.2fr_1fr]">
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
            <span className="mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
              RUBRIC ID <span className="text-b-text-faint">· optional</span>
            </span>
            <input
              value={rubricId}
              onChange={(event) => setRubricId(event.target.value)}
              placeholder="default rubric"
              style={{ borderRadius: "var(--b-rad-sm)" }}
              className="w-full border border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text placeholder:text-b-text-faint focus:border-b-clay focus:outline-none"
            />
          </label>
          <button
            type="button"
            disabled={!canCompare}
            onClick={handleCompare}
            className="mt-3 flex w-full items-center justify-center bg-b-clay px-2 py-2 font-mono text-[11px] font-semibold text-b-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            style={{ borderRadius: "var(--b-rad-sm)" }}
          >
            {compareMutation.isPending ? "comparing…" : "▶ compare"}
          </button>
          {compareMutation.isPending && (
            <div className="mt-2 font-mono text-[10px] text-b-text-dim">
              scoring both runs under one rubric…
            </div>
          )}
          {compareMutation.isError && (
            <div role="alert" className="mt-2 font-mono text-[10px] text-b-red">
              comparison failed
              {compareMutation.error instanceof Error
                ? `: ${compareMutation.error.message}`
                : ""}
            </div>
          )}
        </div>
      </div>

      {compareMutation.data && <ComparisonResult result={compareMutation.data} />}
    </section>
  );
}
