import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Loader2, Save, TriangleAlert } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import { saveWorkflowEditor, validateWorkflowEditor } from "../api/client";
import type { DAGNode, WorkflowEditorValidationIssue } from "../api/types";
import { useWorkflowEditor } from "../hooks/useWorkflows";

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
      <div className="border-b border-white/5 px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <Link to={`/workflows/${encodeURIComponent(name ?? "")}`} className="btn-ghost p-1" aria-label="Back to workflow detail">
            <ArrowLeft className="h-4 w-4" />
          </Link>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-sm font-semibold">{name}</h1>
              <span className="rounded-full border border-white/10 bg-surface-2 px-2 py-0.5 text-[11px] uppercase tracking-wide text-gray-400">
                Builder
              </span>
              {data?.read_only && (
                <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-300">
                  Read only
                </span>
              )}
            </div>
            <p className="truncate text-xs text-gray-600">
              {data?.description || "Edit YAML while previewing the workflow graph."}
            </p>
          </div>

          <div className="flex items-center gap-2 text-[11px] text-gray-500">
            {lastSavedAt && <span>Last saved {new Date(lastSavedAt).toLocaleString()}</span>}
            {issueCount > 0 && (
              <span className={`rounded-full px-2 py-0.5 ${hasErrors ? "bg-red-500/10 text-red-300" : "bg-amber-500/10 text-amber-300"}`}>
                {issueCount} issue{issueCount === 1 ? "" : "s"}
              </span>
            )}
            {isDirty && (
              <span className="rounded-full bg-blue-500/10 px-2 py-0.5 text-blue-300">
                Unsaved changes
              </span>
            )}
          </div>

          <button
            type="button"
            onClick={() => validateMutation.mutate()}
            disabled={validateMutation.isPending || saveMutation.isPending || isReadOnly}
            className="btn-ghost px-3 py-1.5 text-xs"
          >
            {validateMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
            Validate
          </button>
          <button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={!isDirty || saveMutation.isPending || isReadOnly}
            className="btn-primary px-3 py-1.5 text-xs"
          >
            {saveMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            Save
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 border-r border-white/5">
          {isLoading ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-600">Loading workflow editor...</div>
          ) : isError ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm text-red-400">
              <TriangleAlert className="h-5 w-5" />
              <div>Unable to load workflow editor.</div>
              <div className="text-xs text-red-300/80">{(error as Error).message}</div>
            </div>
          ) : data ? (
            <WorkflowDAG
              dagNodes={data.nodes}
              dagEdges={data.edges}
              onNodeClick={setSelectedStepId}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-gray-600">No workflow editor data available.</div>
          )}
        </div>

        <aside className="flex w-[420px] flex-col overflow-hidden bg-surface-1">
          <div className="border-b border-white/5 px-4 py-3">
            <h2 className="text-xs font-medium uppercase tracking-wide text-gray-500">Selected step</h2>
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            <StepInspector node={selectedNode} step={selectedStep} />

            <div className="mt-4 rounded-lg border border-white/5 bg-surface-0">
              <div className="border-b border-white/5 px-3 py-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-gray-500">Source preview</h3>
              </div>
              <div className="p-3">
                <textarea
                  value={draftSource}
                  onChange={(event) => setDraftSource(event.target.value)}
                  spellCheck={false}
                  readOnly={isReadOnly}
                  className="h-[300px] w-full resize-none rounded-md border border-white/10 bg-[#0d1117] p-3 font-mono text-xs leading-5 text-gray-200 focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue"
                  aria-label="Workflow source"
                />
              </div>
            </div>

            <div className="mt-4 rounded-lg border border-white/5 bg-surface-0">
              <div className="border-b border-white/5 px-3 py-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-gray-500">Validation</h3>
              </div>
              <div className="space-y-2 p-3 text-xs">
                {validateMutation.isError && (
                  <div className="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-red-300">
                    {(validateMutation.error as Error).message}
                  </div>
                )}
                {saveMutation.isError && (
                  <div className="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-red-300">
                    {(saveMutation.error as Error).message}
                  </div>
                )}
                {issueCount === 0 && !validateMutation.isPending && (
                  <div className="rounded-md border border-white/5 bg-surface-1 px-3 py-2 text-gray-500">
                    No validation messages yet. Run validation to preview schema and graph issues.
                  </div>
                )}
                {issues.map((issue, index) => (
                  <div
                    key={`${issue.level}-${issue.path ?? "root"}-${index}`}
                    className={`rounded-md border px-3 py-2 ${
                      issue.level === "error"
                        ? "border-red-500/20 bg-red-500/10 text-red-300"
                        : "border-amber-500/20 bg-amber-500/10 text-amber-300"
                    }`}
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
      <div className="rounded-lg border border-dashed border-white/10 px-4 py-6 text-center text-sm text-gray-600">
        Select a step in the graph to inspect its configuration.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-white/5 bg-surface-0 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-200">{node.id}</h3>
          <p className="mt-1 text-xs text-gray-500">{node.description || "No description provided."}</p>
        </div>
        {node.tier && (
          <span className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] uppercase tracking-wide text-gray-400">
            {node.tier}
          </span>
        )}
      </div>

      <dl className="mt-4 space-y-3 text-xs">
        <div>
          <dt className="mb-1 text-gray-500">Agent</dt>
          <dd className="text-gray-200">{node.agent ?? "Unassigned"}</dd>
        </div>
        <div>
          <dt className="mb-1 text-gray-500">Depends on</dt>
          <dd className="text-gray-200">
            {node.depends_on.length > 0 ? node.depends_on.join(", ") : "No dependencies"}
          </dd>
        </div>
        <div>
          <dt className="mb-1 text-gray-500">Prompt file</dt>
          <dd className="text-gray-200">{step?.prompt_file ?? "Not specified"}</dd>
        </div>
        <div>
          <dt className="mb-1 text-gray-500">Tools</dt>
          <dd className="text-gray-200">
            {step?.tools && step.tools.length > 0 ? step.tools.join(", ") : "No explicit tools"}
          </dd>
        </div>
        <div>
          <dt className="mb-1 text-gray-500">When</dt>
          <dd className="font-mono text-gray-200">{step?.when ?? "Always"}</dd>
        </div>
        <div>
          <dt className="mb-1 text-gray-500">Loop</dt>
          <dd className="font-mono text-gray-200">
            {step?.loop_until ? `${step.loop_until}${step.loop_max ? ` (max ${step.loop_max})` : ""}` : "No loop"}
          </dd>
        </div>
      </dl>
    </div>
  );
}
