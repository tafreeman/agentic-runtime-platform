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

  const definitionCount = workflows?.length ?? 0;

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="workflows" />

      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-5 p-6">
          {/* Header — editorial serif title + stat numeric */}
          <div className="flex items-end justify-between gap-4">
            <div>
              <h1
                className="text-b-text"
                style={{
                  fontFamily: "var(--b-font-heading)",
                  fontSize: "30px",
                  fontWeight: 600,
                  letterSpacing: "-0.8px",
                  lineHeight: 1,
                }}
              >
                Workflows
              </h1>
              <div className="mt-2 font-mono text-[11px] text-b-text-dim">
                $ {definitionCount} definitions · filter with{" "}
                <span className="text-b-clay">/</span>
              </div>
            </div>
            <div className="text-right">
              <div
                className="text-b-text tabular-nums"
                style={{
                  fontFamily: "var(--b-font-heading)",
                  fontSize: "34px",
                  fontWeight: 600,
                  letterSpacing: "-1.2px",
                  lineHeight: 1,
                }}
              >
                {definitionCount}
              </div>
              <div className="mt-1 font-mono text-[9px] uppercase tracking-[1.5px] text-b-text-faint">
                Definitions
              </div>
            </div>
          </div>

          {/* Search — card with theme tokens */}
          <div
            className="flex items-center gap-2 border border-b-line bg-b-bg1 px-3 py-2 focus-within:ring-1 focus-within:ring-b-clay/50"
            style={{
              borderRadius: "var(--b-rad-sm)",
              borderWidth: "var(--b-bw)",
            }}
          >
            <span className="font-mono text-[13px] font-bold text-b-clay">
              /
            </span>
            <input
              ref={inputRef}
              type="text"
              aria-label="Filter workflows by name or tag"
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
            <div className="space-y-[3px]">
              {(["sk-0", "sk-1", "sk-2"] as const).map((skId) => (
                <div
                  key={skId}
                  className="h-[58px] animate-pulse border border-b-line bg-b-bg1"
                  style={{
                    borderRadius: "var(--b-rad-lg)",
                    borderWidth: "var(--b-bw)",
                  }}
                />
              ))}
            </div>
          )}

          {isError && !isLoading && (
            <div
              className="border border-b-red/40 bg-b-red/10 px-3 py-3 font-mono text-[11px] text-b-red"
              style={{
                borderRadius: "var(--b-rad-sm)",
                borderWidth: "var(--b-bw)",
              }}
            >
              [!] {errorMessage}
            </div>
          )}

          {!isError &&
            !isLoading &&
            definitionCount === 0 &&
            !query && (
              <div
                className="border border-dashed border-b-line py-12 text-center font-mono text-[11px] text-b-text-dim"
                style={{ borderRadius: "var(--b-rad-lg)" }}
              >
                $ no workflow definitions found
              </div>
            )}

          {/* List — hairline cards, clay accent bar on hover */}
          {!isError && definitionCount > 0 && (
            <div className="space-y-[3px]">
              <div className="flex items-center gap-3 px-3 pb-1 font-mono text-[9px] uppercase tracking-[1px] text-b-text-faint">
                <span className="w-[14px]" aria-hidden="true" />
                <span className="flex-1">Workflow</span>
                <span>Last run</span>
              </div>
              {filtered.map((name) => {
                const latest = latestRunFor(runs, name);
                return (
                  <Link
                    key={name}
                    to={`/workflows/${name}`}
                    data-testid={`workflow-link-${name}`}
                    className="group relative flex items-center gap-3 overflow-hidden border border-b-line bg-b-bg1 px-3 py-[14px] transition-colors hover:bg-b-bg2 focus:outline-none focus:ring-1 focus:ring-b-clay/50"
                    style={{
                      borderRadius: "var(--b-rad-lg)",
                      borderWidth: "var(--b-bw)",
                    }}
                  >
                    {/* clay accent bar — primary/active card pattern */}
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-x-0 top-0 h-[2px] origin-left scale-x-0 bg-b-clay transition-transform group-hover:scale-x-100 group-focus:scale-x-100"
                    />
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
                <div
                  className="border border-dashed border-b-line py-12 text-center font-mono text-[11px] text-b-text-dim"
                  style={{ borderRadius: "var(--b-rad-lg)" }}
                >
                  no workflows match "
                  <span className="text-b-text">{query}</span>"
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
