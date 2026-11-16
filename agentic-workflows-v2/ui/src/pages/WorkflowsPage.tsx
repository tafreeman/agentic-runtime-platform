import { useMemo, useRef, useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Pencil, CircleAlert, Search } from "lucide-react";
import { useWorkflows } from "../hooks/useWorkflows";
import { useRuns } from "../hooks/useRuns";
import BTopBar from "../components/layout/BTopBar";
import StatusBadge from "../components/common/StatusBadge";
import NoData from "../components/states/NoData";
import { isWorkflowBuilderEnabled } from "../config/featureFlags";
import { describeApiError, formatApiError } from "../lib/apiErrors";
import type { RunSummary } from "../api/types";

function latestRunFor(runs: RunSummary[] | undefined, name: string) {
  if (!runs) return null;
  return runs.find((r) => r.workflow_name === name) ?? null;
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
          {/* Header — editorial serif title + one plain scope line (the count
              lives here once; no second hero numeral). */}
          <div>
            <h1 className="font-display text-[30px] font-semibold leading-none tracking-[-0.8px] text-el-ink">
              Workflows
            </h1>
            <p className="mt-2 text-xs text-el-muted">
              <span className="tabular-nums">{definitionCount ?? <NoData />}</span>{" "}
              definitions · open one to preview its graph and run it · filter
              with{" "}
              <kbd className="rounded-sm border border-el-divider px-1 font-mono text-micro text-el-ink">
                /
              </kbd>
            </p>
          </div>

          {/* Search — the wrapper draws a full-strength focus-within ring (the
              compliant replacement), so the bare input inside suppresses its
              own outline instead of drawing a second ring. */}
          <div className="flex items-center gap-2 rounded-md border border-el-control-border bg-el-surface h-10 px-3 focus-within:ring-2 focus-within:ring-el-focus focus-within:ring-offset-2 focus-within:ring-offset-el-canvas">
            <Search aria-hidden="true" className="size-3.5 flex-none text-el-muted" />
            <input
              ref={inputRef}
              type="text"
              aria-label="Filter workflows by name"
              aria-keyshortcuts="/"
              placeholder="Filter by name…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="min-h-0 flex-1 self-stretch bg-transparent text-xs text-el-ink outline-none placeholder:text-el-muted"
            />
            {query && (
              <span className="text-micro tabular-nums text-el-muted" aria-live="polite">
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
              <p className="py-6 text-center text-xs text-el-muted">
                Workflows can't load while the API is unreachable.
              </p>
            ) : (
              <div
                role="alert"
                className="rounded-md border border-el-danger/40 bg-el-danger-soft px-3 py-3 text-xs text-el-danger"
              >
                <span className="flex items-start gap-1.5">
                  <CircleAlert
                    aria-hidden="true"
                    className="mt-0.5 size-3.5 flex-none"
                  />
                  <span>{loadFailure.summary}</span>
                </span>
                <span className="block pl-5 text-el-ink">{loadFailure.remedy}</span>
              </div>
            ))}

          {loadFailure && !showLoadError && (
            <p role="status" className="text-xs text-el-muted">
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
              <div className="rounded-lg border border-dashed border-el-divider py-12 text-center text-xs text-el-muted">
                No workflow definitions found — add a workflow YAML
                definition, then reload this page
              </div>
            )}

          {/* List — hairline-ruled rows, a quiet hover tint */}
          {!showLoadError && definitionCount != null && definitionCount > 0 && (
            <div>
              <div className="flex items-center gap-3 px-3 pb-2 text-micro font-semibold uppercase tracking-[0.8px] text-el-muted">
                <span className="flex-1">Workflow</span>
                <span>Last run</span>
                {workflowBuilderEnabled && <span aria-hidden="true" className="w-[62px]" />}
              </div>
              {/* Hairline-ruled ledger rows (no card per row). */}
              <ul className="divide-y divide-el-divider-soft border-y border-el-divider">
              {filtered.map((name) => {
                const latest = latestRunFor(runs, name);
                return (
                  <li
                    key={name}
                    className="group relative flex min-h-14 items-stretch transition-colors hover:bg-el-hover"
                  >
                    <Link
                      to={`/workflows/${name}`}
                      data-testid={`workflow-link-${name}`}
                      className="focus-ring-inset flex min-w-0 flex-1 items-center gap-3 px-3 py-[14px]"
                    >
                      <span className="min-w-0 flex-1 truncate font-mono text-[14px] font-semibold text-el-ink">
                        {name}
                      </span>
                      {latest && (
                        <span className="flex-none">
                          <span className="sr-only">Last run: </span>
                          <StatusBadge status={latest.status} />
                        </span>
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
                        className="focus-ring-inset relative z-10 flex w-[74px] shrink-0 items-center justify-center gap-1.5 border-l border-el-divider-soft text-xs text-el-secondary transition-colors hover:bg-el-subtle hover:text-el-ink"
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                        Edit
                      </Link>
                    )}
                  </li>
                );
              })}
              </ul>

              {filtered.length === 0 && !isLoading && (
                <div className="mt-3 rounded-lg border border-dashed border-el-divider py-12 text-center text-xs text-el-muted">
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
