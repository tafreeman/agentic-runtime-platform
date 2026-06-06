import { useMemo, useState } from "react";
import { Cpu, Gauge, HardDrive, SlidersHorizontal } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import BBox from "../components/common/BBox";
import BPill, { type BPillTone } from "../components/common/BPill";
import BTopBar from "../components/layout/BTopBar";
import { getModelRecommendations } from "../api/client";
import type { ModelSortField, ModelTaskCategory } from "../api/types";

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

function fitTone(score: number, runnable: boolean): BPillTone {
  if (!runnable) return "warn";
  if (score >= 80) return "ok";
  if (score >= 60) return "info";
  return "clay";
}

export default function ModelFinderPage() {
  const [category, setCategory] = useState<ModelTaskCategory | "all">("all");
  const [sortBy, setSortBy] = useState<ModelSortField>("downloads");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["model-recommendations", category, sortBy],
    queryFn: () => getModelRecommendations(category, sortBy),
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

  return (
    <div className="flex h-full flex-col">
      <BTopBar path="model finder">
        <button type="button" onClick={() => refetch()} className="btn-ghost">
          <SlidersHorizontal className="h-3 w-3" /> rescan
        </button>
      </BTopBar>

      <div className="h-full overflow-y-auto p-6">
        <div className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-[24px] font-semibold text-b-text">
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
                className="rounded-sm border border-b-line bg-b-bg1 px-2 py-1 font-mono text-[11px] text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
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
                className="rounded-sm border border-b-line bg-b-bg1 px-2 py-1 font-mono text-[11px] text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
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
            <BBox bodyClassName="p-4">
              <p className="font-mono text-[12px] text-b-red">
                failed to load model recommendations: {error.message}
              </p>
            </BBox>
          )}

          <div className="grid gap-3 lg:grid-cols-4">
            <BBox title="ram" bodyClassName="p-4">
              <div className="flex items-center gap-3">
                <HardDrive className="h-5 w-5 text-b-clay" />
                <div>
                  <div className="text-xl font-semibold text-b-text">
                    {isLoading ? "…" : `${data?.profile.ram_gb ?? 0} GB`}
                  </div>
                  <div className="font-mono text-[10px] text-b-text-dim">
                    usable memory budget
                  </div>
                </div>
              </div>
            </BBox>
            <BBox title="cpu" bodyClassName="p-4">
              <div className="flex items-center gap-3">
                <Cpu className="h-5 w-5 text-b-blue" />
                <div>
                  <div className="text-xl font-semibold text-b-text">
                    {isLoading ? "…" : `${data?.profile.cpu_cores_logical ?? 0} threads`}
                  </div>
                  <div className="font-mono text-[10px] text-b-text-dim">
                    {data?.profile.cpu_name ?? "detecting CPU"}
                  </div>
                </div>
              </div>
            </BBox>
            <BBox title="performance" bodyClassName="p-4">
              <div className="flex items-center gap-3">
                <Gauge className="h-5 w-5 text-b-green" />
                <div>
                  <div className="text-xl font-semibold text-b-text">
                    {isLoading
                      ? "…"
                      : compactNumber(data?.profile.estimated_cinebench_r23_multi ?? 0)}
                  </div>
                  <div className="font-mono text-[10px] text-b-text-dim">
                    est. Cinebench R23 multi
                  </div>
                </div>
              </div>
            </BBox>
            <BBox title="accelerators" bodyClassName="p-4">
              <div className="font-mono text-[11px] leading-5 text-b-text">
                {isLoading ? "detecting…" : acceleratorText}
              </div>
              <div className="mt-1 font-mono text-[10px] text-b-text-dim">
                tier: {data?.profile.performance_tier ?? "unknown"}
              </div>
            </BBox>
          </div>

          <BBox
            title="ranked model recommendations"
            right={<BPill tone="clay">{data?.sort_order.join(" › ") ?? "loading"}</BPill>}
          >
            <div className="overflow-x-auto">
              <table className="min-w-full text-left">
                <thead className="border-b border-b-line bg-b-bg2 font-mono text-[10px] uppercase text-b-text-dim">
                  <tr>
                    <th className="px-3 py-2">rank</th>
                    <th className="px-3 py-2">model</th>
                    <th className="px-3 py-2">fit</th>
                    <th className="px-3 py-2">category</th>
                    <th className="px-3 py-2">stats</th>
                    <th className="px-3 py-2">requirements</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-b-line">
                  {(data?.models ?? []).map((model, index) => (
                    <tr key={model.id} className="align-top hover:bg-b-bg2/50">
                      <td className="px-3 py-3 font-mono text-[11px] text-b-text-dim">
                        #{index + 1}
                      </td>
                      <td className="px-3 py-3">
                        <a
                          href={model.url}
                          target="_blank"
                          rel="noreferrer"
                          className="font-semibold text-b-text hover:text-b-clay"
                        >
                          {model.name}
                        </a>
                        <div className="mt-1 font-mono text-[10px] text-b-text-dim">
                          {model.parameters_b}B · {model.quantization} · ctx {compactNumber(model.context_tokens)}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <BPill tone={fitTone(model.fit_score, model.runnable)}>
                          {model.fit_score}% {model.runnable ? "run" : "tight"}
                        </BPill>
                        <div className="mt-1 max-w-40 font-mono text-[10px] text-b-text-dim">
                          {model.fit_reason}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex flex-wrap gap-1">
                          {model.categories.map((item) => (
                            <BPill key={item}>{item}</BPill>
                          ))}
                        </div>
                      </td>
                      <td className="px-3 py-3 font-mono text-[10px] leading-5 text-b-text-dim">
                        ↓ {compactNumber(model.downloads)} · ♥ {compactNumber(model.likes)} · forks {compactNumber(model.forks)}
                        <br />released {model.release_date}
                      </td>
                      <td className="px-3 py-3 font-mono text-[10px] leading-5 text-b-text-dim">
                        min RAM {model.min_ram_gb}GB · rec {model.recommended_ram_gb}GB
                        <br />min VRAM {model.min_vram_gb || "none"} · {model.license}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!isLoading && data?.models.length === 0 && (
                <div className="p-6 font-mono text-[12px] text-b-text-dim">
                  no models matched this category
                </div>
              )}
            </div>
          </BBox>

          {data?.profile.notes.map((note) => (
            <p key={note} className="font-mono text-[10px] text-b-text-faint">
              note: {note}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}
