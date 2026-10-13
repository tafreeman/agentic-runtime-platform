import { useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button } from "../ui/button";
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
    <div className="border-b border-el-divider-soft bg-el-subtle px-3 py-1.5 text-micro font-semibold uppercase tracking-wider text-el-muted">
      {children}
    </div>
  );
}

interface DatasetRowProps {
  dataset: EvaluationDatasetOption;
  active: boolean;
  onSelect: (event: React.MouseEvent<HTMLButtonElement>) => void;
}

function DatasetRow({ dataset, active, onSelect }: Readonly<DatasetRowProps>) {
  return (
    <button
      type="button"
      aria-label={`Select dataset ${dataset.name}`}
      data-testid={`dataset-row-${dataset.id}`}
      aria-pressed={active}
      onClick={onSelect}
      className={`focus-ring-inset relative grid min-h-14 w-full grid-cols-[1fr_auto] items-center gap-2 border-b border-el-divider-soft px-3 py-2 text-left transition-colors hover:bg-el-hover ${
        active ? "bg-el-subtle" : ""
      }`}
    >
      {active && (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-[2px] bg-el-accent-strong"
        />
      )}
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-el-ink">
          {dataset.name}
        </span>
        <span className="block truncate text-xs text-el-muted">
          {dataset.id}
        </span>
      </span>
      {dataset.sample_count != null && (
        <span className="flex flex-col items-end leading-none">
          <span className="text-sm font-medium tabular-nums text-el-secondary">
            {dataset.sample_count}
          </span>
          <span className="mt-0.5 text-micro text-el-muted">
            samples
          </span>
        </span>
      )}
    </button>
  );
}

export default function DatasetBrowser({ datasets }: Readonly<DatasetBrowserProps>) {
  const [params, setParams] = useSearchParams();
  const datasetTrigger = useRef<HTMLButtonElement | null>(null);
  const sampleTrigger = useRef<HTMLButtonElement | null>(null);
  // Fallback focus targets for selections restored from the URL, where no row
  // was clicked and so no trigger was recorded.
  const catalogPane = useRef<HTMLDivElement | null>(null);
  const samplePane = useRef<HTMLElement | null>(null);
  const source = params.get("source");
  const selectedSource: SelectedSource = source === "repository" || source === "local" ? source : null;
  const selectedDatasetId = selectedSource && datasets[selectedSource].some((dataset) => dataset.id === params.get("dataset"))
    ? params.get("dataset") : null;
  const sample = params.get("sample");
  const selectedSampleIndex = selectedDatasetId && sample !== null && /^\d+$/.test(sample) && Number.isSafeInteger(Number(sample))
    ? Number(sample) : null;

  function selectDataset(source: SelectedSource, id: string, trigger: HTMLButtonElement) {
    datasetTrigger.current = trigger;
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("source", source!);
      next.set("dataset", id);
      next.delete("sample");
      return next;
    });
  }

  function goBack(toCatalog: boolean) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete("sample");
      if (toCatalog) { next.delete("source"); next.delete("dataset"); }
      return next;
    });
    requestAnimationFrame(() => {
      const trigger = (toCatalog ? datasetTrigger : sampleTrigger).current;
      (trigger ?? (toCatalog ? catalogPane : samplePane).current)?.focus();
    });
  }

  return (
    <div className="flex h-full min-h-80 min-w-0 border-y border-el-divider bg-el-surface" onKeyDown={(event) => { if (event.key === "Escape" && selectedDatasetId) { event.stopPropagation(); goBack(selectedSampleIndex === null); } }}>
      {/* Left pane — dataset list */}
      <div
        ref={catalogPane}
        tabIndex={-1}
        aria-label="Dataset catalog" className={`min-w-0 flex-1 overflow-y-auto lg:w-1/4 lg:flex-none lg:border-r lg:border-el-divider ${selectedDatasetId ? "hidden lg:block" : "block"}`}
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
                onSelect={(event) => selectDataset("repository", ds.id, event.currentTarget)}
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
                onSelect={(event) => selectDataset("local", ds.id, event.currentTarget)}
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
                <div className="text-xs text-el-muted">
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
            <div className="px-3 py-4 text-xs text-el-muted">
              No datasets found. Add a dataset, then reload this page.
            </div>
          )}
      </div>

      {/* Middle pane — sample index */}
      <section ref={samplePane} tabIndex={-1} aria-label="Dataset samples" className={`min-w-0 flex-1 flex-col lg:flex lg:w-1/3 lg:flex-none lg:border-r lg:border-el-divider ${selectedDatasetId && selectedSampleIndex === null ? "flex" : "hidden"}`}>
        <div className="border-b border-el-divider-soft p-2 lg:hidden">
          <Button variant="ghost" onClick={() => goBack(true)}><ArrowLeft aria-hidden="true" />All datasets</Button>
        </div>
        <div className="min-h-0 flex-1">
        {selectedSource && selectedDatasetId ? (
          <SampleIndexGrid
            key={`${selectedSource}:${selectedDatasetId}`}
            datasetSource={selectedSource}
            datasetId={selectedDatasetId}
            selectedIndex={selectedSampleIndex}
            onSelect={(index, trigger) => {
              sampleTrigger.current = trigger;
              setParams((previous) => { const next = new URLSearchParams(previous); next.set("sample", String(index)); return next; });
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-el-muted">
            Select a dataset to inspect its samples.
          </div>
        )}
      </div>

      </section>
      {/* Narrow screens show one level at a time; desktop keeps the selection visible. */}
      <section aria-label="Sample detail" className={`min-w-0 flex-1 flex-col lg:flex ${selectedSampleIndex !== null ? "flex" : "hidden"}`}>
        <div className="border-b border-el-divider-soft p-2 lg:hidden">
          <Button variant="ghost" onClick={() => goBack(false)}><ArrowLeft aria-hidden="true" />Back to samples</Button>
        </div>
        <div className="min-h-0 flex-1">
        {selectedSource && selectedDatasetId && selectedSampleIndex !== null ? (
          <DatasetDetailPane
            datasetSource={selectedSource}
            datasetId={selectedDatasetId}
            sampleIndex={selectedSampleIndex}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-el-muted">
            Select a sample to inspect its evidence.
          </div>
        )}
        </div>
      </section>
    </div>
  );
}
