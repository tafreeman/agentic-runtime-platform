import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { loadLmStudioModel } from "../../api/client";
import type { ModelProbeResponse, ProbedModel } from "../../api/types";
import {
  loadVerifications,
  type ModelVerification,
} from "../../lib/modelVerification";

// PROVIDER BACKENDS section of the model router — the full probed catalog
// grouped by provider, with substring search, per-model badges (tier /
// capability / cloud / running / playground-verified), and a per-model
// "chat" action that deep-links into the playground tab.

const SECTION_LABEL =
  "font-mono text-[9px] uppercase tracking-[1.6px] text-b-text-faint";
const CARD_STYLE = {
  borderWidth: "var(--b-bw)",
  borderRadius: "var(--b-rad-lg)",
} as const;

interface ProbeProviderGroup {
  readonly name: string;
  readonly available: boolean;
  readonly models: ProbedModel[];
}

/** Group models by provider — available (keyed) providers first. */
function groupProbeByProvider(
  models: readonly ProbedModel[],
  availableProviders: readonly string[],
  providerNames: readonly string[] = [],
): ProbeProviderGroup[] {
  const available = new Set(availableProviders);
  const byName = new Map<string, ProbedModel[]>();
  for (const provider of providerNames) {
    if (provider) byName.set(provider, []);
  }
  for (const model of models) {
    const bucket = byName.get(model.provider);
    if (bucket) bucket.push(model);
    else byName.set(model.provider, [model]);
  }
  return Array.from(byName.entries())
    .map(([name, list]) => ({
      name,
      available: available.has(name),
      models: list
        .slice()
        .sort((a, b) => a.tier - b.tier || a.id.localeCompare(b.id)),
    }))
    .sort(
      (a, b) =>
        Number(b.available) - Number(a.available) ||
        b.models.length - a.models.length ||
        a.name.localeCompare(b.name),
    );
}

/** Capability-tier (1–5) accent: T1/T2 blue, T3 amber, T4/T5 clay. */
function probeTierColor(tier: number): string {
  if (tier >= 4) return "rgb(var(--b-clay))";
  if (tier === 3) return "rgb(var(--b-amber))";
  return "rgb(var(--b-blue))";
}

