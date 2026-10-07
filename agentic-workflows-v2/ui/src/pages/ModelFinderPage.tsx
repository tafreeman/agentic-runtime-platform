import { useMemo, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import BTopBar from "../components/layout/BTopBar";
import Scoreline from "../components/common/Scoreline";
import { apiErrorText } from "../components/common/apiErrorText";
import ChatPlaygroundPanel from "../components/models/ChatPlaygroundPanel";
import HardwareOverrideForm from "../components/models/HardwareOverrideForm";
import ProviderProbeList from "../components/models/ProviderProbeList";
import ModelPacksPanel from "../components/models/ModelPacksPanel";
import ProviderPanel from "../components/settings/ProviderPanel";
import TierBoard from "../components/settings/TierBoard";
import { Button } from "../components/ui/button";
import { getModelRecommendations, probeModels } from "../api/client";
import { describeApiError } from "../lib/apiErrors";
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
  /** Text color for the band letter (text-safe token). */
  readonly textClass: string;
  /** Border color for the band's model chips (decorative; letter carries it). */
  readonly borderClass: string;
  readonly match: (model: ModelCandidate) => boolean;
}

const CAPABILITY_TIERS: readonly CapabilityTier[] = [
  {
    key: "s",
    letter: "S",
    label: "headroom",
    desc: "fits with budget to spare",
    textClass: "text-el-success",
    borderClass: "border-el-success",
    match: (m) => m.runnable && m.fit_score >= 80,
  },
  {
    key: "a",
    letter: "A",
    label: "comfortable",
    desc: "runs on this machine",
    textClass: "text-el-info",
    borderClass: "border-el-info",
    match: (m) => m.runnable && m.fit_score >= 60 && m.fit_score < 80,
  },
  {
    key: "b",
    letter: "B",
    label: "workable",
    desc: "runs with trade-offs",
    textClass: "text-el-warning",
    borderClass: "border-el-warning",
    match: (m) => m.runnable && m.fit_score < 60,
  },
  {
    key: "c",
    letter: "C",
    label: "tight",
    desc: "exceeds detected budget",
    textClass: "text-el-danger",
    borderClass: "border-el-danger",
    match: (m) => !m.runnable,
  },
];

const CARD_CLASS = "rounded-lg border border-el-divider bg-el-surface";
const SELECT_CLASS =
  "h-10 rounded-md border border-el-control-border bg-el-raised px-2 font-mono text-xs text-el-ink focus-ring focus-visible:border-el-focus";
/** >=36x36px centred ::after hit area for visually compact controls. */
const HIT_AREA =
  "relative after:absolute after:top-1/2 after:left-1/2 after:size-full after:min-h-9 after:min-w-9 after:-translate-x-1/2 after:-translate-y-1/2";

