import { CircleAlert } from "lucide-react";
import { useState } from "react";
import { useDatasetSamples } from "../../hooks/useDatasets";
import type { DatasetSampleSummary } from "../../api/types";
import { describeApiError } from "../../lib/apiErrors";

interface SampleIndexGridProps {
  datasetSource: string;
  datasetId: string;
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}

/**
 * Resolve the row's title + subtitle. Server titles fall back to a generic
 * "Sample N" for datasets without a natural title field — substitute the
 * task id / sample id / summary excerpt so rows stay recognizable.
 */
function sampleRowText(sample: DatasetSampleSummary): {
  title: string;
  subtitle: string | null;
} {
  const generic = sample.title === `Sample ${sample.sample_index}`;
  if (!generic) {
    return { title: sample.title, subtitle: sample.summary || null };
  }
  const identifier = sample.task_id ?? sample.sample_id;
  if (identifier) {
    return { title: identifier, subtitle: sample.summary || null };
  }
  return { title: sample.summary || sample.title, subtitle: null };
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
      <div className="p-3 font-mono text-micro text-el-muted">
        $ loading samples…
      </div>
    );
  }

  if (error && !data) {
    const failure = describeApiError(error);
    // An unreachable API is already announced by the shell's offline banner.
    if (failure.unreachable) {
      return (
        <div className="p-3 font-mono text-micro text-el-muted">
          samples unavailable while the API is unreachable
        </div>
      );
    }
    return (
      <div role="alert" className="p-3 font-mono text-micro text-el-danger">
        <span className="flex items-start gap-1.5">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 flex-none" />
          <span>failed to load samples: {failure.summary}</span>
        </span>
        <span className="block pl-5 text-el-secondary">{failure.remedy}</span>
      </div>
    );
  }

  if (!data || data.samples.length === 0) {
    return (
      <div className="p-3 font-mono text-micro text-el-muted">
        $ no samples in this dataset — pick another dataset
      </div>
    );
  }

  const hasMore = offset + limit < data.sample_count;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="grid grid-cols-[3rem_1fr_3rem] gap-2 border-b border-el-divider bg-el-subtle px-3 py-1.5 font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
        <span>#</span>
        <span>title</span>
        <span className="text-right">fields</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {data.samples.map((sample) => {
          const active = selectedIndex === sample.sample_index;
          const { title, subtitle } = sampleRowText(sample);
          return (
            <button
              key={sample.sample_index}
              type="button"
              aria-label={`Select sample ${sample.sample_index}`}
              data-testid={`sample-row-${sample.sample_index}`}
              aria-pressed={active}
              onClick={() => onSelect(sample.sample_index)}
              className={`focus-ring-inset relative grid min-h-9 w-full grid-cols-[3rem_1fr_3rem] items-center gap-2 border-b border-el-divider-soft px-3 py-2 text-left transition-colors hover:bg-el-hover ${
                active ? "bg-el-subtle" : ""
              }`}
            >
              {active && (
                <span
                  aria-hidden="true"
                  className="absolute inset-y-0 left-0 w-[2px] bg-el-accent"
                />
              )}
              <span className="tabular-nums font-mono text-micro text-el-muted">
                {sample.sample_index}
              </span>
              <span className="min-w-0">
                <span className="block truncate font-mono text-micro text-el-ink">
                  {title}
                </span>
                {subtitle ? (
                  <span className="block truncate font-mono text-micro text-el-muted">
                    {subtitle}
                  </span>
                ) : null}
              </span>
              <span className="text-right tabular-nums font-mono text-micro text-el-muted">
                {sample.field_names.length}
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between border-t border-el-divider bg-el-subtle px-1 font-mono text-micro text-el-muted">
        <button
          type="button"
          aria-label="Previous page"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - limit))}
          className="focus-ring-inset inline-flex min-h-9 min-w-9 items-center justify-center rounded-md text-el-ink transition-colors hover:bg-el-hover disabled:cursor-not-allowed disabled:opacity-40"
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
          className="focus-ring-inset inline-flex min-h-9 min-w-9 items-center justify-center rounded-md text-el-ink transition-colors hover:bg-el-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          [&gt;]
        </button>
      </div>
    </div>
  );
}
