import type { ReactNode } from "react";
import type { RunsSummary } from "../../api/types";
import BBox from "../common/BBox";
import DurationDisplay from "../common/DurationDisplay";

interface RunSummaryCardsProps {
  summary: RunsSummary | undefined;
  isLoading: boolean;
}

function MetricCard({
  label,
  value,
  helper,
}: {
  label: string;
  value: ReactNode;
  helper?: string;
}) {
  return (
    <BBox>
      <div className="p-3">
        <div className="font-mono text-[10px] uppercase tracking-[0.8px] text-b-text-dim">
          {label}
        </div>
        <div
          className="mt-1 text-[24px] font-semibold tabular-nums text-b-text"
          style={{ fontFamily: "var(--b-font-heading)" }}
        >
          {value}
        </div>
        {helper ? (
          <div className="mt-1 truncate font-mono text-[10px] text-b-text-faint">
            {helper}
          </div>
        ) : null}
      </div>
    </BBox>
  );
}

export default function RunSummaryCards({
  summary,
  isLoading,
}: RunSummaryCardsProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            className="h-[88px] animate-pulse rounded-sm border border-b-line bg-b-bg1"
          />
        ))}
      </div>
    );
  }

  const totalRuns = summary?.total_runs ?? 0;
  const workflows = summary?.workflows ?? [];
  const successRate =
    totalRuns > 0 ? `${(((summary?.success ?? 0) / totalRuns) * 100).toFixed(0)}%` : "--";

  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      <MetricCard
        label="Total Runs"
        value={totalRuns.toLocaleString()}
        helper={`${workflows.length} workflow${workflows.length === 1 ? "" : "s"}`}
      />
      <MetricCard
        label="Success"
        value={(summary?.success ?? 0).toLocaleString()}
        helper={successRate}
      />
      <MetricCard
        label="Failed"
        value={(summary?.failed ?? 0).toLocaleString()}
        helper="needs review"
      />
      <MetricCard
        label="Avg Duration"
        value={<DurationDisplay ms={summary?.avg_duration_ms} />}
        helper={undefined}
      />
    </div>
  );
}
