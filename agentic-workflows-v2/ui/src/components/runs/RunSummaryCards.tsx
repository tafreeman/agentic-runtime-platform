import type { ReactNode } from "react";
import type { RunsSummary } from "../../api/types";
import DurationDisplay from "../common/DurationDisplay";

interface RunSummaryCardsProps {
  summary: RunsSummary | undefined;
  isLoading: boolean;
}

function MetricCard({
  label,
  value,
  helper,
  accent,
}: {
  label: string;
  value: ReactNode;
  helper?: string;
  accent?: string;
}) {
  return (
    <div
      style={{
        borderRadius: "var(--b-rad-lg)",
        borderWidth: "var(--b-bw)",
      }}
      className="relative overflow-hidden border border-solid border-b-line bg-b-bg1 p-[18px]"
    >
      <div className="font-mono text-[9px] uppercase tracking-[1.2px] text-b-text-faint">
        {label}
      </div>
      <div
        className="mt-2 text-[34px] font-semibold leading-[0.9] tabular-nums text-b-text"
        style={{
          fontFamily: "var(--b-font-heading)",
          letterSpacing: "-1px",
          color: accent,
        }}
      >
        {value}
      </div>
      {helper ? (
        <div className="mt-2 truncate font-mono text-[10px] text-b-text-dim">
          {helper}
        </div>
      ) : null}
    </div>
  );
}

export default function RunSummaryCards({
  summary,
  isLoading,
}: RunSummaryCardsProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            style={{
              borderRadius: "var(--b-rad-lg)",
              borderWidth: "var(--b-bw)",
            }}
            className="h-[96px] animate-pulse border border-solid border-b-line bg-b-bg1"
          />
        ))}
      </div>
    );
  }

  const totalRuns = summary?.total_runs ?? 0;
  const workflows = summary?.workflows ?? [];
  const failed = summary?.failed ?? 0;
  const successRate =
    totalRuns > 0
      ? `${Math.min(100, Math.round(((summary?.success ?? 0) / totalRuns) * 100))}%`
      : "--";

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricCard
        label="Total Runs"
        value={totalRuns.toLocaleString()}
        helper={`${workflows.length} workflow${workflows.length === 1 ? "" : "s"}`}
      />
      <MetricCard
        label="Success"
        value={(summary?.success ?? 0).toLocaleString()}
        helper={successRate}
        accent="rgb(var(--b-green))"
      />
      <MetricCard
        label="Failed"
        value={failed.toLocaleString()}
        helper="needs review"
        accent={failed > 0 ? "rgb(var(--b-red))" : undefined}
      />
      <MetricCard
        label="Avg Duration"
        value={<DurationDisplay ms={summary?.avg_duration_ms} />}
        helper={undefined}
      />
    </div>
  );
}
