import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useMemo, useState } from "react";
import { loadLmStudioModel } from "../../api/client";
import type { ModelProbeResponse, ProbedModel } from "../../api/types";
import { useApiAvailability } from "../../hooks/useApiAvailability";
import { describeApiError } from "../../lib/apiErrors";
import {
  loadVerifications,
  type ModelVerification,
} from "../../lib/modelVerification";
import { apiErrorText } from "../common/apiErrorText";

// PROVIDER BACKENDS section of the model router — the full probed catalog
// grouped by provider, with substring search, per-model badges (tier /
// capability / cloud / running / playground-verified), and a per-model
// "chat" action that deep-links into the playground tab.

const SECTION_LABEL =
  "font-mono text-micro uppercase tracking-[1.2px] text-el-muted";
/** Small tag (tier / capability / cloud): 2px radius, 11px floor. */
const TAG = "flex-none rounded-sm border px-1.5 py-px font-mono text-micro";
/**
 * Dense row action: 28px visual, >=36px hit area via a centred ::after
 * (rows are min-h-10, so neighbouring rows' targets never overlap).
 */
const ROW_ACTION =
  "relative flex-none rounded-sm border border-el-divider px-2 py-0.5 font-mono text-micro text-el-secondary transition-colors hover:bg-el-hover hover:text-el-ink focus-ring after:absolute after:top-1/2 after:left-1/2 after:size-full after:min-h-9 after:min-w-9 after:-translate-x-1/2 after:-translate-y-1/2 disabled:opacity-50";

type ProbeStatusTone = "success" | "warning" | "danger";

/** Provider status → token classes (status text always accompanies color). */
const STATUS_TEXT_CLASS: Record<ProbeStatusTone, string> = {
  success: "text-el-success",
  warning: "text-el-warning",
  danger: "text-el-danger",
};
const STATUS_FILL_CLASS: Record<ProbeStatusTone, string> = {
  success: "bg-el-success",
  warning: "bg-el-warning",
  danger: "bg-el-danger",
};

/**
 * Placeholder mode or no models → warning; missing credentials → danger;
 * keyed with models → success.
 */
function providerStatusTone(
  placeholderMode: boolean,
  group: ProbeProviderGroup,
): ProbeStatusTone {
  if (placeholderMode) return "warning";
  if (!group.available) return "danger";
  if (group.models.length === 0) return "warning";
  return "success";
}

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

/** Capability-tier mark: T0–T2 tier-low, T3 tier-mid, T4/T5 tier-high. */
function probeTierClass(tier: number): string {
  if (tier >= 4) return "border-el-tier-high text-el-tier-high";
  if (tier === 3) return "border-el-tier-mid text-el-tier-mid";
  return "border-el-tier-low text-el-tier-low";
}

