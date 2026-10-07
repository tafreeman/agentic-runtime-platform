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
import { Button } from "../components/ui/button";
import TierMark, { tierLevel } from "../components/common/TierMark";
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
import { useApiAvailability } from "../hooks/useApiAvailability";
import { useWorkflowEditor } from "../hooks/useWorkflows";
import { formatApiError } from "../lib/apiErrors";

/** Bordered surface panel (graph, step strip, validation band). */
const PANEL_CLASS = "rounded-lg border border-el-divider bg-el-surface";

/** Small tracked overline label (type floor: text-micro). */
const OVERLINE_CLASS =
  "font-mono text-micro uppercase tracking-[1.5px] text-el-muted";

const API_REASON_ID = "workflow-editor-api-reason";

type EditorMode = "visual" | "yaml";

type Selection =
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string }
  | null;

function normalizeIssues(issues: WorkflowEditorValidationIssue[] | undefined) {
  return issues ?? [];
}

/**
 * Capability-tier mark classes for a tier badge — the same scale as the DAG
 * step nodes and the workflow detail page: a numbered tier ("t2", "tier3",
 * "4") maps T0–T2 → low, T3 → mid, T4–T5 → high; named aliases fall back to
 * fast/haiku → low, sonnet → mid, smart/opus → high.
 */
function tierClass(tier: string | null | undefined): string {
  const t = (tier ?? "").toLowerCase();
  const digit = /(\d+)/.exec(t);
  if (digit) {
    const level = Number(digit[1]);
    if (level <= 2) return "border-el-tier-low text-el-tier-low";
    if (level === 3) return "border-el-tier-mid text-el-tier-mid";
    return "border-el-tier-high text-el-tier-high";
  }
  if (t.includes("fast") || t.includes("haiku")) {
    return "border-el-tier-low text-el-tier-low";
  }
  if (t.includes("smart") || t.includes("opus")) {
    return "border-el-tier-high text-el-tier-high";
  }
  if (t.includes("sonnet")) {
    return "border-el-tier-mid text-el-tier-mid";
  }
  return "border-el-divider text-el-muted";
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
      className={`inline-flex min-h-9 items-center rounded-md border px-[11px] font-mono text-micro transition-colors focus-ring ${
        active
          ? "border-el-ink bg-el-subtle text-el-ink"
          : "border-el-divider bg-el-canvas text-el-muted hover:bg-el-hover hover:text-el-ink"
      }`}
    >
      {label}
    </button>
  );
}

