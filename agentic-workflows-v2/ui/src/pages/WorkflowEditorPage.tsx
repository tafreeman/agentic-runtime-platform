import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Loader2,
  Plus,
  Save,
  TriangleAlert,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import EdgeInspector from "../components/editor/EdgeInspector";
import NodeInspector from "../components/editor/NodeInspector";
import {
  addDependency,
  addStep,
  cloneDocument,
  deriveGraph,
  documentsEqual,
  edgeInfo,
  getStep,
  patchStep,
  patchStepInput,
  removeDependency,
  removeStep,
  type RawDocument,
  type RawStep,
} from "../components/editor/documentModel";
import {
  listObservers,
  listPersonas,
  listTools,
  probeModels,
  saveWorkflowEditor,
  saveWorkflowEditorDocument,
  validateWorkflowEditor,
  validateWorkflowEditorDocument,
} from "../api/client";
import type { WorkflowEditorValidationIssue } from "../api/types";
import { useWorkflowEditor } from "../hooks/useWorkflows";

const CARD_STYLE = {
  background: "rgb(var(--b-bg1))",
  border: "var(--b-bw) solid rgb(var(--b-line))",
  borderRadius: "var(--b-rad-lg)",
} as const;

const INPUT_STYLE = {
  background: "rgb(var(--b-bg0))",
  border: "var(--b-bw) solid rgb(var(--b-line))",
  borderRadius: "var(--b-rad-sm)",
} as const;

type EditorMode = "visual" | "yaml";

type Selection =
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string }
  | null;

function normalizeIssues(issues: WorkflowEditorValidationIssue[] | undefined) {
  return issues ?? [];
}

/** Resolve a theme-aware status color (CSS var) for a tier badge. */
function tierColor(tier: string | null | undefined): string {
  const t = (tier ?? "").toLowerCase();
  if (t.includes("0") || t.includes("fast") || t.includes("haiku")) {
    return "rgb(var(--b-green))";
  }
  if (t.includes("2") || t.includes("smart") || t.includes("opus")) {
    return "rgb(var(--b-purple))";
  }
  if (t.includes("1") || t.includes("sonnet")) {
    return "rgb(var(--b-blue))";
  }
  return "rgb(var(--b-text-dim))";
}

function ModePill({
  label,
  active,
  onClick,
}: Readonly<{ label: string; active: boolean; onClick: () => void }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className="inline-flex items-center font-mono text-[10.5px]"
      style={{
        border: "var(--b-bw) solid",
        borderColor: active ? "rgb(var(--b-clay))" : "rgb(var(--b-line))",
        borderRadius: "var(--b-rad-sm)",
        padding: "5px 11px",
        color: active ? "rgb(var(--b-text))" : "rgb(var(--b-text-dim))",
        background: active ? "rgb(var(--b-bg2))" : "rgb(var(--b-bg0))",
      }}
    >
      {label}
    </button>
  );
}

