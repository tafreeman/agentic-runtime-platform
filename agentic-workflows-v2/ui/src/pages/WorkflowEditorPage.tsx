import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Loader2, Save, TriangleAlert } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import { saveWorkflowEditor, validateWorkflowEditor } from "../api/client";
import type { DAGNode, WorkflowEditorValidationIssue } from "../api/types";
import { useWorkflowEditor } from "../hooks/useWorkflows";
import BPill from "../components/common/BPill";

function normalizeIssues(issues: WorkflowEditorValidationIssue[] | undefined) {
  return issues ?? [];
}

export default function WorkflowEditorPage() {
  const { name } = useParams<{ name: string }>();
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useWorkflowEditor(name, true);

  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [draftSource, setDraftSource] = useState("");
  const [savedSource, setSavedSource] = useState("");
  const [issues, setIssues] = useState<WorkflowEditorValidationIssue[]>([]);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setDraftSource(data.source ?? "");
    setSavedSource(data.source ?? "");
    setIssues([]);
    setLastSavedAt(data.updated_at ?? null);
    setSelectedStepId((current) => current ?? data.nodes[0]?.id ?? null);
  }, [data]);

  const selectedNode = useMemo(() => {
    return data?.nodes.find((node) => node.id === selectedStepId) ?? null;
  }, [data, selectedStepId]);

  const selectedStep = useMemo(() => {
    if (!selectedStepId) return null;
    return data?.steps?.find((step) => step.name === selectedStepId) ?? null;
  }, [data, selectedStepId]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!name) throw new Error("Workflow name is required.");
      return saveWorkflowEditor(name, { source: draftSource });
    },
    onSuccess: (response) => {
      setDraftSource(response.workflow.source);
      setSavedSource(response.workflow.source);
      setIssues([]);
      setLastSavedAt(response.workflow.updated_at ?? new Date().toISOString());
      queryClient.setQueryData(["workflow-editor", name], response.workflow);
    },
  });

  const validateMutation = useMutation({
    mutationFn: async () => {
      if (!name) throw new Error("Workflow name is required.");
      return validateWorkflowEditor(name, { source: draftSource });
    },
    onSuccess: (response) => {
      setIssues(normalizeIssues(response.issues));
      if (response.workflow?.source) {
        setDraftSource(response.workflow.source);
        setSavedSource(response.workflow.source);
        queryClient.setQueryData(["workflow-editor", name], response.workflow);
      }
    },
  });

  const isDirty = data != null && draftSource !== savedSource;
  const issueCount = issues.length;
  const hasErrors = issues.some((issue) => issue.level === "error");
  const isReadOnly = Boolean(data?.read_only);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-b-line px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <Link to={`/workflows/${encodeURIComponent(name ?? "")}`} className="btn-ghost p-1" aria-label="Back to workflow detail">
            <ArrowLeft className="h-4 w-4" />
          </Link>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-[20px] font-semibold text-b-text">{name}</h1>
              <BPill tone="dim">Builder</BPill>
              {data?.read_only && (
                <BPill tone="warn">Read only</BPill>
              )}
            </div>
            <p className="truncate font-mono text-[11px] text-b-text-faint">
              {data?.description || "Edit YAML while previewing the workflow graph."}
            </p>
          </div>

          <div className="flex items-center gap-2 font-mono text-[11px] text-b-text-dim">
            {lastSavedAt && <span>Last saved {new Date(lastSavedAt).toLocaleString()}</span>}
            {issueCount > 0 && (
              <BPill tone={hasErrors ? "err" : "warn"}>
                {issueCount} issue{issueCount === 1 ? "" : "s"}
              </BPill>
            )}
            {isDirty && (
              <BPill tone="info">Unsaved changes</BPill>
            )}
          </div>

          <button
            type="button"
            onClick={() => validateMutation.mutate()}
            disabled={validateMutation.isPending || saveMutation.isPending || isReadOnly}
            aria-busy={validateMutation.isPending}
            className="btn-ghost"
          >
            {validateMutation.isPending ? <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
            {validateMutation.isPending ? "Validating…" : "Validate"}
          </button>
          <button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={!isDirty || saveMutation.isPending || isReadOnly}
            aria-busy={saveMutation.isPending}
            className="btn-primary"
          >
            {saveMutation.isPending ? <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {saveMutation.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 border-r border-b-line">
          {(() => {
            if (isLoading) {
              return <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">Loading workflow editor...</div>;
            }
            if (isError) {
              return (
                <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center font-mono text-[11px] text-b-red">
                  <TriangleAlert className="h-5 w-5" />
                  <div>Unable to load workflow editor.</div>
                  <div className="font-mono text-[10px] text-b-red/70">{error.message}</div>
                </div>
              );
            }
            if (data) {
              return (
                <WorkflowDAG
                  dagNodes={data.nodes}
                  dagEdges={data.edges}
                  onNodeClick={setSelectedStepId}
                />
              );
            }
            return <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-text-dim">No workflow editor data available.</div>;
          })()}
        </div>

        <aside className="flex w-[420px] flex-col overflow-hidden bg-b-bg1">
          <div className="border-b border-b-line px-4 py-3">
            <h2 className="font-mono text-[10px] font-medium uppercase tracking-[0.5px] text-b-text-faint">Selected step</h2>
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            <StepInspector node={selectedNode} step={selectedStep} />

            <div className="mt-4 rounded-sm border border-b-line bg-b-bg0">
              <div className="border-b border-b-line px-3 py-2">
                <h3 className="font-mono text-[10px] font-medium uppercase tracking-[0.5px] text-b-text-dim">Source preview</h3>
              </div>
              <div className="p-3">
                <textarea
                  value={draftSource}
                  onChange={(event) => setDraftSource(event.target.value)}
                  spellCheck={false}
                  readOnly={isReadOnly}
                  className="h-[300px] w-full resize-none rounded-sm border border-b-line bg-b-bg0 p-3 font-mono text-[11px] leading-5 text-b-text focus:border-b-clay focus:outline-none focus:ring-1 focus:ring-b-clay/50"
                  aria-label="Workflow source"
                />
              </div>
            </div>

            <div className="mt-4 rounded-sm border border-b-line bg-b-bg0">
              <div className="border-b border-b-line px-3 py-2">
                <h3 className="font-mono text-[10px] font-medium uppercase tracking-[0.5px] text-b-text-dim">Validation</h3>
              </div>
              <div className="space-y-2 p-3">
                {validateMutation.isError && (
                  <div className="rounded-sm border border-b-red/40 bg-b-red/10 px-3 py-2 font-mono text-[11px] text-b-red">
                    {validateMutation.error.message}
                  </div>
                )}
                {saveMutation.isError && (
                  <div className="rounded-sm border border-b-red/40 bg-b-red/10 px-3 py-2 font-mono text-[11px] text-b-red">
                    {saveMutation.error.message}
                  </div>
                )}
                {issueCount === 0 && !validateMutation.isPending && (
                  <div className="rounded-sm border border-b-line bg-b-bg2 px-3 py-2 font-mono text-[11px] text-b-text-dim">
                    No validation messages yet. Run validation to preview schema and graph issues.
                  </div>
                )}
                {issues.map((issue, index) => (
                  <div
                    key={`${issue.level}-${issue.path ?? "root"}-${index}`}
                    className={issue.level === "error" ? "rounded-sm border border-b-red/40 bg-b-red/10 px-3 py-2 font-mono text-[11px] text-b-red" : "rounded-sm border border-b-amber/40 bg-b-amber/10 px-3 py-2 font-mono text-[11px] text-b-amber"}
                  >
                    <div className="font-medium">{issue.message}</div>
                    {issue.path && <div className="mt-1 font-mono text-[11px] opacity-80">{issue.path}</div>}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function StepInspector({
  node,
  step,
}: Readonly<{
  node: DAGNode | null;
  step: {
    when?: string | null;
    loop_until?: string | null;
    loop_max?: number | null;
    tools?: string[];
    prompt_file?: string | null;
  } | null;
}>) {
  if (!node) {
    return (
      <div className="rounded-sm border border-dashed border-b-line px-4 py-6 text-center font-mono text-[11px] text-b-text-dim">
        Select a step in the graph to inspect its configuration.
      </div>
    );
  }

  return (
    <div className="rounded-sm border border-b-line bg-b-bg0 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-b-text">{node.id}</h3>
          <p className="mt-1 text-xs text-b-text-dim">{node.description || "No description provided."}</p>
        </div>
        {node.tier && (
          <BPill tone="dim">{node.tier}</BPill>
        )}
      </div>

      <dl className="mt-4 space-y-3">
        <div>
          <dt className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">Agent</dt>
          <dd className="font-mono text-[11px] text-b-text">{node.agent ?? "Unassigned"}</dd>
        </div>
        <div>
          <dt className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">Depends on</dt>
          <dd className="font-mono text-[11px] text-b-text">
            {node.depends_on.length > 0 ? node.depends_on.join(", ") : "No dependencies"}
          </dd>
        </div>
        <div>
          <dt className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">Prompt file</dt>
          <dd className="font-mono text-[11px] text-b-text">{step?.prompt_file ?? "Not specified"}</dd>
        </div>
        <div>
          <dt className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">Tools</dt>
          <dd className="font-mono text-[11px] text-b-text">
            {step?.tools && step.tools.length > 0 ? step.tools.join(", ") : "No explicit tools"}
          </dd>
        </div>
        <div>
          <dt className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">When</dt>
          <dd className="font-mono text-[11px] text-b-text">{step?.when ?? "Always"}</dd>
        </div>
        <div>
          <dt className="mb-1 font-mono text-[10px] uppercase tracking-[0.5px] text-b-text-dim">Loop</dt>
          <dd className="font-mono text-[11px] text-b-text">
            {(() => {
              if (!step?.loop_until) return "No loop";
              if (step.loop_max) return `${step.loop_until} (max ${step.loop_max})`;
              return step.loop_until;
            })()}
          </dd>
        </div>
      </dl>
    </div>
  );
}