function ProbedModelRow({
  model,
  isDefault,
  verification,
  loadBusy,
  loading,
  onLoadInLmStudio,
  onOpenInPlayground,
}: Readonly<{
  model: ProbedModel;
  isDefault: boolean;
  verification: ModelVerification | null;
  loadBusy: boolean;
  loading: boolean;
  onLoadInLmStudio: (modelId: string) => void;
  onOpenInPlayground: (modelId: string) => void;
}>) {
  const color = probeTierColor(model.tier);
  const canLoad =
    model.provider === "lmstudio" && model.available && !model.running;
  return (
    <div className="flex items-center gap-2.5 border-b border-b-line-soft py-1.5 last:border-b-0">
      <span
        className="flex-none border px-1.5 py-px font-mono text-[8.5px] tracking-[0.3px]"
        style={{ borderColor: color, color, borderRadius: "3px" }}
      >
        T{model.tier}
      </span>
      <span
        title={model.id}
        className="flex-1 truncate text-[11px] text-b-text-mid"
      >
        {model.id}
      </span>
      {model.capabilities
        ?.filter((cap) => cap !== "completion")
        .map((cap) => (
          <span
            key={cap}
            className="flex-none border border-b-line px-1.5 py-px font-mono text-[8px] uppercase tracking-[0.3px] text-b-text-dim"
            style={{ borderRadius: "3px" }}
          >
            {cap}
          </span>
        ))}
      {model.cloud && (
        <span
          className="flex-none border px-1.5 py-px font-mono text-[8.5px] tracking-[0.3px]"
          style={{
            borderColor: "rgb(var(--b-purple))",
            color: "rgb(var(--b-purple))",
            borderRadius: "3px",
          }}
        >
          cloud
        </span>
      )}
      {model.running && (
        <span
          className="flex flex-none items-center gap-1 font-mono text-[9px] text-b-green"
          title="loaded in memory"
        >
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: "rgb(var(--b-green))" }}
          />
          running
        </span>
      )}
      {isDefault && (
        <span className="flex-none font-mono text-[9px] text-b-clay">
          default
        </span>
      )}
      {!model.available && (
        <span className="flex-none font-mono text-[9px] text-b-text-dim">
          no keys
        </span>
      )}
      {verification?.status === "ok" && (
        <span
          className="flex-none font-mono text-[9px] text-b-text-dim"
          title={`playground-verified ${verification.at}`}
        >
          ✓ ok
        </span>
      )}
      {verification?.status === "error" && (
        <span
          className="flex-none font-mono text-[9px] text-b-text-dim"
          title={verification.message ?? `playground probe failed ${verification.at}`}
        >
          ✗ failed
        </span>
      )}
      {canLoad && (
        <button
          type="button"
          aria-label={`Load ${model.id} in LM Studio`}
          aria-busy={loading}
          disabled={loadBusy}
          onClick={() => onLoadInLmStudio(model.id)}
          className="flex-none border border-b-clay px-1.5 py-px font-mono text-[9px] text-b-clay transition-colors hover:bg-b-clay/10 disabled:cursor-wait disabled:opacity-50"
          style={{ borderRadius: "3px" }}
        >
          {loading ? "loading…" : "load"}
        </button>
      )}
      <button
        type="button"
        aria-label={`Open ${model.id} in playground`}
        data-testid={`open-in-playground-${model.id}`}
        onClick={() => onOpenInPlayground(model.id)}
        className="flex-none border border-b-line px-1.5 py-px font-mono text-[9px] text-b-text-dim transition-colors hover:border-b-clay hover:text-b-clay"
        style={{ borderRadius: "3px" }}
      >
        chat
      </button>
    </div>
  );
}

interface ProviderProbeListProps {
  probe: ModelProbeResponse | undefined;
  probing: boolean;
  probeError: Error | null;
  /** Deep-link a model into the playground tab (?tab=playground&model=…). */
  onOpenInPlayground: (modelId: string) => void;
}