export default function WorkflowEditorPage() {
  const { name } = useParams<{ name: string }>();
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useWorkflowEditor(name, true);

  const [mode, setMode] = useState<EditorMode>("visual");
  const [selection, setSelection] = useState<Selection>(null);
  const [draftDocument, setDraftDocument] = useState<RawDocument | null>(null);
  const [savedDocument, setSavedDocument] = useState<RawDocument | null>(null);
  const [draftSource, setDraftSource] = useState("");
  const [savedSource, setSavedSource] = useState("");
  const [issues, setIssues] = useState<WorkflowEditorValidationIssue[]>([]);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    const document = data.document ?? null;
    setDraftDocument(document ? cloneDocument(document) : null);
    setSavedDocument(document ? cloneDocument(document) : null);
    setDraftSource(data.source ?? "");
    setSavedSource(data.source ?? "");
    setIssues([]);
    setLastSavedAt(data.updated_at ?? null);
    setSelection((current) => {
      if (current) return current;
      const first = data.nodes[0]?.id;
      return first ? { kind: "node", id: first } : null;
    });
  }, [data]);

  // Catalogs for the per-node pickers. Static per session.
  const personasQuery = useQuery({
    queryKey: ["personas"],
    queryFn: listPersonas,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const toolsQuery = useQuery({
    queryKey: ["tools"],
    queryFn: listTools,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const observersQuery = useQuery({
    queryKey: ["observers"],
    queryFn: listObservers,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const modelsQuery = useQuery({
    queryKey: ["model-probe"],
    queryFn: probeModels,
    staleTime: Number.POSITIVE_INFINITY,
  });

  const graph = useMemo(
    () => (draftDocument ? deriveGraph(draftDocument) : { nodes: [], edges: [] }),
    [draftDocument]
  );

  const stepNames = useMemo(
    () => graph.nodes.map((node) => node.id),
    [graph.nodes]
  );

  const selectedStep: RawStep | null = useMemo(() => {
    if (!draftDocument || selection?.kind !== "node") return null;
    return getStep(draftDocument, selection.id);
  }, [draftDocument, selection]);

  const selectedEdge = useMemo(() => {
    if (!draftDocument || selection?.kind !== "edge") return null;
    const [source, target] = selection.id.split("->");
    if (!source || !target) return null;
    return edgeInfo(draftDocument, source, target);
  }, [draftDocument, selection]);

  const applyDocument = (next: RawDocument) => {
    setDraftDocument(next);
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!name) throw new Error("Workflow name is required.");
      if (mode === "visual") {
        if (!draftDocument) throw new Error("No document loaded.");
        return saveWorkflowEditorDocument(name, draftDocument);
      }
      return saveWorkflowEditor(name, { source: draftSource });
    },
    onSuccess: (response) => {
      const workflow = response.workflow;
      const document = workflow.document ?? null;
      setDraftDocument(document ? cloneDocument(document) : null);
      setSavedDocument(document ? cloneDocument(document) : null);
      setDraftSource(workflow.source);
      setSavedSource(workflow.source);
      setIssues([]);
      setLastSavedAt(workflow.updated_at ?? new Date().toISOString());
      queryClient.setQueryData(["workflow-editor", name], workflow);
    },
  });

  const validateMutation = useMutation({
    mutationFn: async () => {
      if (!name) throw new Error("Workflow name is required.");
      if (mode === "visual") {
        if (!draftDocument) throw new Error("No document loaded.");
        return validateWorkflowEditorDocument(name, draftDocument);
      }
      return validateWorkflowEditor(name, { source: draftSource });
    },
    onSuccess: (response) => {
      setIssues(normalizeIssues(response.issues));
    },
  });

  const isDirty =
    mode === "visual"
      ? draftDocument != null && !documentsEqual(draftDocument, savedDocument)
      : data != null && draftSource !== savedSource;
  const issueCount = issues.length;
  const hasErrors = issues.some((issue) => issue.level === "error");
  const isReadOnly = Boolean(data?.read_only);

  const stepCount = graph.nodes.length;
  const edgeCount = graph.edges.length;

  const validColor = hasErrors ? "rgb(var(--b-red))" : "rgb(var(--b-green))";
  const validText = (() => {
    if (issueCount === 0) return "not validated";
    return hasErrors ? `${issueCount} blocking` : "valid";
  })();

  const handleModeSwitch = (nextMode: EditorMode) => {
    if (nextMode === mode) return;
    if (isDirty) {
      const confirmed = window.confirm(
        "You have unsaved changes in this mode. Switching discards them. Continue?"
      );
      if (!confirmed) return;
      // Reset the abandoned mode's draft so stale edits can't be saved later.
      if (mode === "visual") {
        setDraftDocument(savedDocument ? cloneDocument(savedDocument) : null);
      } else {
        setDraftSource(savedSource);
      }
    }
    setMode(nextMode);
  };

  const handleAddStep = () => {
    if (!draftDocument || isReadOnly) return;
    const after = selection?.kind === "node" ? selection.id : null;
    const { document, name: newName } = addStep(draftDocument, after);
    applyDocument(document);
    setSelection({ kind: "node", id: newName });
  };

  const handleDeleteStep = (stepName: string) => {
    if (!draftDocument || isReadOnly) return;
    applyDocument(removeStep(draftDocument, stepName));
    setSelection(null);
  };

  const handleConnect = (source: string, target: string) => {
    if (!draftDocument || isReadOnly) return;
    applyDocument(addDependency(draftDocument, source, target));
    setSelection({ kind: "edge", id: `${source}->${target}` });
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-b-bg0">
      {/* ── workflow header band ── */}
      <div className="p-4 pb-0">
        <div
          className="flex flex-wrap items-center gap-x-5 gap-y-3 bg-b-bg1 px-4 py-3.5"
          style={{
            border: "var(--b-bw) solid rgb(var(--b-line))",
            borderRadius: "var(--b-rad-lg)",
          }}
        >
          <Link
            to={`/workflows/${encodeURIComponent(name ?? "")}`}
            className="btn-ghost p-1"
            aria-label="Back to workflow detail"
          >
            <ArrowLeft aria-hidden="true" className="h-4 w-4" />
          </Link>

          <div className="flex items-center gap-2.5">
            <span className="font-mono text-[9px] uppercase tracking-[1.2px] text-b-text-faint">
              Workflow
            </span>
            <h1
              className="truncate font-semibold text-b-text"
              style={{ fontFamily: "var(--b-font-heading)", fontSize: "20px" }}
            >
              {name}
            </h1>
            {data?.read_only && (
              <span
                className="inline-flex items-center font-mono text-[9px] uppercase tracking-[0.5px] text-b-amber"
                style={{
                  border: "var(--b-bw) solid rgb(var(--b-amber) / 0.4)",
                  borderRadius: "var(--b-rad-sm)",
                  padding: "1px 6px",
                }}
              >
                read only
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <span className="font-mono text-[9px] uppercase tracking-[1.2px] text-b-text-faint">
              Mode
            </span>
            <ModePill
              label="visual"
              active={mode === "visual"}
              onClick={() => handleModeSwitch("visual")}
            />
            <ModePill
              label="yaml"
              active={mode === "yaml"}
              onClick={() => handleModeSwitch("yaml")}
            />
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="font-mono text-[10px] text-b-text-dim">
              {stepCount} steps · {edgeCount} edges
            </span>
            <span
              className="flex items-center gap-1.5 font-mono text-[10px]"
              style={{ color: validColor }}
            >
              <span
                aria-hidden="true"
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ background: validColor }}
              />
              {validText}
            </span>
            {lastSavedAt && (
              <span className="font-mono text-[10px] text-b-text-dim">
                Last saved {new Date(lastSavedAt).toLocaleString()}
              </span>
            )}
            {isDirty && (
              <span
                className="inline-flex items-center font-mono text-[9px] uppercase tracking-[0.5px] text-b-blue"
                style={{
                  border: "var(--b-bw) solid rgb(var(--b-blue) / 0.4)",
                  borderRadius: "var(--b-rad-sm)",
                  padding: "1px 6px",
                }}
              >
                Unsaved changes
              </span>
            )}
            <button
              type="button"
              onClick={() => validateMutation.mutate()}
              disabled={validateMutation.isPending || saveMutation.isPending || isReadOnly}
              aria-busy={validateMutation.isPending}
              className="btn-ghost"
            >
              {validateMutation.isPending ? (
                <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" />
              )}
              {validateMutation.isPending ? "Validating…" : "Validate"}
            </button>
            <button
              type="button"
              onClick={() => saveMutation.mutate()}
              disabled={!isDirty || saveMutation.isPending || isReadOnly}
              aria-busy={saveMutation.isPending}
              className="btn-primary"
            >
              {saveMutation.isPending ? (
                <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save aria-hidden="true" className="h-3.5 w-3.5" />
              )}
              {saveMutation.isPending ? "Saving…" : "Save"}
            </button>
            <Link
              to={`/workflows/${encodeURIComponent(name ?? "")}`}
              className="inline-flex items-center gap-1.5 bg-b-clay px-3.5 py-[7px] font-mono text-[11px] font-semibold text-b-ink transition-colors hover:bg-b-clay/90 focus:outline-none focus:ring-1 focus:ring-b-clay/50"
              style={{ borderRadius: "var(--b-rad-sm)" }}
            >
              run config →
            </Link>
          </div>
        </div>
      </div>

      {(() => {
        if (isLoading) {
          return (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-text-dim">
              Loading workflow editor...
            </div>
          );
        }
        if (isError) {
          return (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center font-mono text-[11px] text-b-red">
              <TriangleAlert aria-hidden="true" className="h-5 w-5" />
              <div>Unable to load workflow editor.</div>
              <div className="font-mono text-[10px] text-b-red/70">{error.message}</div>
            </div>
          );
        }
        if (!data) {
          return (
            <div className="flex flex-1 items-center justify-center font-mono text-[11px] text-b-text-dim">
              No workflow editor data available.
            </div>
          );
        }
        return (
          <div className="grid flex-1 grid-cols-1 items-start gap-4 p-4 xl:grid-cols-[1.12fr_0.98fr]">
            {/* ── LEFT: canvas ── */}
            <div className="flex min-w-0 flex-col gap-4">
              <div className="flex min-h-[420px] flex-col p-3.5" style={CARD_STYLE}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
                    Graph · click nodes and edges to configure · drag handles to
                    connect
                  </span>
                  <button
                    type="button"
                    onClick={handleAddStep}
                    disabled={isReadOnly || mode !== "visual"}
                    className="btn-ghost"
                  >
                    <Plus aria-hidden="true" className="h-3.5 w-3.5" />
                    add step
                  </button>
                </div>
                <div className="mt-2.5 min-h-[380px] flex-1 overflow-hidden">
                  <WorkflowDAG
                    dagNodes={graph.nodes}
                    dagEdges={graph.edges}
                    onNodeClick={(id) => setSelection({ kind: "node", id })}
                    onEdgeClick={(id) => setSelection({ kind: "edge", id })}
                    onConnect={
                      mode === "visual" && !isReadOnly ? handleConnect : undefined
                    }
                    selectedNodeId={
                      selection?.kind === "node" ? selection.id : null
                    }
                    selectedEdgeId={
                      selection?.kind === "edge" ? selection.id : null
                    }
                    showEdgeLabels
                  />
                </div>
              </div>

              {/* step strip */}
              <div className="p-3.5" style={CARD_STYLE}>
                <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
                  Steps
                </span>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {graph.nodes.length === 0 && (
                    <div className="py-2 font-mono text-[10px] text-b-text-faint">
                      no steps defined
                    </div>
                  )}
                  {graph.nodes.map((node, index) => {
                    const isSelected =
                      selection?.kind === "node" && selection.id === node.id;
                    const color = tierColor(node.tier);
                    return (
                      <button
                        type="button"
                        key={node.id}
                        onClick={() => setSelection({ kind: "node", id: node.id })}
                        aria-pressed={isSelected}
                        className="flex items-center gap-2 text-left"
                        style={{
                          background: isSelected
                            ? "rgb(var(--b-bg2))"
                            : "rgb(var(--b-bg0))",
                          border: `var(--b-bw) solid ${isSelected ? "rgb(var(--b-clay))" : "rgb(var(--b-line))"}`,
                          borderRadius: "var(--b-rad-sm)",
                          padding: "6px 10px",
                        }}
                      >
                        <span className="font-mono text-[9px] text-b-text-faint">
                          {index + 1}
                        </span>
                        <span className="text-[11.5px] font-medium text-b-text">
                          {node.id}
                        </span>
                        {node.tier && (
                          <span
                            className="font-mono text-[8.5px] uppercase"
                            style={{
                              color,
                              border: `1px solid ${color}`,
                              borderRadius: "var(--b-rad-sm)",
                              padding: "0px 4px",
                            }}
                          >
                            {node.tier}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* ── RIGHT: inspector (clay accent) ── */}
            <div
              className="relative flex min-w-0 flex-col gap-4 overflow-hidden p-[18px]"
              style={{
                background: "rgb(var(--b-bg1))",
                border: "var(--b-bw) solid rgb(var(--b-clay))",
                borderRadius: "var(--b-rad-lg)",
              }}
            >
              <span
                aria-hidden="true"
                className="absolute inset-x-0 top-0 h-0.5"
                style={{ background: "rgb(var(--b-clay))" }}
              />
              <div className="flex items-center gap-2.5">
                <h2 className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-clay">
                  {selection?.kind === "edge" ? "Configure edge" : "Configure step"}
                </h2>
                {selection && (
                  <span className="font-mono text-[9.5px] text-b-text-faint">
                    {selection.id}
                  </span>
                )}
              </div>

              {mode === "yaml" && (
                <div style={{ ...INPUT_STYLE }}>
                  <div
                    className="px-3 py-2"
                    style={{ borderBottom: "var(--b-bw) solid rgb(var(--b-line))" }}
                  >
                    <span className="flex items-center justify-between font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
                      Workflow source (YAML)
                      <span className="text-b-text-faint">
                        {draftSource.length} chars
                      </span>
                    </span>
                  </div>
                  <div className="p-3">
                    <textarea
                      value={draftSource}
                      onChange={(event) => setDraftSource(event.target.value)}
                      spellCheck={false}
                      readOnly={isReadOnly}
                      className="h-[430px] w-full resize-none border border-b-line bg-b-bg0 p-3 font-mono text-[11.5px] leading-[1.55] text-b-text focus:border-b-clay focus:outline-none focus:ring-1 focus:ring-b-clay/50"
                      style={{ borderRadius: "var(--b-rad-sm)" }}
                      aria-label="Workflow source"
                    />
                  </div>
                </div>
              )}

              {mode === "visual" && selection?.kind === "edge" && selectedEdge && (
                <EdgeInspector
                  edge={selectedEdge}
                  readOnly={isReadOnly}
                  onPatchMapping={(inputKey, expression) => {
                    if (!draftDocument) return;
                    applyDocument(
                      patchStepInput(
                        draftDocument,
                        selectedEdge.target,
                        inputKey,
                        expression
                      )
                    );
                  }}
                  onPatchWhen={(when) => {
                    if (!draftDocument) return;
                    applyDocument(
                      patchStep(draftDocument, selectedEdge.target, {
                        when: when || undefined,
                      })
                    );
                  }}
                  onRemoveEdge={() => {
                    if (!draftDocument) return;
                    applyDocument(
                      removeDependency(
                        draftDocument,
                        selectedEdge.source,
                        selectedEdge.target
                      )
                    );
                    setSelection({ kind: "node", id: selectedEdge.target });
                  }}
                />
              )}

              {mode === "visual" && selection?.kind === "node" && selectedStep && (
                <NodeInspector
                  step={selectedStep}
                  stepNames={stepNames}
                  personas={personasQuery.data?.personas ?? []}
                  tools={toolsQuery.data?.tools ?? []}
                  observers={observersQuery.data?.observers ?? []}
                  models={modelsQuery.data?.models ?? []}
                  readOnly={isReadOnly}
                  onPatch={(patch) => {
                    if (!draftDocument || selection?.kind !== "node") return;
                    applyDocument(patchStep(draftDocument, selection.id, patch));
                  }}
                  onDelete={() => {
                    if (selection?.kind === "node") handleDeleteStep(selection.id);
                  }}
                  onAddDependency={(source) => {
                    if (!draftDocument || selection?.kind !== "node") return;
                    applyDocument(
                      addDependency(draftDocument, source, selection.id)
                    );
                  }}
                  onRemoveDependency={(source) => {
                    if (!draftDocument || selection?.kind !== "node") return;
                    applyDocument(
                      removeDependency(draftDocument, source, selection.id)
                    );
                  }}
                />
              )}

              {mode === "visual" && !selectedStep && selection?.kind !== "edge" && (
                <div
                  className="px-4 py-6 text-center font-mono text-[11px] text-b-text-dim"
                  style={{
                    border: "var(--b-bw) dashed rgb(var(--b-line))",
                    borderRadius: "var(--b-rad-sm)",
                  }}
                >
                  Select a step or edge in the graph to configure it.
                </div>
              )}
            </div>

            {/* ── VALIDATION band ── */}
            <div className="xl:col-span-2 p-[18px]" style={CARD_STYLE}>
              <div className="mb-3.5 flex items-center gap-3">
                <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
                  Validation
                </span>
                <span
                  className="flex items-center gap-1.5 font-mono text-[10px]"
                  style={{ color: validColor }}
                >
                  <span
                    aria-hidden="true"
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{ background: validColor }}
                  />
                  {validText}
                </span>
              </div>

              {validateMutation.isError && (
                <div
                  className="mb-2 px-3 py-2 font-mono text-[11px] text-b-red"
                  style={{
                    border: "var(--b-bw) solid rgb(var(--b-red) / 0.4)",
                    borderRadius: "var(--b-rad-sm)",
                    background: "rgb(var(--b-red) / 0.1)",
                  }}
                >
                  {validateMutation.error.message}
                </div>
              )}
              {saveMutation.isError && (
                <div
                  className="mb-2 px-3 py-2 font-mono text-[11px] text-b-red"
                  style={{
                    border: "var(--b-bw) solid rgb(var(--b-red) / 0.4)",
                    borderRadius: "var(--b-rad-sm)",
                    background: "rgb(var(--b-red) / 0.1)",
                  }}
                >
                  {saveMutation.error.message}
                </div>
              )}
              {issueCount === 0 && !validateMutation.isPending && (
                <div
                  className="px-3 py-2 font-mono text-[11px] text-b-text-dim"
                  style={{
                    border: "var(--b-bw) solid rgb(var(--b-line))",
                    borderRadius: "var(--b-rad-sm)",
                    background: "rgb(var(--b-bg2))",
                  }}
                >
                  No validation messages yet. Run validation to preview schema and
                  graph issues.
                </div>
              )}
              <div className="space-y-2">
                {issues.map((issue, index) => {
                  const isIssueError = issue.level === "error";
                  const accent = isIssueError ? "var(--b-red)" : "var(--b-amber)";
                  return (
                    <div
                      key={`${issue.level}-${issue.path ?? "root"}-${index}`}
                      className={`px-3 py-2 font-mono text-[11px] ${isIssueError ? "text-b-red" : "text-b-amber"}`}
                      style={{
                        border: `var(--b-bw) solid rgb(${accent} / 0.4)`,
                        borderRadius: "var(--b-rad-sm)",
                        background: `rgb(${accent} / 0.1)`,
                      }}
                    >
                      <div className="font-medium">{issue.message}</div>
                      {issue.path && (
                        <div className="mt-1 font-mono text-[11px] opacity-80">
                          {issue.path}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
