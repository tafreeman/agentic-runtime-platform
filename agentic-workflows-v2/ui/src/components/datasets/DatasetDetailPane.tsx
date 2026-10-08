import { CircleAlert } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { useDatasetSampleDetail } from "../../hooks/useDatasets";
import { useWorkflows } from "../../hooks/useWorkflows";
import BPill from "../common/BPill";
import JsonViewer from "../common/JsonViewer";
import { describeApiError } from "../../lib/apiErrors";

interface DatasetDetailPaneProps {
  datasetSource: string;
  datasetId: string;
  sampleIndex: number;
}

interface RunWithSampleProps {
  datasetSource: string;
  datasetId: string;
  sampleIndex: number;
}

/** Workflow picker + deep link that prefills a run with this sample. */
function RunWithSample({
  datasetSource,
  datasetId,
  sampleIndex,
}: Readonly<RunWithSampleProps>) {
  const [workflow, setWorkflow] = useState("");
  const { data: workflows, isLoading } = useWorkflows();
  const effectiveWorkflow = workflow || workflows?.[0] || "";
  const runHref = `/workflows/${encodeURIComponent(effectiveWorkflow)}?eval_source=${datasetSource}&eval_dataset=${encodeURIComponent(datasetId)}&samples=${sampleIndex}`;

  return (
    <div data-testid="run-with-sample">
      <div className="mb-1.5 font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
        run with this sample
      </div>
      <div className="flex items-center gap-2">
        <select
          aria-label="Workflow to run"
          data-testid="run-with-sample-workflow"
          value={effectiveWorkflow}
          onChange={(event) => setWorkflow(event.target.value)}
          className="focus-ring min-w-0 flex-1 rounded-md border border-el-control-border bg-el-canvas px-2 py-1.5 font-mono text-micro text-el-ink"
          disabled={isLoading || !workflows?.length}
        >
          {!workflows?.length ? (
            <option value="">
              {isLoading ? "loading workflows…" : "no workflows"}
            </option>
          ) : (
            workflows.map((wf) => (
              <option key={wf} value={wf}>
                {wf}
              </option>
            ))
          )}
        </select>
        {effectiveWorkflow ? (
          <Link
            to={runHref}
            aria-label="Configure run with this sample"
            data-testid="run-with-sample-link"
            className="focus-ring inline-flex min-h-9 flex-none items-center rounded-md px-1 font-mono text-micro font-semibold text-el-ink underline underline-offset-2 hover:text-el-accent-strong"
          >
            configure run →
          </Link>
        ) : null}
      </div>
    </div>
  );
}

function FieldValue({ value }: Readonly<{ value: unknown }>) {
  if (typeof value === "string") {
    return (
      // pre-wrap + break-words: diffs and multi-line prompts keep their line
      // breaks and long tokens wrap instead of widening the pane.
      <span className="whitespace-pre-wrap break-words">
        {value.length > 200 ? `${value.slice(0, 200)}…` : value}
      </span>
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
      <div className="mb-1.5 font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
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
      <div className="flex h-full items-center justify-center font-mono text-micro text-el-muted">
        $ loading sample…
      </div>
    );
  }

  if (error && !data) {
    const failure = describeApiError(error);
    // An unreachable API is already announced by the shell's offline banner.
    if (failure.unreachable) {
      return (
        <div className="p-3 font-mono text-micro text-el-muted">
          sample unavailable while the API is unreachable
        </div>
      );
    }
    return (
      <div role="alert" className="p-3 font-mono text-micro text-el-danger">
        <span className="flex items-start gap-1.5">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 flex-none" />
          <span>failed to load sample: {failure.summary}</span>
        </span>
        <span className="block pl-5 text-el-secondary">{failure.remedy}</span>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="h-full space-y-4 overflow-y-auto p-4">
      {/* Header — stat numeric + identity */}
      <div className="flex items-end gap-3 border-b border-el-divider-soft pb-3">
        <span className="font-display text-[34px] leading-none tracking-[-1px] tabular-nums text-el-ink">
          {data.sample_index}
        </span>
        <div className="min-w-0 pb-0.5">
          <div className="font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
            sample
          </div>
          <div className="truncate font-mono text-micro text-el-ink">
            {data.dataset_id}
            {data.sample_id && (
              <span className="ml-1 text-el-muted">#{data.sample_id}</span>
            )}
          </div>
        </div>
      </div>

      {data.summary && (
        <div className="font-mono text-micro text-el-secondary">
          {data.summary}
        </div>
      )}

      {/* Fields */}
      <div className="space-y-2.5">
        {Object.entries(data.sample).map(([key, value]) => (
          <div key={key}>
            <div className="mb-1 font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
              {key}
            </div>
            <div className="font-mono text-micro leading-relaxed text-el-ink">
              <FieldValue value={value} />
            </div>
          </div>
        ))}
      </div>

      {/* Run with this sample — deep link into the run config form */}
      <RunWithSample
        datasetSource={datasetSource}
        datasetId={datasetId}
        sampleIndex={sampleIndex}
      />

      {/* Dataset meta (collapsed by default) */}
      <div>
        <button
          type="button"
          aria-label="Toggle dataset metadata"
          aria-expanded={metaOpen}
          aria-controls={metaPanelId}
          onClick={() => setMetaOpen((v) => !v)}
          className="focus-ring inline-flex min-h-9 items-center rounded-md px-1 font-mono text-micro text-el-muted transition-colors hover:text-el-ink"
        >
          {metaOpen ? "[meta -]" : "[meta +]"}
        </button>
        {metaOpen && (
          <div
            id={metaPanelId}
            className="mt-1.5 rounded-md border border-el-divider-soft bg-el-subtle p-2.5"
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
