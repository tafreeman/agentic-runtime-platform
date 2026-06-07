import { useMemo, useRef, useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { useWorkflows } from "../hooks/useWorkflows";
import { useRuns } from "../hooks/useRuns";
import BTopBar from "../components/layout/BTopBar";
import BPill from "../components/common/BPill";
import type { RunSummary } from "../api/types";

function latestRunFor(runs: RunSummary[] | undefined, name: string) {
  if (!runs) return null;
  return runs.find((r) => r.workflow_name === name) ?? null;
}

function statusTone(status: string | null | undefined) {
  if (status === "success") return "ok" as const;
  if (status === "failed" || status === "error") return "err" as const;
  if (status === "running" || status === "in_progress") return "clay" as const;
  return "dim" as const;
}

export default function WorkflowsPage() {
  const { data: workflows, isLoading, isError, error } = useWorkflows();
  const { data: runs } = useRuns();
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const errorMessage =
    error instanceof Error ? error.message : "failed to load workflows";

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

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="workflows" />

      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-4 p-6">
          {/* Header */}
          <div>
            <h1
              className="text-[24px] font-semibold text-b-text"
              style={{ letterSpacing: "-0.5px" }}
            >
              Workflows
            </h1>
            <div className="mt-1 font-mono text-[11px] text-b-text-dim">
              $ {workflows?.length ?? 0} definitions · filter with{" "}
              <span className="text-b-clay">/</span>
            </div>
          </div>

          {/* Search */}
          <div className="flex items-center gap-2 rounded-sm border border-b-line bg-b-bg0 px-3 py-2 focus-within:ring-1 focus-within:ring-b-clay/50">
            <span className="font-mono text-[13px] font-bold text-b-clay">
              /
            </span>
            <input
              ref={inputRef}
              type="text"
              placeholder="filter by name, tag…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 bg-transparent font-mono text-[11px] text-b-text placeholder:text-b-text-faint focus:outline-none focus:ring-0"
            />
            {query && (
              <span className="font-mono text-[10px] text-b-text-dim">
                {filtered.length} match
              </span>
            )}
          </div>

          {/* Loading */}
          {isLoading && (
            <div className="space-y-[2px]">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={`workflow-skeleton-${i}`}
                  className="h-[52px] animate-pulse rounded-sm border border-b-line bg-b-bg1"
                />
              ))}
            </div>
          )}

          {isError && !isLoading && (
            <div className="rounded-sm border border-b-red/40 bg-b-red/10 px-3 py-3 font-mono text-[11px] text-b-red">
              [!] {errorMessage}
            </div>
          )}

          {!isError &&
            !isLoading &&
            (workflows?.length ?? 0) === 0 &&
            !query && (
              <div className="rounded-sm border border-dashed border-b-line py-10 text-center font-mono text-[11px] text-b-text-dim">
                $ no workflow definitions found
              </div>
            )}

          {/* List */}
          {!isError && (workflows?.length ?? 0) > 0 && (
            <div className="space-y-[2px]">
              {filtered.map((name) => {
                const latest = latestRunFor(runs, name);
                return (
                  <Link
                    key={name}
                    to={`/workflows/${name}`}
                    data-testid={`workflow-link-${name}`}
                    className="group flex items-center gap-3 border border-b-line border-l-2 bg-b-bg1 px-3 py-3 transition-colors hover:bg-b-bg2 hover:border-l-b-clay focus:outline-none focus:ring-1 focus:ring-b-clay/50"
                  >
                    <span className="font-mono text-[14px] text-b-blue">
                      ▣
                    </span>
                    <div className="flex-1 min-w-0">
                      <div
                        className="truncate font-mono text-[14px] font-semibold text-b-text"
                        style={{ fontFamily: "var(--b-font-mono)" }}
                      >
                        {name}
                      </div>
                      <div className="mt-0.5 truncate font-mono text-[10px] text-b-text-dim">
                        #{name.replaceAll("_", "-")}
                      </div>
                    </div>
                    {latest && (
                      <BPill tone={statusTone(latest.status)}>
                        {latest.status ?? "—"}
                      </BPill>
                    )}
                    <ChevronRight className="h-4 w-4 text-b-text-faint group-hover:text-b-clay" />
                  </Link>
                );
              })}

              {filtered.length === 0 && !isLoading && (
                <div className="rounded-sm border border-dashed border-b-line py-10 text-center font-mono text-[11px] text-b-text-dim">
                  {`no workflows match "`}<span className="text-b-text">{query}</span>{'"'}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