/** Pulse placeholder for a scoreline value while the profile loads. */
function ValueSkeleton() {
  return (
    <span className="block h-7 w-20 animate-pulse rounded-sm bg-el-hover motion-reduce:animate-none">
      <span className="sr-only">Loading</span>
    </span>
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
      // The active rail is state-bearing, so it uses accent-strong (>=3:1).
      // Inset ring: the tab strip scrolls horizontally and would clip it.
      className={`-mb-px whitespace-nowrap border-b-2 px-1 pb-3 pt-4 text-[13px] font-semibold transition-colors focus-ring-inset ${
        active
          ? "border-el-accent-strong text-el-ink"
          : "border-transparent text-el-muted hover:text-el-ink"
      }`}
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

  // No profile (still loading, or the API is down) renders "—", never a
  // fabricated "0 GB" / "0 threads" / "CPU only" reading.
  const profile = data?.profile;
  const ramText = profile ? `${profile.ram_gb} GB` : "—";
  const threadsText = profile ? `${profile.cpu_cores_logical} threads` : "—";
  const cpuLabel = profile?.cpu_name ?? (isLoading ? "detecting CPU" : "CPU");
  const cinebenchText = profile
    ? compactNumber(profile.estimated_cinebench_r23_multi)
    : "—";

  const acceleratorText = useMemo(() => {
    if (!data?.profile) return "—";
    const accelerators = data.profile.accelerators;
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
        {/* A read, not a mutation: stays available as the retry while the
            API is down. */}
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={rescan}
          disabled={probing || refreshing}
          aria-busy={probing || refreshing}
          aria-label="Rescan providers"
          className="font-mono text-micro font-normal text-el-secondary"
        >
          <SlidersHorizontal
            aria-hidden="true"
            className={probing || refreshing ? "animate-spin" : ""}
          />
          rescan
        </Button>
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
              <h1 className="font-display text-[36px] font-medium leading-tight text-el-ink">Hardware</h1>
              {/* Scope line (§8.2): what this tab controls, in product terms. */}
              <p className="mt-3 max-w-[70ch] text-[14px] leading-6 text-el-muted">
                The memory and compute used to rank local models on the Models
                tab. Overrides change those recommendations only, not routing.
              </p>
            </div>
            {/* Detected profile as a ruled scoreline (§11.1), not icon cards. */}
            <Scoreline
              label="detected hardware"
              items={[
                { label: "Usable memory", value: isLoading ? <ValueSkeleton /> : ramText },
                { label: cpuLabel, value: isLoading ? <ValueSkeleton /> : threadsText },
                { label: "Estimated CPU score", value: isLoading ? <ValueSkeleton /> : cinebenchText },
                {
                  label: "Accelerators",
                  value: isLoading ? (
                    <ValueSkeleton />
                  ) : (
                    <span className="block font-sans text-sm font-medium leading-snug tracking-normal">
                      {acceleratorText}
                    </span>
                  ),
                },
              ]}
            />
            <HardwareOverrideForm onClose={() => openTab("finder")} />
          </div>
        )}
        {tab === "finder" && (
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="font-display text-[36px] font-medium leading-tight text-el-ink">
                Model catalog
              </h1>
              {/* Scope line (§8.2): what this tab controls, in product terms. */}
              <p className="mt-3 max-w-[70ch] text-[14px] leading-6 text-el-muted">
                Ranks local models by how well they fit this machine's
                hardware. Browsing here doesn't change routing; tiers and packs
                do.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <select
                value={category}
                onChange={(event) =>
                  setCategory(event.target.value as ModelTaskCategory | "all")
                }
                className={SELECT_CLASS}
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
                className={SELECT_CLASS}
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

          {error && describeApiError(error).unreachable && (
            // The shell banner already reports the outage — a quiet note.
            <p className="font-mono text-micro text-el-muted">
              model recommendations unavailable —{" "}
              {describeApiError(error).summary}
            </p>
          )}
          {error && !describeApiError(error).unreachable && (
            <div
              role="alert"
              className="rounded-lg border border-el-danger/40 bg-el-danger-soft p-4 font-mono text-xs text-el-danger"
            >
              failed to load model recommendations: {apiErrorText(error)}
            </div>
          )}

          {/* ─── SYSTEM PROFILE ─── */}
          <div>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="m-0 font-sans text-[15px] font-semibold text-el-ink">
                System profile
              </h2>
              <span className="text-xs text-el-muted">
                Hardware class: {data?.profile.performance_tier ?? "—"}
              </span>
              <button
                type="button"
                data-testid="edit-specs"
                aria-label="Edit hardware specs"
                aria-expanded={specsOpen}
                onClick={() => setSpecsOpen((open) => !open)}
                className={`${HIT_AREA} rounded-sm text-xs font-medium text-el-secondary underline underline-offset-2 transition-colors hover:text-el-ink focus-ring`}
              >
                Edit hardware specs
              </button>
            </div>
            {specsOpen && (
              <div className="mb-3.5">
                <HardwareOverrideForm onClose={() => setSpecsOpen(false)} />
              </div>
            )}
            {/* Detected profile as a ruled scoreline (§11.1), not icon cards. */}
            <Scoreline
              label="system profile"
              items={[
                { label: "Usable memory budget", value: isLoading ? <ValueSkeleton /> : ramText },
                { label: cpuLabel, value: isLoading ? <ValueSkeleton /> : threadsText },
                {
                  label: "Est. Cinebench R23 multi",
                  value: isLoading ? <ValueSkeleton /> : cinebenchText,
                },
                {
                  label: "Accelerators",
                  value: isLoading ? (
                    <ValueSkeleton />
                  ) : (
                    <span className="block font-sans text-sm font-medium leading-snug tracking-normal">
                      {acceleratorText}
                    </span>
                  ),
                },
              ]}
            />
          </div>

          {/* ─── FIT GROUPS ─── (memory-fit buckets — not the router's T0–T5
              capability tiers, so they are not called "tiers" here) */}
          <div>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="m-0 font-sans text-[15px] font-semibold text-el-ink">
                Fit for this machine
              </h2>
              <span className="text-xs text-el-muted">
                Grouped by memory headroom, ranked by fit
              </span>
            </div>
            {isLoading && (
              <div className="grid gap-3.5 md:grid-cols-2">
                {CAPABILITY_TIERS.map((tier) => (
                  <div key={tier.key} className={`${CARD_CLASS} px-4 py-3.5`}>
                    <div className="h-5 w-40 animate-pulse rounded-sm bg-el-hover" />
                  </div>
                ))}
              </div>
            )}
            {!isLoading && populatedBuckets.length > 0 && (
              <div className="grid gap-3.5 md:grid-cols-2">
                {populatedBuckets.map(({ tier, tierModels }) => (
                  <div key={tier.key} className={`${CARD_CLASS} px-4 py-3.5`}>
                    <div className="flex items-baseline gap-2.5">
                      <span className={`font-display text-[14px] font-semibold ${tier.textClass}`}>
                        {tier.letter}
                      </span>
                      <span className="text-xs text-el-secondary">
                        {tier.label}
                      </span>
                      <span className="ml-auto font-mono text-micro text-el-muted">
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
                          className={`${HIT_AREA} inline-flex min-h-8 max-w-[200px] items-center gap-1.5 rounded-sm border bg-el-subtle px-2 py-1 font-mono text-micro text-el-secondary underline-offset-2 transition-colors hover:text-el-ink hover:underline focus-ring ${tier.borderClass}`}
                        >
                          <span className="truncate">{model.name}</span>
                          <span className="flex-none text-el-muted">
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
                    className="font-mono text-micro text-el-muted"
                  >
                    <span className={tier.textClass}>{tier.letter}</span>{" "}
                    {tier.label} — none
                  </span>
                ))}
              </div>
            )}
            {allFitWithHeadroom && (
              <p
                data-testid="fit-headroom-caption"
                className="mt-2 font-mono text-micro text-el-muted"
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
            <p key={note} className="font-mono text-micro text-el-muted">
              note: {note}
            </p>
          ))}
        </div>
        )}
      </div>
    </div>
  );
}
