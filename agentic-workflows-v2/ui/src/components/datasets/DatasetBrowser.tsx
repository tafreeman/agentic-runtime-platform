import { useState } from "react";
import type { EvaluationDatasetsResponse } from "../../api/types";
import SampleIndexGrid from "./SampleIndexGrid";
import DatasetDetailPane from "./DatasetDetailPane";

interface DatasetBrowserProps {
  datasets: EvaluationDatasetsResponse;
}

type SelectedSource = "repository" | "local" | null;

export default function DatasetBrowser({ datasets }: DatasetBrowserProps) {
  const [selectedSource, setSelectedSource] = useState<SelectedSource>(null);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [selectedSampleIndex, setSelectedSampleIndex] = useState<number | null>(null);

  function selectDataset(source: SelectedSource, id: string) {
    setSelectedSource(source);
    setSelectedDatasetId(id);
    setSelectedSampleIndex(null);
  }

  return (
    <div className="flex h-full overflow-hidden border border-b-line">
      {/* Left pane — dataset list */}
      <div className="w-1/4 overflow-y-auto border-r border-b-line">
        {datasets.repository.length > 0 && (
          <div>
            <div className="border-b border-b-line-soft bg-b-bg2 px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-b-text-faint">
              repository ({datasets.repository.length})
            </div>
            {datasets.repository.map((ds) => (
              <button
                key={ds.id}
                onClick={() => selectDataset("repository", ds.id)}
                className={`w-full border-b border-b-line-soft px-3 py-2 text-left hover:bg-b-bg2 ${
                  selectedSource === "repository" && selectedDatasetId === ds.id
                    ? "bg-b-bg3"
                    : ""
                }`}
              >
                <div className="truncate font-mono text-[11px] text-b-text">
                  {ds.name}
                </div>
                <div className="font-mono text-[10px] text-b-text-dim">{ds.id}</div>
              </button>
            ))}
          </div>
        )}

        {datasets.local.length > 0 && (
          <div>
            <div className="border-b border-b-line-soft bg-b-bg2 px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-b-text-faint">
              local ({datasets.local.length})
            </div>
            {datasets.local.map((ds) => (
              <button
                key={ds.id}
                onClick={() => selectDataset("local", ds.id)}
                className={`w-full border-b border-b-line-soft px-3 py-2 text-left hover:bg-b-bg2 ${
                  selectedSource === "local" && selectedDatasetId === ds.id
                    ? "bg-b-bg3"
                    : ""
                }`}
              >
                <div className="truncate font-mono text-[11px] text-b-text">
                  {ds.name}
                </div>
                <div className="font-mono text-[10px] text-b-text-dim">{ds.id}</div>
              </button>
            ))}
          </div>
        )}

        {datasets.eval_sets.length > 0 && (
          <div>
            <div className="border-b border-b-line-soft bg-b-bg2 px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-b-text-faint">
              eval sets ({datasets.eval_sets.length})
            </div>
            {datasets.eval_sets.map((es) => (
              <div
                key={es.id}
                className="border-b border-b-line-soft px-3 py-2"
              >
                <div className="truncate font-mono text-[11px] text-b-text">
                  {es.name}
                </div>
                <div className="font-mono text-[10px] text-b-text-dim">
                  {es.datasets.length} linked datasets
                </div>
                {es.datasets.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {es.datasets.map((d) => (
                      <span
                        key={d}
                        className="rounded-sm bg-b-bg3 px-1 font-mono text-[10px] text-b-text-mid"
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
