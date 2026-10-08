import type { ReactNode } from "react";
import type { RunsSummary } from "../../api/types";
import DurationDisplay from "../common/DurationDisplay";
import NoData from "../states/NoData";

interface RunSummaryCardsProps {
  summary: RunsSummary | undefined;
  isLoading: boolean;
}

function MetricCard({
  label,
  value,
  helper,
  valueClassName = "text-el-ink",
}: {
  label: string;
  value: ReactNode;
  helper?: ReactNode;
  /** Text color class for the value (status tone), default ink. */
  valueClassName?: string;
}) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-el-divider bg-el-surface p-[18px]">
      <div className="font-mono text-micro uppercase tracking-[1.2px] text-el-muted">
        {label}
      </div>
      <div
        className={`mt-2 font-display text-[34px] font-semibold leading-[0.9] tabular-nums ${valueClassName}`}
        style={{ letterSpacing: "-1px" }}
      >
        {value}
      </div>
      {helper ? (
        <div className="mt-2 truncate font-mono text-micro text-el-muted">
          {helper}
        </div>
      ) : null}
    </div>
  );
}

/** A count from the summary, or "—" when the summary didn't supply one. */
function countOrNoData(value: number | undefined): ReactNode {
  return typeof value === "number" ? value.toLocaleString() : <NoData />;
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
            className="h-24 animate-pulse rounded-lg border border-el-divider bg-el-surface"
          />
        ))}
      </div>
    );
  }

  // No summary (failed or not fetched) → every value is "—", never a fake 0.
  const totalRuns = summary?.total_runs;
  const workflows = summary?.workflows;
  const failed = summary?.failed;
  const success = summary?.success;
  // A rate over zero runs has no underlying data.
  const successRate =
    typeof totalRuns === "number" && totalRuns > 0 && typeof success === "number"
      ? `${Math.min(100, Math.round((success / totalRuns) * 100))}%`
      : <NoData />;
  const avgMs = totalRuns === 0 ? null : summary?.avg_duration_ms;

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricCard
        label="Total Runs"
        value={countOrNoData(totalRuns)}
        helper={
          workflows
            ? `${workflows.length} workflow${workflows.length === 1 ? "" : "s"}`
            : undefined
        }
      />
      <MetricCard
        label="Success"
        value={countOrNoData(success)}
        helper={successRate}
        valueClassName={typeof success === "number" ? "text-el-success" : "text-el-ink"}
      />
      <MetricCard
        label="Failed"
        value={countOrNoData(failed)}
        helper={typeof failed === "number" && failed > 0 ? "needs review" : undefined}
        valueClassName={
          typeof failed === "number" && failed > 0 ? "text-el-danger" : "text-el-ink"
        }
      />
      <MetricCard
        label="Avg Duration"
        value={avgMs == null ? <NoData /> : <DurationDisplay ms={avgMs} />}
        helper={undefined}
      />
    </div>
  );
}
