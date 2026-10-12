import { useEvaluationDatasets } from "../hooks/useWorkflows";
import BTopBar from "../components/layout/BTopBar";
import DatasetBrowser from "../components/datasets/DatasetBrowser";
import InlineError from "../components/states/InlineError";
import EmptyState from "../components/states/EmptyState";
import Scoreline from "../components/common/Scoreline";
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

      <div className="flex flex-1 min-h-0 flex-col gap-6 overflow-y-auto p-4 sm:p-6 lg:p-10">
        <header>
          <h1 className="font-display text-[30px] leading-tight tracking-tight text-el-ink sm:text-[40px]">Datasets</h1>
          <p className="mt-2 max-w-prose text-sm text-el-muted">Inspect dataset samples and configure a workflow with their evidence.</p>
        </header>
        <Scoreline label="Dataset catalog" items={[
          { label: "Repository", value: repoCount ?? <NoData /> },
          { label: "Local", value: localCount ?? <NoData /> },
          { label: "Evaluation sets", value: evalSetCount ?? <NoData /> },
        ]} />

        {(() => {
          if (isLoading) {
            return (
              <div className="flex h-32 items-center justify-center text-sm text-el-muted">
                Loading datasets...
              </div>
            );
          }
          if (datasets) {
            // A failed refetch keeps the last good catalog on screen.
            return (
              <>
                {loadFailure && (
                  <p role="status" className="text-sm text-el-muted">
                    Showing the last loaded datasets — refresh failed:{" "}
                    {loadFailure.unreachable
                      ? "the API is unreachable."
                      : formatApiError(error)}
                  </p>
                )}
                <div className="flex-1 min-h-80">
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
                <p className="py-6 text-center text-sm text-el-muted">
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
