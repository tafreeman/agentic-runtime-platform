import { useMemo, useRef, useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Pencil } from "lucide-react";
import { useWorkflows } from "../hooks/useWorkflows";
import { useRuns } from "../hooks/useRuns";
import BTopBar from "../components/layout/BTopBar";
import BPill from "../components/common/BPill";
import NoData from "../components/states/NoData";
import { isWorkflowBuilderEnabled } from "../config/featureFlags";
import { describeApiError, formatApiError } from "../lib/apiErrors";
import type { RunSummary } from "../api/types";

function latestRunFor(runs: RunSummary[] | undefined, name: string) {
  if (!runs) return null;
  return runs.find((r) => r.workflow_name === name) ?? null;
}

function statusTone(status: string | null | undefined) {
  if (status === "success") return "ok" as const;
  if (status === "failed" || status === "error") return "err" as const;
  if (status === "running" || status === "in_progress") return "info" as const;
  return "dim" as const;
}

export default function WorkflowsPage() {
  const { data: workflows, isLoading, isError, error } = useWorkflows();
  const { data: runs } = useRuns();
  const workflowBuilderEnabled = isWorkflowBuilderEnabled();
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const loadFailure = isError ? describeApiError(error) : null;
  // A failed refetch keeps the last good catalog; only an empty-handed
  // failure replaces the list.
  const showLoadError = loadFailure != null && !workflows;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    globalThis.addEventListener("keydown", onKey);
    return () => globalThis.removeEventListener("keydown", onKey);
  }, []);

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return workflows ?? [];
    return (workflows ?? []).filter((name) =>
      name.toLowerCase().includes(q),
    );
  }, [workflows, query]);

  // Unknown (not zero) until the catalog has loaded.
  const definitionCount = workflows?.length;

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="workflows" />

      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-5 p-6">
          {/* Header — editorial serif title + stat numeric */}
          <div className="flex items-end justify-between gap-4">
            <div>
              <h1 className="font-display text-[30px] font-semibold leading-none tracking-[-0.8px] text-el-ink">
                Workflows
              </h1>
              <div className="mt-2 font-mono text-micro text-el-muted">
                $ {definitionCount ?? <NoData />} definitions · filter with{" "}
                <kbd className="font-mono font-semibold text-el-ink">/</kbd>
              </div>
            </div>
            <div className="text-right">
              <div className="font-display text-[34px] font-semibold leading-none tracking-[-1.2px] tabular-nums text-el-ink">
                {definitionCount ?? <NoData />}
              </div>
              <div className="mt-1 font-mono text-micro uppercase tracking-[1.5px] text-el-muted">
                Definitions
              </div>
            </div>
          </div>

          {/* Search — the wrapper draws a full-strength focus-within ring (the
              compliant replacement), so the bare input inside suppresses its
              own outline instead of drawing a second ring. */}
          <div className="flex items-center gap-2 rounded-md border border-el-divider bg-el-surface px-3 py-2 focus-within:ring-2 focus-within:ring-el-focus focus-within:ring-offset-2 focus-within:ring-offset-el-canvas">
            <span
              aria-hidden="true"
              className="font-mono text-[13px] font-bold text-el-secondary"
            >
              /
            </span>
            <input
              ref={inputRef}
              type="text"
              aria-label="Filter workflows by name or tag"
              placeholder="filter by name, tag…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 bg-transparent font-mono text-xs text-el-ink outline-none placeholder:text-el-muted"
            />
            {query && (
              <span className="font-mono text-micro text-el-muted" aria-live="polite">
                {filtered.length} match
              </span>
            )}
          </div>

          {/* Loading */}
          {isLoading && (
            <div className="space-y-[3px]">
              {(["sk-0", "sk-1", "sk-2"] as const).map((skId) => (
                <div
                  key={skId}
                  className="h-[58px] animate-pulse rounded-lg border border-el-divider bg-el-surface motion-reduce:animate-none"
                />
              ))}
            </div>
          )}

          {showLoadError &&
            !isLoading &&
            (loadFailure.unreachable ? (
              // The shell's offline banner already announces an unreachable
              // API; keep this to a quiet note instead of a second alert.
              <p className="py-6 text-center font-mono text-micro text-el-muted">
                Workflows can't load while the API is unreachable.
              </p>
            ) : (
              <div
                role="alert"
                className="rounded-md border border-el-danger/40 bg-el-danger-soft px-3 py-3 font-mono text-micro text-el-danger"
              >
                <span className="block">[!] {loadFailure.summary}</span>
                <span className="block text-el-ink">{loadFailure.remedy}</span>
              </div>
            ))}

          {loadFailure && !showLoadError && (
            <p role="status" className="font-mono text-micro text-el-muted">
              Showing the last loaded workflows — refresh failed:{" "}
              {loadFailure.unreachable
                ? "the API is unreachable."
                : formatApiError(error)}
            </p>
          )}

          {!showLoadError &&
            !isLoading &&
            definitionCount === 0 &&
            !query && (
              <div className="rounded-lg border border-dashed border-el-divider py-12 text-center font-mono text-micro text-el-muted">
                $ no workflow definitions found — add a workflow YAML
                definition, then reload this page
              </div>
            )}

          {/* List — hairline rows, an accent rail on hover/focus */}
          {!showLoadError && definitionCount != null && definitionCount > 0 && (
            <div className="space-y-[3px]">
              <div className="flex items-center gap-3 px-3 pb-1 font-mono text-micro uppercase tracking-[1px] text-el-muted">
                <span className="w-[14px]" aria-hidden="true" />
                <span className="flex-1">Workflow</span>
                <span>Last run</span>
                {workflowBuilderEnabled && <span className="w-[62px]">Edit</span>}
              </div>
              {filtered.map((name) => {
                const latest = latestRunFor(runs, name);
                return (
                  <div
                    key={name}
                    className="group relative flex items-stretch overflow-hidden rounded-lg border border-el-divider bg-el-surface transition-colors hover:bg-el-hover"
                  >
                    {/* accent rail — the hover/focus mark for the row */}
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-x-0 top-0 h-[2px] origin-left scale-x-0 bg-el-accent transition-transform group-focus-within:scale-x-100 group-hover:scale-x-100 motion-reduce:transition-none"
                    />
                    <Link
                      to={`/workflows/${name}`}
                      data-testid={`workflow-link-${name}`}
                      className="focus-ring-inset flex min-w-0 flex-1 items-center gap-3 rounded-l-lg px-3 py-[14px]"
                    >
                      <span
                        aria-hidden="true"
                        className="font-mono text-[14px] text-el-muted"
                      >
                        ▣
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-mono text-[14px] font-semibold text-el-ink">
                          {name}
                        </div>
                        <div className="mt-0.5 truncate font-mono text-micro text-el-muted">
                          #{name.replaceAll("_", "-")}
                        </div>
                      </div>
                      {latest && (
                        <BPill tone={statusTone(latest.status)}>
                          {latest.status ?? "—"}
                        </BPill>
                      )}
                      <ChevronRight
                        aria-hidden="true"
                        className="h-4 w-4 text-el-muted group-hover:text-el-ink"
                      />
                    </Link>
                    {workflowBuilderEnabled && (
                      <Link
                        to={`/workflows/${name}/edit`}
                        aria-label={`Edit ${name} workflow`}
                        data-testid={`workflow-edit-${name}`}
                        className="focus-ring-inset relative z-10 flex w-[74px] shrink-0 flex-col items-center justify-center gap-1 rounded-r-lg border-l border-el-divider font-mono text-micro uppercase tracking-[0.8px] text-el-muted transition-colors hover:bg-el-subtle hover:text-el-ink"
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                        edit
                      </Link>
                    )}
                  </div>
                );
              })}

              {filtered.length === 0 && !isLoading && (
                <div className="rounded-lg border border-dashed border-el-divider py-12 text-center font-mono text-micro text-el-muted">
                  no workflows match "
                  <span className="text-el-ink">{query}</span>" — clear the
                  filter to see all {definitionCount}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
