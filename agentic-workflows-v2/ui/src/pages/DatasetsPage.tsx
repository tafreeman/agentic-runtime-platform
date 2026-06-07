import { useEvaluationDatasets } from "../hooks/useWorkflows";
import BTopBar from "../components/layout/BTopBar";
import DatasetBrowser from "../components/datasets/DatasetBrowser";

export default function DatasetsPage() {
  const { data: datasets, isLoading, error } = useEvaluationDatasets();

  const repoCount = datasets?.repository.length ?? 0;
  const localCount = datasets?.local.length ?? 0;
  const evalSetCount = datasets?.eval_sets.length ?? 0;

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="datasets" />

      <div className="flex flex-1 min-h-0 flex-col gap-3 overflow-hidden p-4">
        <div>
          <h1
            className="text-[24px] font-semibold text-b-text"
            style={{ letterSpacing: "-0.5px" }}
          >
            Datasets
          </h1>
          <div className="mt-1 font-mono text-[11px] text-b-text-dim">
            $ {repoCount} repo · {localCount} local · {evalSetCount} eval sets
          </div>
        </div>

        {(() => {
          if (isLoading) {
            return (
              <div className="flex h-32 items-center justify-center font-mono text-[11px] text-b-text-dim">
                Loading datasets...
              </div>
            );
          }
          if (error) {
            return (
              <div className="rounded-sm border border-b-red bg-b-red/10 p-4 font-mono text-[11px] text-b-red">
                [!] failed to load datasets
              </div>
            );
          }
          if (datasets) {
            return (
              <div className="flex-1 min-h-0 overflow-hidden">
                <DatasetBrowser datasets={datasets} />
              </div>
            );
          }
          return (
            <div className="flex h-32 items-center justify-center font-mono text-[11px] text-b-text-dim">
              No datasets available.
            </div>
          );
        })()}
      </div>
    </div>
  );
}
