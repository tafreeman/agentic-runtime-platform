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
}: Readonly<SampleIndexGridProps>) {
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
      <div className="grid grid-cols-[3rem_1fr_3rem] gap-2 border-b border-b-line bg-b-bg2 px-3 py-1.5 font-mono text-[9px] uppercase tracking-[1.5px] text-b-text-faint">
        <span>#</span>
        <span>title</span>
        <span className="text-right">fields</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {data.samples.map((sample) => {
          const active = selectedIndex === sample.sample_index;
          return (
            <button
              key={sample.sample_index}
              onClick={() => onSelect(sample.sample_index)}
              className={`relative grid w-full grid-cols-[3rem_1fr_3rem] items-center gap-2 border-b border-b-line-soft px-3 py-2 text-left transition-colors hover:bg-b-bg2 ${
                active ? "bg-b-bg3" : ""
              }`}
            >
              {active && (
                <span
                  aria-hidden="true"
                  className="absolute inset-y-0 left-0 w-[2px] bg-b-clay"
                />
              )}
              <span className="tabular-nums font-mono text-[11px] text-b-text-dim">
                {sample.sample_index}
              </span>
              <span className="truncate font-mono text-[11px] text-b-text">
                {sample.title}
              </span>
              <span className="text-right tabular-nums font-mono text-[10px] text-b-text-faint">
                {sample.field_names.length}
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between border-t border-b-line bg-b-bg2 px-3 py-1.5 font-mono text-[10px] text-b-text-dim">
        <button
          type="button"
          aria-label="Previous page"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - limit))}
          className="text-b-clay disabled:opacity-40 hover:text-b-text"
        >
          [&lt;]
        </button>
        <span className="tabular-nums">
          {offset + 1}–{Math.min(offset + limit, data.sample_count)} of{" "}
          {data.sample_count}
        </span>
        <button
          type="button"
          aria-label="Next page"
          disabled={!hasMore}
          onClick={() => setOffset(offset + limit)}
          className="text-b-clay disabled:opacity-40 hover:text-b-text"
        >
          [&gt;]
        </button>
      </div>
    </div>
  );
}
