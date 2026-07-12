import { useMemo, useState, type ReactNode } from "react";
import { Cpu, Gauge, HardDrive, SlidersHorizontal } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import BTopBar from "../components/layout/BTopBar";
import ChatPlaygroundPanel from "../components/models/ChatPlaygroundPanel";
import { getModelRecommendations, probeModels } from "../api/client";
import type {
  ModelCandidate,
  ModelProbeResponse,
  ModelSortField,
  ModelTaskCategory,
  ProbedModel,
} from "../api/types";

const CATEGORIES: Array<ModelTaskCategory | "all"> = [
  "all",
  "general",
  "swe",
  "biomed",
  "physics",
  "math",
  "vision",
];

const SORTS: ModelSortField[] = [
  "downloads",
  "release_date",
  "likes",
  "forks",
  "fit",
];

function compactNumber(value: number): string {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

// ---------------------------------------------------------------------------
// Capability tiers — derived purely from each candidate's fit score so the
// section reflects real recommendation data (no mutation backend exists for
// hand-assigning models to tiers).
// ---------------------------------------------------------------------------

interface CapabilityTier {
  readonly key: string;
  readonly letter: string;
  readonly label: string;
  readonly desc: string;
  readonly color: string;
  readonly match: (model: ModelCandidate) => boolean;
}

const CAPABILITY_TIERS: readonly CapabilityTier[] = [
  {
    key: "s",
    letter: "S",
    label: "headroom",
    desc: "fits with budget to spare",
    color: "rgb(var(--b-green))",
    match: (m) => m.runnable && m.fit_score >= 80,
  },
  {
    key: "a",
    letter: "A",
    label: "comfortable",
    desc: "runs on this machine",
    color: "rgb(var(--b-blue))",
    match: (m) => m.runnable && m.fit_score >= 60 && m.fit_score < 80,
  },
  {
    key: "b",
    letter: "B",
    label: "workable",
    desc: "runs with trade-offs",
    color: "rgb(var(--b-clay))",
    match: (m) => m.runnable && m.fit_score < 60,
  },
  {
    key: "c",
    letter: "C",
    label: "tight",
    desc: "exceeds detected budget",
    color: "rgb(var(--b-amber))",
    match: (m) => !m.runnable,
  },
];

// Provider backends from the live probe — the full known catalog grouped by
// provider, available (keys present) first.
interface ProbeProviderGroup {
  readonly name: string;
  readonly available: boolean;
  readonly models: ProbedModel[];
}

function groupProbeByProvider(
  probe: ModelProbeResponse | undefined,
): ProbeProviderGroup[] {
  if (!probe) return [];
  const available = new Set(probe.available_providers);
  const byName = new Map<string, ProbedModel[]>();
  for (const model of probe.models) {
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

const SECTION_LABEL =
  "font-mono text-[9px] uppercase tracking-[1.6px] text-b-text-faint";
const CARD_STYLE = {
  borderWidth: "var(--b-bw)",
  borderRadius: "var(--b-rad-lg)",
} as const;
const CHIP_STYLE = {
  borderRadius: "var(--b-rad-sm)",
} as const;

function ProfileStat({
  icon,
  value,
  label,
  loading,
}: Readonly<{
  icon: ReactNode;
  value: ReactNode;
  label: string;
  loading: boolean;
}>) {
  return (
    <div
      className="border-b-line bg-b-bg1 p-[15px]"
      style={{ borderWidth: "var(--b-bw)", borderRadius: "var(--b-rad-lg)" }}
    >
      <div className="flex items-center gap-3">
        {icon}
        <div className="min-w-0">
          {loading ? (
            <div className="h-6 w-16 animate-pulse rounded bg-b-bg3" />
          ) : (
            <div
              className="text-[24px] font-semibold leading-tight tabular-nums text-b-text"
              style={{
                fontFamily: "var(--b-font-heading)",
                letterSpacing: "-0.5px",
              }}
            >
              {value}
            </div>
          )}
          <div className="mt-1.5 font-mono text-[9px] uppercase tracking-[1.2px] text-b-text-faint">
            {label}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Sub-views of the model router page. */
type ModelRouterTab = "finder" | "playground";

function TabButton({
  label,
  active,
  onClick,
  testId,
}: Readonly<{
  label: string;
  active: boolean;
  onClick: () => void;
  testId?: string;
}>) {
  return (
    <button
      type="button"
      data-testid={testId}
      aria-pressed={active}
      onClick={onClick}
      className={`-mb-px border-b-2 px-1 pb-2.5 pt-3 font-mono text-[10px] uppercase tracking-[1.6px] transition-colors ${
        active ? "text-b-text" : "text-b-text-dim hover:text-b-text"
      }`}
      style={{
        borderBottomColor: active ? "rgb(var(--b-clay))" : "transparent",
      }}
    >
      {label}
    </button>
  );
}

export default function ModelFinderPage() {
  const [tab, setTab] = useState<ModelRouterTab>("finder");
  const [category, setCategory] = useState<ModelTaskCategory | "all">("all");
  const [sortBy, setSortBy] = useState<ModelSortField>("downloads");
  const [openProvider, setOpenProvider] = useState<string | null>(null);

  const {
    data,
    isLoading,
    isFetching: refreshing,
    error,
    refetch,
  } = useQuery({
    queryKey: ["model-recommendations", category, sortBy],
    queryFn: () => getModelRecommendations(category, sortBy),
  });

  // Live provider probe — re-runs the same availability check as server startup
  // and loads the full known model catalog. Driven by "rescan".
  const {
    data: probe,
    isFetching: probing,
    error: probeError,
    refetch: refetchProbe,
  } = useQuery({
    queryKey: ["model-probe"],
    queryFn: probeModels,
  });

  const acceleratorText = useMemo(() => {
    const accelerators = data?.profile.accelerators ?? [];
    if (accelerators.length === 0) return "CPU only";
    return accelerators
      .map((item) =>
        `${item.kind.toUpperCase()} ${item.name}${
          item.memory_gb ? ` · ${item.memory_gb}GB` : ""
        }`,
      )
      .join(" / ");
  }, [data]);

  const models = data?.models ?? [];
  const probeProviders = useMemo(() => groupProbeByProvider(probe), [probe]);

  // Rescan refreshes both the local hardware fit and the live provider probe.
  const rescan = () => {
    void refetch();
    void refetchProbe();
  };

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="model router">
        <button
          type="button"
          onClick={rescan}
          disabled={probing || refreshing}
          aria-busy={probing || refreshing}
          aria-label="Rescan providers"
          className="btn-ghost"
        >
          <SlidersHorizontal
            className={`h-3 w-3 ${probing || refreshing ? "animate-spin" : ""}`}
          />{" "}
          rescan
        </button>
      </BTopBar>

      {/* Sub-view tabs: catalog/fit finder vs direct chat playground. */}
      <div className="flex items-center gap-4 border-b border-b-line px-6">
        <TabButton
          label="finder"
          active={tab === "finder"}
          onClick={() => setTab("finder")}
        />
        <TabButton
          label="playground"
          active={tab === "playground"}
          onClick={() => setTab("playground")}
          testId="chat-playground-tab"
        />
      </div>

      <div className="h-full overflow-y-auto p-6">
        {tab === "playground" && (
          <ChatPlaygroundPanel probe={probe} probeLoading={probing} />
        )}
        {tab === "finder" && (
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1
                className="text-[24px] font-semibold text-b-text"
                style={{ fontFamily: "var(--b-font-heading)", letterSpacing: "-0.5px" }}
              >
                local model fit finder
              </h1>
              <p className="mt-1 max-w-3xl font-mono text-[11px] leading-5 text-b-text-dim">
                Profiles RAM, CPU, GPU/NPU hints, estimated Cinebench-class CPU
                score, and estimated 7B Q4 throughput, then ranks local LLMs by
                your selected metric with popularity/newness/forks tie-breakers.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <select
                value={category}
                onChange={(event) =>
                  setCategory(event.target.value as ModelTaskCategory | "all")
                }
                className="border border-b-line bg-b-bg1 px-2 py-1 font-mono text-[11px] text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
                style={CHIP_STYLE}
                aria-label="Model category"
              >
                {CATEGORIES.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
              <select
                value={sortBy}
                onChange={(event) => setSortBy(event.target.value as ModelSortField)}
                className="border border-b-line bg-b-bg1 px-2 py-1 font-mono text-[11px] text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
                style={CHIP_STYLE}
                aria-label="Sort models by"
              >
                {SORTS.map((item) => (
                  <option key={item} value={item}>
                    sort: {item.replace("_", " ")}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="border-b-red/40 bg-b-bg1 p-4 font-mono text-[12px] text-b-red"
              style={CARD_STYLE}
            >
              failed to load model recommendations: {error.message}
            </div>
          )}

          {/* ─── SYSTEM PROFILE ─── */}
          <div>
            <div className={`${SECTION_LABEL} mb-3`}>
              SYSTEM PROFILE · DISCOVERY ·{" "}
              <span className="text-b-text-dim">
                tier {data?.profile.performance_tier ?? "—"}
              </span>
            </div>
            <div className="grid gap-3.5 lg:grid-cols-4">
              <ProfileStat
                loading={isLoading}
                icon={<HardDrive className="h-5 w-5 flex-none text-b-clay" />}
                value={`${data?.profile.ram_gb ?? 0} GB`}
                label="usable memory budget"
              />
              <ProfileStat
                loading={isLoading}
                icon={<Cpu className="h-5 w-5 flex-none text-b-blue" />}
                value={`${data?.profile.cpu_cores_logical ?? 0} threads`}
                label={data?.profile.cpu_name ?? "detecting CPU"}
              />
              <ProfileStat
                loading={isLoading}
                icon={<Gauge className="h-5 w-5 flex-none text-b-green" />}
                value={compactNumber(
                  data?.profile.estimated_cinebench_r23_multi ?? 0,
                )}
                label="est. Cinebench R23 multi"
              />
              <ProfileStat
                loading={isLoading}
                icon={
                  <SlidersHorizontal className="h-5 w-5 flex-none text-b-purple" />
                }
                value={
                  <span className="font-mono text-[12px] font-normal leading-snug">
                    {acceleratorText}
                  </span>
                }
                label="accelerators"
              />
            </div>
          </div>

          {/* ─── CAPABILITY TIERS ─── */}
          <div>
            <div className={`${SECTION_LABEL} mb-3`}>
              CAPABILITY TIERS · FIT-WEIGHTED SELECTION
            </div>
            <div className="grid gap-3.5 md:grid-cols-2">
              {CAPABILITY_TIERS.map((tier) => {
                const tierModels = models.filter(tier.match);
                return (
                  <div
                    key={tier.key}
                    className="border-b-line bg-b-bg1 px-[17px] py-[15px]"
                    style={CARD_STYLE}
                  >
                    <div className="flex items-baseline gap-2.5">
                      <span
                        className="text-[14px] font-semibold"
                        style={{
                          fontFamily: "var(--b-font-heading)",
                          color: tier.color,
                        }}
                      >
                        {tier.letter}
                      </span>
                      <span className="text-[11px] text-b-text-mid">
                        {tier.label}
                      </span>
                      <span className="ml-auto font-mono text-[9.5px] text-b-text-faint">
                        {tier.desc}
                      </span>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      {isLoading && (
                        <div className="h-5 w-40 animate-pulse rounded bg-b-bg3" />
                      )}
                      {!isLoading && tierModels.length === 0 && (
                        <span className="font-mono text-[9.5px] text-b-text-faint">
                          no models in this band
                        </span>
                      )}
                      {!isLoading &&
                        tierModels.map((model) => (
                          <a
                            key={model.id}
                            href={model.url}
                            target="_blank"
                            rel="noreferrer"
                            title={`${model.name} · ${model.fit_score}% fit`}
                            className="inline-flex max-w-[200px] items-center gap-1.5 border px-[9px] py-1 font-mono text-[10px] text-b-text-mid transition-colors hover:text-b-clay"
                            style={{
                              ...CHIP_STYLE,
                              borderColor: tier.color,
                              backgroundColor: "rgb(var(--b-bg2))",
                            }}
                          >
                            <span className="truncate">{model.name}</span>
                            <span className="flex-none text-b-text-dim">
                              {model.fit_score}%
                            </span>
                          </a>
                        ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* ─── PROVIDER BACKENDS · live probe ─── */}
          <div>
            <div
              className={`${SECTION_LABEL} mb-3 flex flex-wrap items-center gap-x-2 gap-y-1`}
            >
              <span>PROVIDER BACKENDS · PROBE</span>
              {probe && (
                <>
                  <span className="text-b-text-dim">
                    {probe.models.length} models ·{" "}
                    {probe.available_providers.length} live
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
              {probe && probe.available_providers.length === 0 && (
                <div className="p-6 font-mono text-[12px] text-b-text-dim">
                  no providers have credentials configured
                </div>
              )}
              {probeProviders.map((provider, index) => {
                const isOpen = openProvider === provider.name;
                // In no-LLM mode every tier is routed to the placeholder model,
                // so a green "ready"/key-present status is misleading — show a
                // neutral/amber "placeholder" instead.
                const placeholderMode = probe?.no_llm_mode ?? false;
                const statusColor = placeholderMode
                  ? "rgb(var(--b-amber))"
                  : provider.available
                    ? "rgb(var(--b-green))"
                    : "rgb(var(--b-red))";
                const statusText = placeholderMode
                  ? "placeholder"
                  : provider.available
                    ? "ready"
                    : "no keys";
                return (
                  <div
                    key={provider.name}
                    className={index > 0 ? "border-t border-b-line-soft" : ""}
                  >
                    <button
                      type="button"
                      onClick={() =>
                        setOpenProvider(isOpen ? null : provider.name)
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
                          const color = probeTierColor(model.tier);
                          // Suppress the "default" marker in no-LLM mode: the
                          // tier defaults are bypassed for the placeholder model.
                          const isDefault =
                            probe && !probe.no_llm_mode
                              ? Object.values(probe.tier_defaults).includes(
                                  model.id,
                                )
                              : false;
                          return (
                            <div
                              key={model.id}
                              className="flex items-center gap-2.5 border-b border-b-line-soft py-1.5 last:border-b-0"
                            >
                              <span
                                className="flex-none border px-1.5 py-px font-mono text-[8.5px] tracking-[0.3px]"
                                style={{
                                  borderColor: color,
                                  color,
                                  borderRadius: "3px",
                                }}
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
                                    style={{
                                      backgroundColor: "rgb(var(--b-green))",
                                    }}
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
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {data?.profile.notes.map((note) => (
            <p key={note} className="font-mono text-[10px] text-b-text-dim">
              note: {note}
            </p>
          ))}
        </div>
        )}
      </div>
    </div>
  );
}
