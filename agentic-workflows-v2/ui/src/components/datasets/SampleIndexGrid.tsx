import { useState } from "react";
import { useDatasetSamples } from "../../hooks/useDatasets";

interface SampleIndexGridProps {
  datasetSource: string;
  datasetId: string;
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}

export default function SampleIndexGrid({
  datasetSource,
  datasetId,
  selectedIndex,
  onSelect,
}: SampleIndexGridProps) {
  const [offset, setOffset] = useState(0);
  const limit = 20;
  const { data, isLoading, error } = useDatasetSamples(datasetSource, datasetId, offset, limit);

  if (isLoading) {
    return (
      <div className="p-3 font-mono text-[11px] text-b-text-dim">
        $ loading samples…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 font-mono text-[11px] text-b-red">
        [!] failed to load samples
      </div>
    );
  }

  if (!data || data.samples.length === 0) {
    return (
      <div className="p-3 font-mono text-[11px] text-b-text-dim">
        $ no samples found
      </div>
    );
  }

  const hasMore = offset + limit < data.sample_count;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="grid grid-cols-[3rem_1fr_3rem] gap-2 border-b border-b-line bg-b-bg2 px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-b-text-faint">
        <span>#</span>
        <span>TITLE</span>
        <span>FIELDS</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {data.samples.map((sample) => (
          <button
            key={sample.sample_index}
            onClick={() => onSelect(sample.sample_index)}
            className={`grid w-full grid-cols-[3rem_1fr_3rem] gap-2 border-b border-b-line-soft px-3 py-2 text-left hover:bg-b-bg2 ${
              selectedIndex === sample.sample_index ? "bg-b-bg3" : ""
            }`}
          >
            <span className="font-mono text-[11px] text-b-text-dim">
              {sample.sample_index}
            </span>
            <span className="truncate font-mono text-[11px] text-b-text">
              {sample.title}
            </span>
            <span className="font-mono text-[10px] text-b-text-faint">
              {sample.field_names.length}
            </span>
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between border-t border-b-line bg-b-bg2 px-3 py-1.5 font-mono text-[10px] text-b-text-dim">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - limit))}
          className="disabled:opacity-40 hover:text-b-text"
        >
          [&lt;]
        </button>
        <span>
          {offset + 1}–{Math.min(offset + limit, data.sample_count)} of{" "}
          {data.sample_count}
        </span>
        <button
          disabled={!hasMore}
          onClick={() => setOffset(offset + limit)}
          className="disabled:opacity-40 hover:text-b-text"
        >
          [&gt;]
        </button>
      </div>
    </div>
  );
}
