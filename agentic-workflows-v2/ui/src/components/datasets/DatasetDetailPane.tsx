import { useId, useState } from "react";
import { useDatasetSampleDetail } from "../../hooks/useDatasets";
import BPill from "../common/BPill";
import JsonViewer from "../common/JsonViewer";

interface DatasetDetailPaneProps {
  datasetSource: string;
  datasetId: string;
  sampleIndex: number;
}

function FieldValue({ value }: Readonly<{ value: unknown }>) {
  if (typeof value === "string") {
    return (
      <span>{value.length > 200 ? `${value.slice(0, 200)}…` : value}</span>
    );
  }
  if (typeof value === "object" && value !== null) {
    return <JsonViewer data={value} />;
  }
  return <span>{String(value)}</span>;
}

function WorkflowPreviewBadge({ preview }: Readonly<{ preview: Record<string, unknown> }>) {
  const compatible = Boolean(preview.compatible);
  return (
    <div>
      <div className="mb-1.5 font-mono text-[9px] uppercase tracking-[1.5px] text-b-text-faint">
        workflow preview
      </div>
      <BPill tone={compatible ? "ok" : "err"}>
        {compatible ? "[compatible]" : "[incompatible]"}
      </BPill>
      {compatible && preview.adapted_inputs != null && (
        <div className="mt-2">
          <JsonViewer data={preview.adapted_inputs} />
        </div>
      )}
    </div>
  );
}

export default function DatasetDetailPane({
  datasetSource,
  datasetId,
  sampleIndex,
}: Readonly<DatasetDetailPaneProps>) {
  const [metaOpen, setMetaOpen] = useState(false);
  const metaPanelId = useId();
  const { data, isLoading, error } = useDatasetSampleDetail(
    datasetSource,
    datasetId,
    sampleIndex
  );

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">
        $ loading sample…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 font-mono text-[11px] text-b-red">
        [!] failed to load sample
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="h-full space-y-4 overflow-y-auto p-4">
      {/* Header — stat numeric + identity */}
      <div className="flex items-end gap-3 border-b border-b-line-soft pb-3">
        <span
          className="tabular-nums leading-none text-b-clay"
          style={{
            fontFamily: "var(--b-font-heading)",
            fontSize: "34px",
            letterSpacing: "-1px",
          }}
        >
          {data.sample_index}
        </span>
        <div className="min-w-0 pb-0.5">
          <div className="font-mono text-[9px] uppercase tracking-[1.5px] text-b-text-faint">
            sample
          </div>
          <div className="truncate font-mono text-[11px] text-b-text">
            {data.dataset_id}
            {data.sample_id && (
              <span className="ml-1 text-b-text-dim">#{data.sample_id}</span>
            )}
          </div>
        </div>
      </div>

      {data.summary && (
        <div className="font-mono text-[11px] text-b-text-mid">
          {data.summary}
        </div>
      )}

      {/* Fields */}
      <div className="space-y-2.5">
        {Object.entries(data.sample).map(([key, value]) => (
          <div key={key}>
            <div className="mb-1 font-mono text-[9px] uppercase tracking-[1.5px] text-b-text-faint">
              {key}
            </div>
            <div className="font-mono text-[11px] leading-relaxed text-b-text">
              <FieldValue value={value} />
            </div>
          </div>
        ))}
      </div>

      {/* Dataset meta (collapsed by default) */}
      <div>
        <button
          type="button"
          aria-expanded={metaOpen}
          aria-controls={metaPanelId}
          onClick={() => setMetaOpen((v) => !v)}
          className="font-mono text-[10px] text-b-text-dim hover:text-b-text"
        >
          {metaOpen ? "[meta -]" : "[meta +]"}
        </button>
        {metaOpen && (
          <div
            id={metaPanelId}
            className="mt-1.5 border border-b-line-soft bg-b-bg2 p-2.5"
            style={{ borderRadius: "var(--b-rad-sm)" }}
          >
            <JsonViewer data={data.dataset_meta} />
          </div>
        )}
      </div>

      {/* Workflow preview */}
      {data.workflow_preview != null && (
        <WorkflowPreviewBadge preview={data.workflow_preview} />
      )}
    </div>
  );
}
