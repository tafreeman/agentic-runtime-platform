import { type ReactNode, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { evaluateRun } from "../../api/client";
import type { RunSummary } from "../../api/types";

/** How many recent runs the setup picker offers for (re-)scoring. */
const PICKER_LIMIT = 6;

/** Static option labels for the eval-setup pill groups (presentational only). */
const SELECT_PILLS = {
  methodology: ["multidimensional", "pairwise", "reference-free"],
  depth: ["per-step", "aggregate", "spot-check"],
  judges: ["opus", "sonnet", "haiku"],
} as const;

/**
 * Design-styled selectable option pill (chosen vs faint). Visual only — the
 * eval-setup band has no real selection wiring, so these carry no handler.
 */
function SelectPill({
  label,
  chosen,
}: Readonly<{ label: string; chosen: boolean }>) {
  return (
    <span
      className={`inline-flex items-center border px-2 py-1.5 font-mono text-[11px] ${
        chosen
          ? "border-b-clay/50 bg-b-bg2 text-b-text"
          : "border-b-line bg-b-bg1 text-b-text-faint"
      }`}
      style={{ borderRadius: "var(--b-rad-sm)" }}
    >
      {label}
    </span>
  );
}

/** Relative "Nh" label for the run picker. */
function relativeWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "—";
  const diff = Date.now() - time;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

/** Tracking label above one setup group (RUN / METHODOLOGY / …). */
function GroupLabel({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <span className="mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
      {children}
    </span>
  );
}

/**
 * "SETUP · EVALUATE A RUN" left rail for the Evaluations page: pick a recent
 * run and replay its captured log through the judge (POST
 * /api/runs/{filename}/evaluate). Any recent run can be (re-)scored — not just
 * runs that already carry a score.
 */
export default function EvalSetupPanel({
  runs,
}: Readonly<{ runs: RunSummary[] }>) {
  const [selectedRunFilename, setSelectedRunFilename] = useState<string | null>(
    null,
  );
  const queryClient = useQueryClient();

  const recentRuns = useMemo(() => runs.slice(0, PICKER_LIMIT), [runs]);

  const evalMutation = useMutation({
    mutationFn: (filename: string) => evaluateRun(filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["run-evaluation"] });
    },
  });

  return (
    <section
      className="relative overflow-hidden border bg-b-bg1 px-5 py-[18px]"
      style={{
        borderColor: "rgb(var(--b-clay))",
        borderWidth: "var(--b-bw)",
        borderRadius: "var(--b-rad-lg)",
      }}
      aria-label="evaluation setup"
      data-testid="eval-setup"
    >
      <div
        className="absolute inset-x-0 top-0 h-[3px] bg-b-clay"
        aria-hidden="true"
      />
      <div className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-clay">
        SETUP · EVALUATE A RUN
      </div>
      <div className="mb-3.5 mt-1 font-mono text-[10px] text-b-text-dim">
        replays a captured run log through a judge
      </div>

      <div className="flex flex-col gap-[18px]">
        <div>
          <GroupLabel>RUN</GroupLabel>
          <div className="flex max-h-40 flex-col gap-1.5 overflow-y-auto">
            {recentRuns.length === 0 ? (
              <span className="font-mono text-[10px] text-b-text-dim">
                no runs yet
              </span>
            ) : (
              recentRuns.map((r) => {
                const isSelected = selectedRunFilename === r.filename;
                return (
                  <button
                    key={r.filename}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() =>
                      setSelectedRunFilename(isSelected ? null : r.filename)
                    }
                    className={`flex items-center gap-2 border px-2 py-1.5 font-mono text-[11px] transition-colors hover:text-b-text ${
                      isSelected
                        ? "border-b-clay bg-b-bg2 text-b-text"
                        : "border-b-line bg-b-bg2 text-b-text-mid hover:border-b-clay/50"
                    }`}
                    style={{ borderRadius: "var(--b-rad-sm)" }}
                  >
                    <span className="flex-none text-[9px] text-b-text-dim">
                      #{(r.run_id ?? r.filename).slice(0, 6)}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-left">
                      {r.workflow_name ?? "—"}
                    </span>
                    <span className="flex-none text-[9px] text-b-text-dim">
                      {relativeWhen(r.start_time)}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </div>

        <div>
          <GroupLabel>METHODOLOGY</GroupLabel>
          {/* DESIGN-GAP: design shows these as interactive selectable pills
              (evaluations 407-412). The page has no eval-setup wiring, so
              they are styled chosen-vs-faint but are presentational only —
              no selection handler exists to drive a real choice. */}
          <div className="flex flex-wrap gap-1.5">
            {SELECT_PILLS.methodology.map((label, i) => (
              <SelectPill key={label} label={label} chosen={i === 0} />
            ))}
          </div>
        </div>

        <div>
          <GroupLabel>DEPTH</GroupLabel>
          {/* DESIGN-GAP: presentational-only selectable pills (see above). */}
          <div className="flex flex-wrap gap-1.5">
            {SELECT_PILLS.depth.map((label, i) => (
              <SelectPill key={label} label={label} chosen={i === 0} />
            ))}
          </div>
        </div>

        <div>
          <GroupLabel>
            JUDGE MODELS <span className="text-b-text-faint">· ensemble</span>
          </GroupLabel>
          {/* DESIGN-GAP: presentational-only selectable pills (see above). */}
          <div className="flex flex-wrap gap-1.5">
            {SELECT_PILLS.judges.map((j, i) => (
              <SelectPill key={j} label={j} chosen={i === 0} />
            ))}
          </div>
          <button
            type="button"
            disabled={!selectedRunFilename || evalMutation.isPending}
            onClick={() =>
              selectedRunFilename && evalMutation.mutate(selectedRunFilename)
            }
            className="mt-3 flex w-full items-center justify-center bg-b-clay px-2 py-2 font-mono text-[11px] font-semibold text-b-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            style={{ borderRadius: "var(--b-rad-sm)" }}
          >
            {evalMutation.isPending ? "scoring…" : "▶ evaluate a run"}
          </button>
          {evalMutation.isSuccess && (
            <div className="mt-2 font-mono text-[10px] text-b-green">
              {evalMutation.data?.evaluation
                ? `scored ${evalMutation.data.evaluation.weighted_score.toFixed(1)} · ${evalMutation.data.evaluation.grade}`
                : "scored — refresh to see details"}
            </div>
          )}
          {evalMutation.isError && (
            <div
              role="alert"
              className="mt-2 font-mono text-[10px] text-b-red"
            >
              evaluation failed
              {evalMutation.error instanceof Error
                ? `: ${evalMutation.error.message}`
                : ""}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