export default function WorkflowEditorPage() {
  const { name } = useParams<{ name: string }>();
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useWorkflowEditor(name, true);
  const { apiDown, reason: apiReason } = useApiAvailability();

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

  // Status text + marker colour; "not validated" stays neutral, not green.
  const [validText, validTextClass, validDotClass] = (() => {
    if (issueCount === 0) return ["not validated", "text-el-muted", "bg-el-neutral"];
    return hasErrors
      ? [`${issueCount} blocking`, "text-el-danger", "bg-el-danger"]
      : ["valid", "text-el-success", "bg-el-success"];
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

  const apiActionProps = apiDown
    ? ({ "aria-describedby": API_REASON_ID } as const)
    : {};

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-el-canvas">
      {/* ── workflow header band ── */}
      <div className="p-4 pb-0">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 rounded-lg border border-el-divider bg-el-surface px-4 py-3.5">
          <Button
            asChild
            variant="ghost"
            size="icon"
            className="size-9"
          >
            <Link
              to={`/workflows/${encodeURIComponent(name ?? "")}`}
              aria-label="Back to workflow detail"
            >
              <ArrowLeft aria-hidden="true" />
            </Link>
          </Button>

          <div className="flex items-center gap-2.5">
            <span className="font-mono text-micro uppercase tracking-[1.2px] text-el-muted">
              Workflow
            </span>
            <h1 className="truncate font-display text-xl font-semibold text-el-ink">
              {name}
            </h1>
            {data?.read_only && (
              <span className="inline-flex items-center rounded-md bg-el-warning-soft px-1.5 py-px font-mono text-micro uppercase tracking-[0.5px] text-el-warning">
                read only
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <span className="font-mono text-micro uppercase tracking-[1.2px] text-el-muted">
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
            <span className="font-mono text-micro text-el-muted">
              {stepCount} steps · {edgeCount} edges
            </span>
            <span
              className={`flex items-center gap-1.5 font-mono text-micro ${validTextClass}`}
            >
              <span
                aria-hidden="true"
                className={`inline-block h-1.5 w-1.5 rounded-full ${validDotClass}`}
              />
              {validText}
            </span>
            {lastSavedAt && (
              <span className="font-mono text-micro text-el-muted">
                Last saved {new Date(lastSavedAt).toLocaleString()}
              </span>
            )}
            {isDirty && (
              <span className="inline-flex items-center rounded-md bg-el-info-soft px-1.5 py-px font-mono text-micro uppercase tracking-[0.5px] text-el-info">
                Unsaved changes
              </span>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => validateMutation.mutate()}
              disabled={
                apiDown ||
                validateMutation.isPending ||
                saveMutation.isPending ||
                isReadOnly
              }
              aria-busy={validateMutation.isPending}
              className="h-9"
              {...apiActionProps}
            >
              {validateMutation.isPending ? (
                <Loader2 aria-hidden="true" className="animate-spin" />
              ) : (
                <CheckCircle2 aria-hidden="true" />
              )}
              {validateMutation.isPending ? "Validating…" : "Validate"}
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => saveMutation.mutate()}
              disabled={apiDown || !isDirty || saveMutation.isPending || isReadOnly}
              aria-busy={saveMutation.isPending}
              className="h-9"
              {...apiActionProps}
            >
              {saveMutation.isPending ? (
                <Loader2 aria-hidden="true" className="animate-spin" />
              ) : (
                <Save aria-hidden="true" />
              )}
              {saveMutation.isPending ? "Saving…" : "Save"}
            </Button>
            <Button asChild variant="outline" size="sm" className="h-9">
              <Link to={`/workflows/${encodeURIComponent(name ?? "")}`}>
                run config →
              </Link>
            </Button>
          </div>
          {apiDown && (
            <p
              id={API_REASON_ID}
              className="w-full text-right font-mono text-micro text-el-muted"
            >
              {apiReason}
            </p>
          )}
        </div>
      </div>

      {(() => {
        if (isLoading) {
          return (
            <div className="flex flex-1 items-center justify-center font-mono text-xs text-el-muted">
              Loading workflow editor...
            </div>
          );
        }
        if (isError) {
          return (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center font-mono text-xs text-el-danger">
              <TriangleAlert aria-hidden="true" className="h-5 w-5" />
              <div>Unable to load workflow editor.</div>
              <div className="font-mono text-micro text-el-secondary">
                {formatApiError(error)}
              </div>
            </div>
          );
        }
        if (!data) {
          return (
            <div className="flex flex-1 items-center justify-center font-mono text-xs text-el-muted">
              No workflow editor data available.
            </div>
          );
        }
        return (
          <div className="grid flex-1 grid-cols-1 items-start gap-4 p-4 xl:grid-cols-[1.12fr_0.98fr]">
            {/* ── LEFT: canvas ── */}
            <div className="flex min-w-0 flex-col gap-4">
              <div className={`flex min-h-[420px] flex-col p-3.5 ${PANEL_CLASS}`}>
                <div className="flex items-center justify-between gap-3">
                  <span className={OVERLINE_CLASS}>
                    Graph · click nodes and edges to configure · drag handles to
                    connect
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleAddStep}
                    disabled={isReadOnly || mode !== "visual"}
                    className="h-9"
                  >
                    <Plus aria-hidden="true" />
                    add step
                  </Button>
                </div>
                {/* Explicit height, not min-h/flex-1: WorkflowDAG's root is
                    h-full and React Flow needs a measurable parent (#004).
                    Percentage heights don't resolve against ancestors that
                    only carry min-height, so the pane was 0px tall and the
                    canvas rendered invisible. */}
                <div
                  data-testid="editor-graph-pane"
                  className="mt-2.5 h-[420px] overflow-hidden"
                >
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
              <div className={`p-3.5 ${PANEL_CLASS}`}>
                <span className={OVERLINE_CLASS}>Steps</span>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {graph.nodes.length === 0 && (
                    <div className="py-2 font-mono text-micro text-el-muted">
                      no steps defined
                    </div>
                  )}
                  {graph.nodes.map((node, index) => {
                    const isSelected =
                      selection?.kind === "node" && selection.id === node.id;
                    return (
                      <button
                        type="button"
                        key={node.id}
                        onClick={() => setSelection({ kind: "node", id: node.id })}
                        aria-pressed={isSelected}
                        className={`flex min-h-9 items-center gap-2 rounded-md border px-2.5 py-1.5 text-left transition-colors focus-ring ${
                          isSelected
                            ? "border-el-accent-strong bg-el-subtle"
                            : "border-el-divider bg-el-canvas hover:bg-el-hover"
                        }`}
                      >
                        <span className="font-mono text-micro text-el-muted">
                          {index + 1}
                        </span>
                        <span className="text-xs font-medium text-el-ink">
                          {node.id}
                        </span>
                        {node.tier && (
                          <TierMark
                            tier={node.tier}
                            // Named aliases (fast/sonnet/opus) carry no digit;
                            // keep their text and the editor's alias tones.
                            label={tierLevel(node.tier) == null ? node.tier : undefined}
                            toneClass={tierClass(node.tier)}
                          />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* ── RIGHT: inspector — the vermilion top rail is its one key
                mark; the heading and border stay neutral. ── */}
            <div className="relative flex min-w-0 flex-col gap-4 overflow-hidden rounded-lg border border-el-divider bg-el-surface p-[18px]">
              <span
                aria-hidden="true"
                className="absolute inset-x-0 top-0 h-0.5 bg-el-accent"
              />
              <div className="flex items-center gap-2.5">
                <h2 className="font-mono text-micro font-semibold uppercase tracking-[1.5px] text-el-ink">
                  {selection?.kind === "edge" ? "Configure edge" : "Configure step"}
                </h2>
                {selection && (
                  <span className="font-mono text-micro text-el-muted">
                    {selection.id}
                  </span>
                )}
              </div>

              {mode === "yaml" && (
                <div className="rounded-md border border-el-divider bg-el-canvas">
                  <div className="border-b border-el-divider px-3 py-2">
                    <span className="flex items-center justify-between font-mono text-micro uppercase tracking-[0.8px] text-el-muted">
                      Workflow source (YAML)
                      <span className="text-el-faint">
                        {draftSource.length} chars
                      </span>
                    </span>
                  </div>
                  <div className="p-3">
                    {/* Dense technical editor: 14px minimum (design system
                        §10.2); focus-ring replaces the 50%-tint ring. */}
                    <textarea
                      value={draftSource}
                      onChange={(event) => setDraftSource(event.target.value)}
                      spellCheck={false}
                      readOnly={isReadOnly}
                      className="h-[430px] w-full resize-none rounded-md border border-el-control-border bg-el-raised p-3 font-mono text-sm leading-[1.55] text-el-ink focus-ring"
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
                <div className="rounded-md border border-dashed border-el-divider px-4 py-6 text-center font-mono text-xs text-el-muted">
                  Select a step or edge in the graph to configure it.
                </div>
              )}
            </div>

            {/* ── VALIDATION band ── */}
            <div className={`p-[18px] xl:col-span-2 ${PANEL_CLASS}`}>
              <div className="mb-3.5 flex items-center gap-3">
                <span className={OVERLINE_CLASS}>Validation</span>
                <span
                  className={`flex items-center gap-1.5 font-mono text-micro ${validTextClass}`}
                >
                  <span
                    aria-hidden="true"
                    className={`inline-block h-1.5 w-1.5 rounded-full ${validDotClass}`}
                  />
                  {validText}
                </span>
              </div>

              {validateMutation.isError && (
                <div className="mb-2 rounded-md border border-el-danger/40 bg-el-danger-soft px-3 py-2 font-mono text-xs text-el-danger">
                  {formatApiError(validateMutation.error)}
                </div>
              )}
              {saveMutation.isError && (
                <div className="mb-2 rounded-md border border-el-danger/40 bg-el-danger-soft px-3 py-2 font-mono text-xs text-el-danger">
                  {formatApiError(saveMutation.error)}
                </div>
              )}
              {issueCount === 0 && !validateMutation.isPending && (
                <div className="rounded-md border border-el-divider-soft bg-el-subtle px-3 py-2 font-mono text-xs text-el-muted">
                  No validation messages yet. Run validation to preview schema and
                  graph issues.
                </div>
              )}
              <div className="space-y-2">
                {issues.map((issue, index) => {
                  const isIssueError = issue.level === "error";
                  return (
                    <div
                      key={`${issue.level}-${issue.path ?? "root"}-${index}`}
                      className={`rounded-md border px-3 py-2 font-mono text-xs ${
                        isIssueError
                          ? "border-el-danger/40 bg-el-danger-soft text-el-danger"
                          : "border-el-warning/40 bg-el-warning-soft text-el-warning"
                      }`}
                    >
                      <div className="font-medium">{issue.message}</div>
                      {issue.path && (
                        <div className="mt-1 font-mono text-xs">{issue.path}</div>
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