function ProbedModelRow({
  model,
  isDefault,
  verification,
  loadBusy,
  loading,
  apiDown,
  apiDownHintId,
  onLoadInLmStudio,
  onOpenInPlayground,
}: Readonly<{
  model: ProbedModel;
  isDefault: boolean;
  verification: ModelVerification | null;
  loadBusy: boolean;
  loading: boolean;
  /** API unreachable: loading a model is an API mutation, so it is disabled. */
  apiDown: boolean;
  /** id of the visible "API unreachable" reason the disabled load refers to. */
  apiDownHintId: string;
  onLoadInLmStudio: (modelId: string) => void;
  onOpenInPlayground: (modelId: string) => void;
}>) {
  const canLoad =
    model.provider === "lmstudio" && model.available && !model.running;
  return (
    <div className="flex min-h-10 items-center gap-2.5 border-b border-el-divider-soft py-1 last:border-b-0">
      <span className={`${TAG} ${probeTierClass(model.tier)}`}>
        T{model.tier}
      </span>
      <span
        title={model.id}
        className="flex-1 truncate text-xs text-el-secondary"
      >
        {model.id}
      </span>
      {model.capabilities
        ?.filter((cap) => cap !== "completion")
        .map((cap) => (
          <span
            key={cap}
            className={`${TAG} border-el-divider uppercase tracking-[0.3px] text-el-muted`}
          >
            {cap}
          </span>
        ))}
      {model.cloud && (
        <span className={`${TAG} border-el-plum text-el-plum`}>cloud</span>
      )}
      {model.running && (
        <span
          className="flex flex-none items-center gap-1 font-mono text-micro text-el-success"
          title="loaded in memory"
        >
          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-el-success" />
          running
        </span>
      )}
      {isDefault && (
        <span className="flex-none font-mono text-micro text-el-accent-strong">
          default
        </span>
      )}
      {!model.available && (
        <span className="flex-none font-mono text-micro text-el-danger">
          no keys
        </span>
      )}
      {verification?.status === "ok" && (
        <span
          className="flex-none font-mono text-micro text-el-success"
          title={`playground-verified ${verification.at}`}
        >
          ✓ ok
        </span>
      )}
      {verification?.status === "error" && (
        <span
          className="flex-none font-mono text-micro text-el-danger"
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
          aria-describedby={apiDown ? apiDownHintId : undefined}
          disabled={loadBusy || apiDown}
          onClick={() => onLoadInLmStudio(model.id)}
          className={`${ROW_ACTION} ${loadBusy ? "disabled:cursor-wait" : "disabled:cursor-not-allowed"}`}
        >
          {loading ? "loading…" : "load"}
        </button>
      )}
      <button
        type="button"
        aria-label={`Open ${model.id} in playground`}
        data-testid={`open-in-playground-${model.id}`}
        onClick={() => onOpenInPlayground(model.id)}
        className={ROW_ACTION}
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
  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const apiDownHintId = useId();
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
  // An unreachable API is already announced by the shell banner, so a failed
  // probe then gets a quiet note (the last probe stays visible) instead of a
  // second alert.
  const probeErrorInfo = probeError ? describeApiError(probeError) : null;

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
              className="text-el-muted"
              title="providers with credentials configured — not a liveness check"
            >
              {probe.models.length} models · {probe.available_providers.length}{" "}
              providers keyed
            </span>
            <span
              data-testid="probe-mode"
              className={`rounded-sm border px-1.5 py-px tracking-[0.3px] ${
                probe.no_llm_mode
                  ? "border-el-warning bg-el-warning-soft text-el-warning"
                  : "border-el-success bg-el-success-soft text-el-success"
              }`}
            >
              {probe.no_llm_mode ? "no-LLM mode" : "LLM mode"}
            </span>
          </>
        )}
      </div>

      {probeError && probeErrorInfo?.unreachable && (
        <p
          data-testid="probe-error-note"
          className="mb-3 font-mono text-micro text-el-muted"
        >
          probe unavailable — {probeErrorInfo.summary}
          {probe ? " Showing the last probe." : ""}
        </p>
      )}
      {probeError && !probeErrorInfo?.unreachable && (
        <div
          role="alert"
          className="mb-3 rounded-lg border border-el-danger/40 bg-el-danger-soft p-4 font-mono text-xs text-el-danger"
        >
          probe failed: {apiErrorText(probeError)}
        </div>
      )}

      {loadMutation.error && (
        <div
          role="alert"
          className="mb-3 rounded-lg border border-el-danger/40 bg-el-danger-soft p-4 font-mono text-xs text-el-danger"
        >
          LM Studio load failed: {apiErrorText(loadMutation.error)}
        </div>
      )}

      {probe && apiDown && (
        <p id={apiDownHintId} className="mb-3 font-mono text-micro text-el-muted">
          Loading models is unavailable: {apiDownReason}
        </p>
      )}

      {probe && (
        <div
          data-testid="provider-card-grid"
          className="mb-4 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2.5"
        >
          {allProviderGroups.map((provider) => {
            const tone = providerStatusTone(placeholderMode, provider);
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
                className="relative min-w-0 overflow-hidden rounded-lg border border-el-divider bg-el-surface p-3.5"
              >
                <span
                  aria-hidden="true"
                  className={`absolute inset-y-0 left-0 w-[2px] ${STATUS_FILL_CLASS[tone]}`}
                />
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate font-mono text-xs font-semibold text-el-ink">
                      {provider.name}
                    </h3>
                    <p className="mt-1 font-mono text-micro text-el-muted">
                      {provider.models.length} detected model
                      {provider.models.length === 1 ? "" : "s"}
                    </p>
                  </div>
                  <span
                    aria-hidden="true"
                    className={`mt-0.5 h-2 w-2 flex-none rounded-full ${STATUS_FILL_CLASS[tone]}`}
                    title={statusText}
                  />
                </div>
                <div
                  className={`mt-3 font-mono text-micro uppercase tracking-[0.8px] ${STATUS_TEXT_CLASS[tone]}`}
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
            className="h-10 w-full max-w-[340px] rounded-md border border-el-control-border bg-el-raised px-2.5 font-mono text-xs text-el-ink placeholder:text-el-faint focus-ring focus-visible:border-el-focus"
          />
          <span
            data-testid="catalog-search-count"
            className="font-mono text-micro text-el-muted"
          >
            {filteredModels.length} / {totalCount} models
          </span>
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-el-divider bg-el-surface">
        {!probe && probing && (
          <div className="space-y-px">
            {["sk-prov-0", "sk-prov-1", "sk-prov-2"].map((k) => (
              <div key={k} className="px-4 py-3">
                <div className="h-4 w-full animate-pulse rounded-sm bg-el-hover" />
              </div>
            ))}
          </div>
        )}
        {probe && probe.available_providers.length === 0 && !searchActive && (
          <div className="p-6 font-mono text-xs text-el-muted">
            no providers have credentials configured
          </div>
        )}
        {probe && searchActive && providerGroups.length === 0 && (
          <div className="p-6 font-mono text-xs text-el-muted">
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
          const tone = providerStatusTone(placeholderMode, provider);
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
              className={index > 0 ? "border-t border-el-divider-soft" : ""}
            >
              {/* Inset ring: the list container clips overflow. */}
              <button
                type="button"
                data-testid={`provider-row-${provider.name}`}
                onClick={() =>
                  setOpenProvider(isOpen && !searchActive ? null : provider.name)
                }
                aria-expanded={isOpen}
                className="flex min-h-11 w-full items-center gap-3 px-4 py-2.5 text-left font-mono text-xs transition-colors hover:bg-el-subtle focus-ring-inset"
              >
                <span aria-hidden="true" className="w-2.5 flex-none text-micro text-el-muted">
                  {isOpen ? "▾" : "▸"}
                </span>
                <span className="flex-1 font-medium text-el-ink">
                  {provider.name}
                </span>
                <span
                  className={`flex items-center gap-1.5 text-micro ${STATUS_TEXT_CLASS[tone]}`}
                >
                  <span
                    aria-hidden="true"
                    className={`h-1.5 w-1.5 rounded-full ${STATUS_FILL_CLASS[tone]}`}
                  />
                  {statusText}
                </span>
                <span className="w-20 flex-none text-right text-micro text-el-muted">
                  {provider.models.length} model
                  {provider.models.length === 1 ? "" : "s"}
                </span>
              </button>
              {isOpen && (
                <div className="bg-el-canvas py-1 pl-10 pr-4">
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
                        apiDown={apiDown}
                        apiDownHintId={apiDownHintId}
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
