import { useState } from "react";
import { useDatasetSampleDetail } from "../../hooks/useDatasets";
import BPill from "../common/BPill";
import JsonViewer from "../common/JsonViewer";

interface DatasetDetailPaneProps {
  datasetSource: string;
  datasetId: string;
  sampleIndex: number;
}

function FieldValue({ value }: { value: unknown }) {
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

function WorkflowPreviewBadge({ preview }: { preview: Record<string, unknown> }) {
  const compatible = Boolean(preview.compatible);
  return (
    <div>
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
}: DatasetDetailPaneProps) {
  const [metaOpen, setMetaOpen] = useState(false);
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
    <div className="h-full space-y-3 overflow-y-auto p-3">
      {/* Header */}
      <div>
        <div className="font-mono text-[11px] text-b-text">
          sample {data.sample_index} · {data.dataset_id}
          {data.sample_id && (
            <span className="ml-1 text-b-text-dim">#{data.sample_id}</span>
          )}
        </div>
        {data.summary && (
          <div className="mt-1 font-mono text-[11px] text-b-text-mid">
            {data.summary}
          </div>
        )}
      </div>

      {/* Fields */}
      <div className="space-y-2">
        {Object.entries(data.sample).map(([key, value]) => (
          <div key={key}>
            <div className="mb-0.5 font-mono text-[10px] uppercase tracking-wider text-b-text-dim">
              {key}
            </div>
            <div className="font-mono text-[11px] text-b-text">
              <FieldValue value={value} />
            </div>
          </div>
        ))}
      </div>

      {/* Dataset meta (collapsed by default) */}
      <div>
        <button
          onClick={() => setMetaOpen((v) => !v)}
          className="font-mono text-[10px] text-b-text-dim hover:text-b-text"
        >
          {metaOpen ? "[meta -]" : "[meta +]"}
        </button>
        {metaOpen && (
          <div className="mt-1 border border-b-line-soft bg-b-bg2 p-2">
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
