import { useState } from "react";
import type { ReactNode } from "react";
import type {
  EvaluationDatasetOption,
  EvaluationDatasetsResponse,
} from "../../api/types";
import SampleIndexGrid from "./SampleIndexGrid";
import DatasetDetailPane from "./DatasetDetailPane";

interface DatasetBrowserProps {
  datasets: EvaluationDatasetsResponse;
}

type SelectedSource = "repository" | "local" | null;

function SectionLabel({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="border-b border-el-divider-soft bg-el-subtle px-3 py-1.5 font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
      {children}
    </div>
  );
}

interface DatasetRowProps {
  dataset: EvaluationDatasetOption;
  active: boolean;
  onSelect: () => void;
}

function DatasetRow({ dataset, active, onSelect }: Readonly<DatasetRowProps>) {
  return (
    <button
      type="button"
      aria-label={`Select dataset ${dataset.name}`}
      data-testid={`dataset-row-${dataset.id}`}
      aria-pressed={active}
      onClick={onSelect}
      className={`focus-ring-inset relative grid min-h-9 w-full grid-cols-[1fr_auto] items-center gap-2 border-b border-el-divider-soft px-3 py-2 text-left transition-colors hover:bg-el-hover ${
        active ? "bg-el-subtle" : ""
      }`}
    >
      {active && (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-[2px] bg-el-accent"
        />
      )}
      <span className="min-w-0">
        <span className="block truncate font-mono text-micro text-el-ink">
          {dataset.name}
        </span>
        <span className="block truncate font-mono text-micro text-el-muted">
          {dataset.id}
        </span>
      </span>
      {dataset.sample_count != null && (
        <span className="flex flex-col items-end leading-none">
          <span className="font-display text-[14px] tracking-[-0.5px] tabular-nums text-el-secondary">
            {dataset.sample_count}
          </span>
          <span className="mt-0.5 font-mono text-micro uppercase tracking-[1px] text-el-muted">
            samples
          </span>
        </span>
      )}
    </button>
  );
}

export default function DatasetBrowser({ datasets }: Readonly<DatasetBrowserProps>) {
  const [selectedSource, setSelectedSource] = useState<SelectedSource>(null);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [selectedSampleIndex, setSelectedSampleIndex] = useState<number | null>(null);

  function selectDataset(source: SelectedSource, id: string) {
    setSelectedSource(source);
    setSelectedDatasetId(id);
    setSelectedSampleIndex(null);
  }

  return (
    <div className="flex h-full overflow-hidden rounded-lg border border-el-divider bg-el-surface">
      {/* Left pane — dataset list */}
      <div
        className="w-1/4 min-w-[160px] overflow-y-auto border-r border-el-divider"
      >
        {datasets.repository.length > 0 && (
          <div>
            <SectionLabel>repository · {datasets.repository.length}</SectionLabel>
            {datasets.repository.map((ds) => (
              <DatasetRow
                key={ds.id}
                dataset={ds}
                active={
                  selectedSource === "repository" && selectedDatasetId === ds.id
                }
                onSelect={() => selectDataset("repository", ds.id)}
              />
            ))}
          </div>
        )}

        {datasets.local.length > 0 && (
          <div>
            <SectionLabel>local · {datasets.local.length}</SectionLabel>
            {datasets.local.map((ds) => (
              <DatasetRow
                key={ds.id}
                dataset={ds}
                active={selectedSource === "local" && selectedDatasetId === ds.id}
                onSelect={() => selectDataset("local", ds.id)}
              />
            ))}
          </div>
        )}

        {datasets.eval_sets.length > 0 && (
          <div>
            <SectionLabel>eval sets · {datasets.eval_sets.length}</SectionLabel>
            {datasets.eval_sets.map((es) => (
              <div key={es.id} className="border-b border-el-divider-soft px-3 py-2">
                <div className="truncate font-mono text-micro text-el-ink">
                  {es.name}
                </div>
                <div className="font-mono text-micro text-el-muted">
                  {es.datasets.length} linked datasets
                </div>
                {es.datasets.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {es.datasets.map((d) => (
                      <span
                        key={d}
                        className="inline-flex items-center rounded-sm bg-el-hover px-1.5 py-px font-mono text-micro text-el-secondary"
                      >
                        {d}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {datasets.repository.length === 0 &&
          datasets.local.length === 0 &&
          datasets.eval_sets.length === 0 && (
            <div className="px-3 py-4 font-mono text-micro text-el-muted">
              $ no datasets found — add a dataset, then reload this page
            </div>
          )}
      </div>

      {/* Middle pane — sample index */}
      <div className="w-1/3 overflow-hidden border-r border-el-divider">
        {selectedSource && selectedDatasetId ? (
          <SampleIndexGrid
            datasetSource={selectedSource}
            datasetId={selectedDatasetId}
            selectedIndex={selectedSampleIndex}
            onSelect={setSelectedSampleIndex}
          />
        ) : (
          <div className="flex h-full items-center justify-center font-mono text-micro text-el-muted">
            $ select a dataset
          </div>
        )}
      </div>

      {/* Right pane — sample detail */}
      <div className="flex-1 overflow-hidden">
        {selectedSource && selectedDatasetId && selectedSampleIndex !== null ? (
          <DatasetDetailPane
            datasetSource={selectedSource}
            datasetId={selectedDatasetId}
            sampleIndex={selectedSampleIndex}
          />
        ) : (
          <div className="flex h-full items-center justify-center font-mono text-micro text-el-muted">
            $ select a sample
          </div>
        )}
      </div>
    </div>
  );
}
