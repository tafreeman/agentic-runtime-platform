import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Loader2, Save, TriangleAlert } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import WorkflowDAG from "../components/dag/WorkflowDAG";
import { saveWorkflowEditor, validateWorkflowEditor } from "../api/client";
import type { DAGNode, WorkflowEditorValidationIssue } from "../api/types";
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

const FIELD_LABEL_CLASS =
  "mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim";

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

/**
 * Design-styled runtime option pill (chosen vs faint). Visual only — the
 * inspector has no runtime-selection state, so these carry no handler.
 */
function RuntimePill({
  label,
  chosen,
}: Readonly<{ label: string; chosen: boolean }>) {
  return (
    <span
      className={`inline-flex items-center font-mono text-[10.5px] ${
        chosen
          ? "border-b-clay/50 bg-b-bg2 text-b-text"
          : "border-b-line bg-b-bg0 text-b-text-dim"
      }`}
      style={{
        border: "var(--b-bw) solid",
        borderColor: chosen ? "rgb(var(--b-clay) / 0.5)" : "rgb(var(--b-line))",
        borderRadius: "var(--b-rad-sm)",
        padding: "5px 11px",
      }}
    >
      {label}
    </span>
  );
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

  const stepCount = data?.nodes.length ?? 0;
  const edgeCount = data?.edges.length ?? 0;
  const selIdx = useMemo(() => {
    if (!data || !selectedStepId) return 0;
    const idx = data.nodes.findIndex((node) => node.id === selectedStepId);
    return idx >= 0 ? idx + 1 : 0;
  }, [data, selectedStepId]);

  const validColor = hasErrors ? "rgb(var(--b-red))" : "rgb(var(--b-green))";
  const validText = (() => {
    if (issueCount === 0) return "not validated";
    return hasErrors ? `${issueCount} blocking` : "valid";
  })();

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-b-bg0">
      {/* ── workflow header band — design ref (builder 519-535): bg1 card with
          theme border + rad-lg, not an edge-to-edge band. ── */}
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

          {/* DESIGN-GAP: design (builder 524-528) shows a RUNTIME subprocess/docker
              toggle. This inspector has no runtime-selection state or backend
              field to persist it, so the pills are presentational only (no
              handler). The interactive runtime selector is separate feature
              work. */}
          <div className="flex items-center gap-2">
            <span className="font-mono text-[9px] uppercase tracking-[1.2px] text-b-text-faint">
              Runtime
            </span>
            <RuntimePill label="subprocess" chosen />
            <RuntimePill label="docker" chosen={false} />
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
            {issueCount > 0 && (
              <span
                className="inline-flex items-center font-mono text-[9px] uppercase tracking-[0.5px]"
                style={{
                  color: hasErrors ? "rgb(var(--b-red))" : "rgb(var(--b-amber))",
                  border: `var(--b-bw) solid ${hasErrors ? "rgb(var(--b-red) / 0.4)" : "rgb(var(--b-amber) / 0.4)"}`,
                  borderRadius: "var(--b-rad-sm)",
                  padding: "1px 6px",
                }}
              >
                {issueCount} issue{issueCount === 1 ? "" : "s"}
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
            {/* The inspector has no compile/run handler — the live run action
                lives on the workflow detail page. Link there instead of
                rendering a dead disabled control. */}
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
          <div className="grid flex-1 grid-cols-1 items-start gap-4 p-4 xl:grid-cols-[0.92fr_1.18fr]">
            {/* ── LEFT: step list + DAG preview ── */}
            <div className="flex min-w-0 flex-col gap-4">
              <div className="p-3.5" style={CARD_STYLE}>
                <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
                  Steps
                </span>
                <div className="mt-2.5 flex flex-col gap-1.5">
                  {data.nodes.length === 0 && (
                    <div className="py-2 font-mono text-[10px] text-b-text-faint">
                      no steps defined
                    </div>
                  )}
                  {data.nodes.map((node, index) => {
                    const isSelected = node.id === selectedStepId;
                    const color = tierColor(node.tier);
                    const depLabel =
                      node.depends_on.length > 0
                        ? ` · ← ${node.depends_on.join(", ")}`
                        : "";
                    return (
                      <button
                        type="button"
                        key={node.id}
                        onClick={() => setSelectedStepId(node.id)}
                        aria-pressed={isSelected}
                        className="flex items-center gap-2.5 text-left"
                        style={{
                          background: isSelected
                            ? "rgb(var(--b-bg2))"
                            : "rgb(var(--b-bg0))",
                          border: `var(--b-bw) solid ${isSelected ? "rgb(var(--b-clay))" : "rgb(var(--b-line))"}`,
                          borderRadius: "var(--b-rad-sm)",
                          padding: "8px 10px",
                        }}
                      >
                        <span className="w-4 flex-none font-mono text-[9px] text-b-text-faint">
                          {index + 1}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[12px] font-medium text-b-text">
                            {node.id}
                          </span>
                          <span className="mt-0.5 block truncate font-mono text-[9.5px] text-b-text-dim">
                            {node.agent ?? "unassigned"}
                            {depLabel}
                          </span>
                        </span>
                        {node.tier && (
                          <span
                            className="flex-none font-mono text-[8.5px] uppercase tracking-[0.3px]"
                            style={{
                              color,
                              border: `1px solid ${color}`,
                              borderRadius: "var(--b-rad-sm)",
                              padding: "1px 5px",
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

              <div className="flex min-h-[260px] flex-col p-3.5" style={CARD_STYLE}>
                <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
                  DAG preview · derived from depends_on
                </span>
                <div className="mt-2.5 min-h-[220px] flex-1 overflow-hidden">
                  <WorkflowDAG
                    dagNodes={data.nodes}
                    dagEdges={data.edges}
                    onNodeClick={setSelectedStepId}
                  />
                </div>
              </div>
            </div>

            {/* ── RIGHT: configure step (clay accent) ── */}
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
                  Configure step
                </h2>
                <span className="font-mono text-[9.5px] text-b-text-faint">
                  step {selIdx}/{stepCount}
                </span>
              </div>

              <StepInspector node={selectedNode} step={selectedStep} />

              {/* source editor */}
              <div style={{ ...INPUT_STYLE }}>
                <div
                  className="px-3 py-2"
                  style={{ borderBottom: "var(--b-bw) solid rgb(var(--b-line))" }}
                >
                  <span className="flex items-center justify-between font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
                    System prompt · workflow source
                    <span className="text-b-text-faint">{draftSource.length} chars</span>
                  </span>
                </div>
                <div className="p-3">
                  <textarea
                    value={draftSource}
                    onChange={(event) => setDraftSource(event.target.value)}
                    spellCheck={false}
                    readOnly={isReadOnly}
                    className="h-[280px] w-full resize-none border border-b-line bg-b-bg0 p-3 font-mono text-[11.5px] leading-[1.55] text-b-text focus:border-b-clay focus:outline-none focus:ring-1 focus:ring-b-clay/50"
                    style={{ borderRadius: "var(--b-rad-sm)" }}
                    aria-label="Workflow source"
                  />
                </div>
              </div>
            </div>

            {/* ── EVALUATION SETUP band ── */}
            <div className="xl:col-span-2 p-[18px]" style={CARD_STYLE}>
              <div className="mb-3.5 flex items-center gap-3">
                <span className="font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-text-faint">
                  Evaluation setup
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
                  No validation messages yet. Run validation to preview schema and graph issues.
                </div>
              )}
              <div className="space-y-2">
                {issues.map((issue, index) => {
                  const isError = issue.level === "error";
                  const accent = isError ? "var(--b-red)" : "var(--b-amber)";
                  return (
                    <div
                      key={`${issue.level}-${issue.path ?? "root"}-${index}`}
                      className={`px-3 py-2 font-mono text-[11px] ${isError ? "text-b-red" : "text-b-amber"}`}
                      style={{
                        border: `var(--b-bw) solid rgb(${accent} / 0.4)`,
                        borderRadius: "var(--b-rad-sm)",
                        background: `rgb(${accent} / 0.1)`,
                      }}
                    >
                      <div className="font-medium">{issue.message}</div>
                      {issue.path && (
                        <div className="mt-1 font-mono text-[11px] opacity-80">{issue.path}</div>
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
      <div
        className="px-4 py-6 text-center font-mono text-[11px] text-b-text-dim"
        style={{
          border: "var(--b-bw) dashed rgb(var(--b-line))",
          borderRadius: "var(--b-rad-sm)",
        }}
      >
        Select a step in the graph to inspect its configuration.
      </div>
    );
  }

  const color = tierColor(node.tier);

  return (
    <div
      className="p-4"
      style={{
        background: "rgb(var(--b-bg0))",
        border: "var(--b-bw) solid rgb(var(--b-line))",
        borderRadius: "var(--b-rad-sm)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3
            className="truncate text-[15px] font-semibold text-b-text"
            style={{ fontFamily: "var(--b-font-heading)" }}
          >
            {node.id}
          </h3>
          <p className="mt-1 text-[12px] text-b-text-dim">
            {node.description || "No description provided."}
          </p>
        </div>
        {node.tier && (
          <span
            className="flex-none font-mono text-[8.5px] uppercase tracking-[0.3px]"
            style={{
              color,
              border: `1px solid ${color}`,
              borderRadius: "var(--b-rad-sm)",
              padding: "1px 5px",
            }}
          >
            {node.tier}
          </span>
        )}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
        <div>
          <dt className={FIELD_LABEL_CLASS}>Agent persona</dt>
          <dd className="font-mono text-[11px] text-b-text">{node.agent ?? "Unassigned"}</dd>
        </div>
        <div>
          <dt className={FIELD_LABEL_CLASS}>Depends on</dt>
          <dd className="font-mono text-[11px] text-b-text">
            {node.depends_on.length > 0 ? node.depends_on.join(", ") : "No dependencies"}
          </dd>
        </div>
        <div>
          <dt className={FIELD_LABEL_CLASS}>Prompt file</dt>
          <dd className="font-mono text-[11px] text-b-text">
            {step?.prompt_file ?? "Not specified"}
          </dd>
        </div>
        <div>
          <dt className={FIELD_LABEL_CLASS}>Tools allowlist</dt>
          <dd className="font-mono text-[11px] text-b-text">
            {step?.tools && step.tools.length > 0 ? step.tools.join(", ") : "No explicit tools"}
          </dd>
        </div>
        <div>
          <dt className={FIELD_LABEL_CLASS}>When · conditional</dt>
          <dd className="font-mono text-[11px] text-b-text">{step?.when ?? "Always"}</dd>
        </div>
        <div>
          <dt className={FIELD_LABEL_CLASS}>Loop</dt>
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