export default function ProviderProbeList({
  probe,
  probing,
  probeError,
  onOpenInPlayground,
}: Readonly<ProviderProbeListProps>) {
  const queryClient = useQueryClient();
  const [openProvider, setOpenProvider] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  // Verified-outcome registry, read once per mount — the finder tab unmounts
  // on a tab switch, so playground results are fresh whenever it returns.
  const [verifications] = useState<Readonly<Record<string, ModelVerification>>>(
    () => loadVerifications(),
  );
  const loadMutation = useMutation({
    mutationFn: (modelId: string) => loadLmStudioModel(modelId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["model-probe"] });
    },
  });

  const beginLmStudioLoad = (modelId: string) => {
    loadMutation.reset();
    loadMutation.mutate(modelId);
  };

  const term = search.trim().toLowerCase();
  const searchActive = term !== "";
  const totalCount = probe?.models.length ?? 0;

  const filteredModels = useMemo(() => {
    const all = probe?.models ?? [];
    if (term === "") return all;
    return all.filter(
      (model) =>
        model.id.toLowerCase().includes(term) ||
        model.provider.toLowerCase().includes(term),
    );
  }, [probe, term]);

  const allProviderNames = useMemo(
    () =>
      Array.from(
        new Set([
          ...(probe?.available_providers ?? []),
          ...(probe?.unavailable_providers ?? []),
          ...(probe?.models.map((model) => model.provider) ?? []),
        ]),
      ),
    [probe],
  );

  const allProviderGroups = useMemo(
    () =>
      groupProbeByProvider(
        probe?.models ?? [],
        probe?.available_providers ?? [],
        allProviderNames,
      ),
    [allProviderNames, probe],
  );

  const matchingProviderNames = useMemo(
    () =>
      searchActive
        ? allProviderNames.filter((provider) => provider.toLowerCase().includes(term))
        : allProviderNames,
    [allProviderNames, searchActive, term],
  );

  const providerGroups = useMemo(
    () =>
      groupProbeByProvider(
        filteredModels,
        probe?.available_providers ?? [],
        matchingProviderNames,
      ),
    [filteredModels, matchingProviderNames, probe],
  );

  const placeholderMode = probe?.no_llm_mode ?? false;

  return (
    <div>
      <div
        className={`${SECTION_LABEL} mb-3 flex flex-wrap items-center gap-x-2 gap-y-1`}
      >
        <span>PROVIDER BACKENDS · PROBE</span>
        {probe && (
          <>
            {/* "keyed" is deliberate copy: this is env-key detection, not a
                liveness check — the playground is the real prober. */}
            <span
              className="text-b-text-dim"
              title="providers with credentials configured — not a liveness check"
            >
              {probe.models.length} models · {probe.available_providers.length}{" "}
              providers keyed
            </span>
            <span
              data-testid="probe-mode"
              className="border px-1.5 py-px text-[8.5px] tracking-[0.3px]"
              style={{
                borderRadius: "var(--b-rad-sm)",
                color: probe.no_llm_mode
                  ? "rgb(var(--b-amber))"
                  : "rgb(var(--b-green))",
                borderColor: probe.no_llm_mode
                  ? "rgb(var(--b-amber))"
                  : "rgb(var(--b-green))",
              }}
            >
              {probe.no_llm_mode ? "no-LLM mode" : "LLM mode"}
            </span>
          </>
        )}
      </div>

      {probeError && (
        <div
          role="alert"
          className="mb-3 border-b-red/40 bg-b-bg1 p-4 font-mono text-[12px] text-b-red"
          style={CARD_STYLE}
        >
          probe failed: {probeError.message}
        </div>
      )}

      {loadMutation.error && (
        <div
          role="alert"
          className="mb-3 border-b-red/40 bg-b-bg1 p-4 font-mono text-[12px] text-b-red"
          style={CARD_STYLE}
        >
          LM Studio load failed: {loadMutation.error.message}
        </div>
      )}

      {probe && (
        <div
          data-testid="provider-card-grid"
          className="mb-4 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2.5"
        >
          {allProviderGroups.map((provider) => {
            const statusColor = placeholderMode
              ? "rgb(var(--b-amber))"
              : !provider.available
                ? "rgb(var(--b-red))"
                : provider.models.length === 0
                  ? "rgb(var(--b-amber))"
                  : "rgb(var(--b-green))";
            const statusText = placeholderMode
              ? "placeholder"
              : !provider.available
                ? "needs key"
                : provider.models.length === 0
                  ? "not detected"
                  : "configured";
            return (
              <article
                key={provider.name}
                data-testid={`provider-card-${provider.name}`}
                className="relative min-w-0 overflow-hidden border border-b-line bg-b-bg1 p-3.5"
                style={CARD_STYLE}
              >
                <span
                  aria-hidden="true"
                  className="absolute inset-y-0 left-0 w-[2px]"
                  style={{ backgroundColor: statusColor }}
                />
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate font-mono text-[12px] font-semibold text-b-text">
                      {provider.name}
                    </h3>
                    <p className="mt-1 font-mono text-[9px] text-b-text-dim">
                      {provider.models.length} detected model
                      {provider.models.length === 1 ? "" : "s"}
                    </p>
                  </div>
                  <span
                    className="mt-0.5 h-2 w-2 flex-none rounded-full"
                    style={{ backgroundColor: statusColor }}
                    title={statusText}
                  />
                </div>
                <div
                  className="mt-3 font-mono text-[8.5px] uppercase tracking-[0.8px]"
                  style={{ color: statusColor }}
                >
                  {statusText}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {probe && (
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <input
            type="search"
            data-testid="catalog-search"
            aria-label="Search catalog models"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="filter models by id or provider…"
            className="w-full max-w-[340px] border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text placeholder:text-b-text-faint focus:border-b-clay focus:outline-none"
            style={{ borderRadius: "var(--b-rad-sm)" }}
          />
          <span
            data-testid="catalog-search-count"
            className="font-mono text-[10px] text-b-text-dim"
          >
            {filteredModels.length} / {totalCount} models
          </span>
        </div>
      )}

      <div
        className="overflow-hidden border-b-line bg-b-bg1"
        style={CARD_STYLE}
      >
        {!probe && probing && (
          <div className="space-y-px">
            {["sk-prov-0", "sk-prov-1", "sk-prov-2"].map((k) => (
              <div key={k} className="px-4 py-3">
                <div className="h-4 w-full animate-pulse rounded bg-b-bg3" />
              </div>
            ))}
          </div>
        )}
        {probe && probe.available_providers.length === 0 && !searchActive && (
          <div className="p-6 font-mono text-[12px] text-b-text-dim">
            no providers have credentials configured
          </div>
        )}
        {probe && searchActive && providerGroups.length === 0 && (
          <div className="p-6 font-mono text-[12px] text-b-text-dim">
            no models match &ldquo;{search.trim()}&rdquo;
          </div>
        )}
        {providerGroups.map((provider, index) => {
          // An active search auto-expands every matching provider so results
          // are visible without clicking through the accordion.
          const isOpen = searchActive || openProvider === provider.name;
          // In no-LLM mode every tier is routed to the placeholder model,
          // so a green "ready"/key-present status is misleading — show a
          // neutral/amber "placeholder" instead.
          const statusColor = placeholderMode
            ? "rgb(var(--b-amber))"
            : !provider.available
              ? "rgb(var(--b-red))"
              : provider.models.length === 0
                ? "rgb(var(--b-amber))"
                : "rgb(var(--b-green))";
          const statusText = placeholderMode
            ? "placeholder"
            : !provider.available
              ? "no keys"
              : provider.models.length === 0
                ? "not detected"
                : "ready";
          return (
            <div
              key={provider.name}
              className={index > 0 ? "border-t border-b-line-soft" : ""}
            >
              <button
                type="button"
                onClick={() =>
                  setOpenProvider(isOpen && !searchActive ? null : provider.name)
                }
                aria-expanded={isOpen}
                className="flex w-full items-center gap-3 px-[18px] py-[11px] text-left font-mono text-[11px] transition-colors hover:bg-b-bg2/50 focus:outline-none focus:ring-1 focus:ring-inset focus:ring-b-clay/50"
              >
                <span className="w-2.5 flex-none text-[10px] text-b-text-faint">
                  {isOpen ? "▾" : "▸"}
                </span>
                <span className="flex-1 font-medium text-b-text">
                  {provider.name}
                </span>
                <span
                  className="flex items-center gap-1.5 text-[10.5px]"
                  style={{ color: statusColor }}
                >
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: statusColor }}
                  />
                  {statusText}
                </span>
                <span className="w-20 flex-none text-right text-[9.5px] text-b-text-dim">
                  {provider.models.length} model
                  {provider.models.length === 1 ? "" : "s"}
                </span>
              </button>
              {isOpen && (
                <div className="bg-b-bg0 py-1 pl-10 pr-[18px]">
                  {provider.models.map((model) => {
                    // Suppress the "default" marker in no-LLM mode: the
                    // tier defaults are bypassed for the placeholder model.
                    const isDefault =
                      probe && !probe.no_llm_mode
                        ? Object.values(probe.tier_defaults).includes(model.id)
                        : false;
                    return (
                      <ProbedModelRow
                        key={model.id}
                        model={model}
                        isDefault={isDefault}
                        verification={verifications[model.id] ?? null}
                        loadBusy={loadMutation.isPending}
                        loading={
                          loadMutation.isPending &&
                          loadMutation.variables === model.id
                        }
                        onLoadInLmStudio={beginLmStudioLoad}
                        onOpenInPlayground={onOpenInPlayground}
                      />
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
