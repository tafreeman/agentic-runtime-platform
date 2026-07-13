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
    <div
      className="border-b border-b-line-soft bg-b-bg2 px-3 py-1.5 font-mono text-[9px] uppercase tracking-[1.5px] text-b-text-faint"
    >
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
      onClick={onSelect}
      className={`relative grid w-full grid-cols-[1fr_auto] items-center gap-2 border-b border-b-line-soft px-3 py-2 text-left transition-colors hover:bg-b-bg2 ${
        active ? "bg-b-bg3" : ""
      }`}
    >
      {active && (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-[2px] bg-b-clay"
        />
      )}
      <span className="min-w-0">
        <span className="block truncate font-mono text-[11px] text-b-text">
          {dataset.name}
        </span>
        <span className="block truncate font-mono text-[10px] text-b-text-dim">
          {dataset.id}
        </span>
      </span>
      {dataset.sample_count != null && (
        <span className="flex flex-col items-end leading-none">
          <span
            className="tabular-nums text-[14px] text-b-text-mid"
            style={{
              fontFamily: "var(--b-font-heading)",
              letterSpacing: "-0.5px",
            }}
          >
            {dataset.sample_count}
          </span>
          <span className="mt-0.5 font-mono text-[8px] uppercase tracking-[1px] text-b-text-faint">
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
    <div
      className="flex h-full overflow-hidden bg-b-bg1"
      style={{
        border: "var(--b-bw) solid rgb(var(--b-line))",
        borderRadius: "var(--b-rad-lg)",
      }}
    >
      {/* Left pane — dataset list */}
      <div
        className="w-1/4 min-w-[160px] overflow-y-auto border-r border-b-line"
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
              <div key={es.id} className="border-b border-b-line-soft px-3 py-2">
                <div className="truncate font-mono text-[11px] text-b-text">
                  {es.name}
                </div>
                <div className="font-mono text-[10px] text-b-text-dim">
                  {es.datasets.length} linked datasets
                </div>
                {es.datasets.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {es.datasets.map((d) => (
                      <span
                        key={d}
                        className="inline-flex items-center bg-b-bg3 px-1.5 py-px font-mono text-[10px] text-b-text-mid"
                        style={{ borderRadius: "var(--b-rad-sm)" }}
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
            <div className="px-3 py-4 font-mono text-[11px] text-b-text-dim">
              $ no datasets available
            </div>
          )}
      </div>

      {/* Middle pane — sample index */}
      <div className="w-1/3 overflow-hidden border-r border-b-line">
        {selectedSource && selectedDatasetId ? (
          <SampleIndexGrid
            datasetSource={selectedSource}
            datasetId={selectedDatasetId}
            selectedIndex={selectedSampleIndex}
            onSelect={setSelectedSampleIndex}
          />
        ) : (
          <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
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
          <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
            $ select a sample
          </div>
        )}
      </div>
    </div>
  );
}
