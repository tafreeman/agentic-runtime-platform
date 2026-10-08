import { useEvaluationDatasets } from "../hooks/useWorkflows";
import BTopBar from "../components/layout/BTopBar";
import DatasetBrowser from "../components/datasets/DatasetBrowser";
import InlineError from "../components/states/InlineError";
import EmptyState from "../components/states/EmptyState";
import NoData from "../components/states/NoData";
import { describeApiError, formatApiError } from "../lib/apiErrors";


export default function DatasetsPage() {
  const { data: datasets, isLoading, error, refetch } = useEvaluationDatasets();

  // Counts are unknown (not zero) until the catalog has loaded.
  const repoCount = datasets?.repository.length;
  const localCount = datasets?.local.length;
  const evalSetCount = datasets?.eval_sets.length;
  const loadFailure = error ? describeApiError(error) : null;

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="datasets" />

      <div className="flex flex-1 min-h-0 flex-col gap-3 overflow-hidden p-4">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-[30px] leading-none tracking-[-0.5px] text-el-ink">
              Datasets
            </h1>
            <div className="mt-1.5 font-mono text-micro text-el-muted">
              {datasets ? (
                <>
                  $ {repoCount} repo · {localCount} local · {evalSetCount} eval
                  sets
                </>
              ) : (
                <>$ dataset catalog not loaded</>
              )}
            </div>
          </div>
          <div className="flex items-end gap-5">
            {(
              [
                ["repo", repoCount],
                ["local", localCount],
                ["eval sets", evalSetCount],
              ] as const
            ).map(([label, count]) => (
              <div key={label} className="flex flex-col items-end leading-none">
                <span className="font-display text-[22px] tracking-[-0.5px] tabular-nums text-el-ink">
                  {count ?? <NoData />}
                </span>
                <span className="mt-1 font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
                  {label}
                </span>
              </div>
            ))}
          </div>
        </div>

        {(() => {
          if (isLoading) {
            return (
              <div className="flex h-32 items-center justify-center font-mono text-micro text-el-muted">
                Loading datasets...
              </div>
            );
          }
          if (datasets) {
            // A failed refetch keeps the last good catalog on screen.
            return (
              <>
                {loadFailure && (
                  <p role="status" className="font-mono text-micro text-el-muted">
                    Showing the last loaded datasets — refresh failed:{" "}
                    {loadFailure.unreachable
                      ? "the API is unreachable."
                      : formatApiError(error)}
                  </p>
                )}
                <div className="flex-1 min-h-0 overflow-hidden">
                  <DatasetBrowser datasets={datasets} />
                </div>
              </>
            );
          }
          if (loadFailure) {
            // The shell's offline banner already announces an unreachable
            // API; keep this to a quiet note instead of a second alert.
            if (loadFailure.unreachable) {
              return (
                <p className="py-6 text-center font-mono text-micro text-el-muted">
                  Datasets can't load while the API is unreachable.
                </p>
              );
            }
            return (
              <InlineError
                message={`failed to load datasets: ${formatApiError(error)}`}
                onRetry={() => void refetch()}
              />
            );
          }
          return <EmptyState entity="datasets" />;
        })()}
      </div>
    </div>
  );
}
