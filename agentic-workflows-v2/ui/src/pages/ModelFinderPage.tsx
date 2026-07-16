import { useMemo, useState, type ReactNode } from "react";
import { Cpu, Gauge, HardDrive, SlidersHorizontal } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import BTopBar from "../components/layout/BTopBar";
import ChatPlaygroundPanel from "../components/models/ChatPlaygroundPanel";
import HardwareOverrideForm from "../components/models/HardwareOverrideForm";
import ProviderProbeList from "../components/models/ProviderProbeList";
import ModelPacksPanel from "../components/models/ModelPacksPanel";
import ProviderPanel from "../components/settings/ProviderPanel";
import TierBoard from "../components/settings/TierBoard";
import { getModelRecommendations, probeModels } from "../api/client";
import type {
  ModelCandidate,
  ModelSortField,
  ModelTaskCategory,
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
type ModelRouterTab =
  | "finder"
  | "providers"
  | "tiers"
  | "packs"
  | "playground"
  | "hardware";

const MODEL_TABS: readonly ModelRouterTab[] = [
  "finder",
  "providers",
  "tiers",
  "packs",
  "playground",
  "hardware",
];

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
      role="tab"
      data-testid={testId}
      aria-selected={active}
      onClick={onClick}
      className={`-mb-px whitespace-nowrap border-b-2 px-1 pb-3 pt-4 text-[13px] font-semibold transition-colors ${
        active ? "text-el-ink" : "text-el-muted hover:text-el-ink"
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
  // URL-driven tab state (contract: /models?tab=playground&model=<id>) so the
  // playground is deep-linkable from anywhere in the console.
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab") as ModelRouterTab | null;
  const tab: ModelRouterTab =
    requestedTab && MODEL_TABS.includes(requestedTab) ? requestedTab : "finder";
  const initialPlaygroundModel = searchParams.get("model") ?? "";

  const [category, setCategory] = useState<ModelTaskCategory | "all">("all");
  const [sortBy, setSortBy] = useState<ModelSortField>("downloads");
  const [specsOpen, setSpecsOpen] = useState(false);

  const openTab = (next: ModelRouterTab) => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      if (next === "finder") {
        params.delete("tab");
        params.delete("model");
      } else {
        params.set("tab", next);
        if (next !== "playground") params.delete("model");
      }
      return params;
    });
  };

  const openModelInPlayground = (modelId: string) => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.set("tab", "playground");
      params.set("model", modelId);
      return params;
    });
  };

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

  const models = useMemo(() => data?.models ?? [], [data]);

  // Fit bands: keep the full cards only where models exist — on capable
  // hardware the scorer is bimodal (everything lands in S), so empty A/B/C
  // bands collapse to one compact line each instead of noisy empty boxes.
  const tierBuckets = useMemo(
    () =>
      CAPABILITY_TIERS.map((tier) => ({
        tier,
        tierModels: models.filter(tier.match),
      })),
    [models],
  );
  const populatedBuckets = tierBuckets.filter((b) => b.tierModels.length > 0);
  const emptyBuckets = tierBuckets.filter((b) => b.tierModels.length === 0);
  const runnableCount = models.filter((m) => m.runnable).length;
  const headroomCount =
    tierBuckets.find((b) => b.tier.key === "s")?.tierModels.length ?? 0;
  const allFitWithHeadroom =
    !isLoading && runnableCount > 0 && headroomCount === runnableCount;

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

      <div className="flex items-center gap-6 overflow-x-auto border-b border-el-divider px-5 sm:px-8 lg:px-10" role="tablist" aria-label="Model router sections">
        <TabButton
          label="Models"
          active={tab === "finder"}
          onClick={() => openTab("finder")}
        />
        <TabButton label="Providers" active={tab === "providers"} onClick={() => openTab("providers")} />
        <TabButton label="Tiers" active={tab === "tiers"} onClick={() => openTab("tiers")} />
        <TabButton label="Packs" active={tab === "packs"} onClick={() => openTab("packs")} />
        <TabButton
          label="Playground"
          active={tab === "playground"}
          onClick={() => openTab("playground")}
          testId="chat-playground-tab"
        />
        <TabButton label="Hardware" active={tab === "hardware"} onClick={() => openTab("hardware")} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-8 lg:p-10">
        {tab === "providers" && <ProviderPanel />}
        {tab === "tiers" && <TierBoard />}
        {tab === "packs" && <ModelPacksPanel />}
        {tab === "playground" && (
          <ChatPlaygroundPanel
            probe={probe}
            probeLoading={probing}
            probeError={probeError ?? null}
            initialModel={initialPlaygroundModel}
          />
        )}
        {tab === "hardware" && (
          <div className="mx-auto max-w-5xl space-y-8">
            <div className="max-w-3xl">
              <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-el-accent-strong">Local inference profile</div>
              <h1 className="font-display text-[36px] font-medium leading-tight text-el-ink">Hardware</h1>
              <p className="mt-3 text-[14px] leading-6 text-el-muted">Review detected compute and override discovery values used by the local model fit recommendations.</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <ProfileStat loading={isLoading} icon={<HardDrive className="h-5 w-5 text-el-accent-strong" />} value={`${data?.profile.ram_gb ?? 0} GB`} label="usable memory" />
              <ProfileStat loading={isLoading} icon={<Cpu className="h-5 w-5 text-el-info" />} value={`${data?.profile.cpu_cores_logical ?? 0} threads`} label={data?.profile.cpu_name ?? "detecting CPU"} />
              <ProfileStat loading={isLoading} icon={<Gauge className="h-5 w-5 text-el-success" />} value={compactNumber(data?.profile.estimated_cinebench_r23_multi ?? 0)} label="estimated CPU score" />
              <ProfileStat loading={isLoading} icon={<SlidersHorizontal className="h-5 w-5 text-el-warning" />} value={<span className="text-[12px]">{acceleratorText}</span>} label="accelerators" />
            </div>
            <HardwareOverrideForm onClose={() => openTab("finder")} />
          </div>
        )}
        {tab === "finder" && (
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1
                className="text-[24px] font-semibold text-b-text"
                style={{ fontFamily: "var(--b-font-heading)", letterSpacing: "-0.5px" }}
              >
                Model catalog
              </h1>
              <p className="mt-2 max-w-3xl text-[14px] leading-6 text-el-muted">
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
            <div className={`${SECTION_LABEL} mb-3 flex flex-wrap items-center gap-x-3 gap-y-1`}>
              <span>
                SYSTEM PROFILE · DISCOVERY ·{" "}
                <span className="text-b-text-dim">
                  tier {data?.profile.performance_tier ?? "—"}
                </span>
              </span>
              <button
                type="button"
                data-testid="edit-specs"
                aria-label="Edit hardware specs"
                aria-expanded={specsOpen}
                onClick={() => setSpecsOpen((open) => !open)}
                className="font-mono text-[9px] uppercase tracking-[1.2px] text-b-text-dim transition-colors hover:text-b-clay"
              >
                [edit specs]
              </button>
            </div>
            {specsOpen && (
              <div className="mb-3.5">
                <HardwareOverrideForm onClose={() => setSpecsOpen(false)} />
              </div>
            )}
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
            {isLoading && (
              <div className="grid gap-3.5 md:grid-cols-2">
                {CAPABILITY_TIERS.map((tier) => (
                  <div
                    key={tier.key}
                    className="border-b-line bg-b-bg1 px-[17px] py-[15px]"
                    style={CARD_STYLE}
                  >
                    <div className="h-5 w-40 animate-pulse rounded bg-b-bg3" />
                  </div>
                ))}
              </div>
            )}
            {!isLoading && populatedBuckets.length > 0 && (
              <div className="grid gap-3.5 md:grid-cols-2">
                {populatedBuckets.map(({ tier, tierModels }) => (
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
                      {tierModels.map((model) => (
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
                ))}
              </div>
            )}
            {/* Empty bands collapse to one compact line each — no empty boxes. */}
            {!isLoading && emptyBuckets.length > 0 && (
              <div
                className={`${
                  populatedBuckets.length > 0 ? "mt-2 " : ""
                }flex flex-wrap gap-x-5 gap-y-1`}
              >
                {emptyBuckets.map(({ tier }) => (
                  <span
                    key={tier.key}
                    data-testid={`fit-band-empty-${tier.key}`}
                    className="font-mono text-[9.5px] text-b-text-faint"
                  >
                    <span style={{ color: tier.color }}>{tier.letter}</span>{" "}
                    {tier.label} — none
                  </span>
                ))}
              </div>
            )}
            {allFitWithHeadroom && (
              <p
                data-testid="fit-headroom-caption"
                className="mt-2 font-mono text-[9.5px] text-b-text-dim"
              >
                all matches fit with headroom on this machine
              </p>
            )}
          </div>

          {/* ─── PROVIDER BACKENDS · live probe ─── */}
          <ProviderProbeList
            probe={probe}
            probing={probing}
            probeError={probeError ?? null}
            onOpenInPlayground={openModelInPlayground}
          />

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
