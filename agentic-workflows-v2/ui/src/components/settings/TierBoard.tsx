import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getTierSettings, putTierSettings } from "../../api/client";
import type {
  TierChain,
  TierModelInfo,
  TierSettingsResponse,
  TierSettingsUpdateRequest,
} from "../../api/types";
import BPill from "../common/BPill";

const CARD_STYLE = {
  background: "rgb(var(--b-bg1))",
  border: "var(--b-bw) solid rgb(var(--b-line))",
  borderRadius: "var(--b-rad-lg)",
} as const;

const CHIP_STYLE = { borderRadius: "var(--b-rad-sm)" } as const;

/** Swap positions index and index+1, returning a new array. */
function moveDown(order: string[], index: number): string[] {
  const next = order.slice();
  const upper = next[index];
  const lower = next[index + 1];
  if (upper === undefined || lower === undefined) return next;
  next[index] = lower;
  next[index + 1] = upper;
  return next;
}

interface CapabilityEditorState {
  /** `${tier}:${modelId}` — a model can appear in several tier chains. */
  key: string;
  modelId: string;
  tags: string[];
}

function ModelChipRow({
  tier,
  modelId,
  index,
  count,
  info,
  expanded,
  disabled,
  onMoveUp,
  onMoveDown,
  onToggleEditor,
}: Readonly<{
  tier: number;
  modelId: string;
  index: number;
  count: number;
  info: TierModelInfo | undefined;
  expanded: boolean;
  disabled: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onToggleEditor: () => void;
}>) {
  const isWinner = index === 0;
  return (
    <div className="flex items-center gap-2">
      <span
        className={`w-6 flex-none text-right font-mono text-[10px] tabular-nums ${
          isWinner ? "font-semibold text-b-clay" : "text-b-text-faint"
        }`}
      >
        {index + 1}.
      </span>
      <button
        type="button"
        aria-label={`Edit capabilities for ${modelId} in tier ${tier}`}
        aria-expanded={expanded}
        onClick={onToggleEditor}
        className={`flex min-w-0 flex-1 items-center gap-2 border px-2.5 py-1.5 text-left font-mono text-[11px] transition-colors hover:text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50 ${
          isWinner
            ? "border-b-clay bg-b-clay-soft text-b-text"
            : "border-b-line bg-b-bg2 text-b-text-mid"
        }`}
        style={CHIP_STYLE}
      >
        <span className="truncate">{modelId}</span>
        {isWinner && (
          <span className="flex-none font-mono text-[8.5px] uppercase tracking-[0.5px] text-b-clay">
            ▸ routes here
          </span>
        )}
        <span className="ml-auto flex flex-none items-center gap-1">
          {(info?.capabilities ?? []).map((cap) => (
            <span
              key={cap}
              className="border border-b-line px-1.5 py-px font-mono text-[8px] uppercase tracking-[0.3px] text-b-text-dim"
              style={{ borderRadius: "3px" }}
            >
              {cap}
            </span>
          ))}
          {info?.capability_overridden && <BPill tone="warn">overridden</BPill>}
        </span>
      </button>
      <span className="flex flex-none gap-1">
        <button
          type="button"
          aria-label={`Move ${modelId} up in tier ${tier}`}
          disabled={disabled || index === 0}
          onClick={onMoveUp}
          className="border border-b-line px-1.5 py-1 font-mono text-[10px] text-b-text-dim transition-colors hover:text-b-text disabled:cursor-not-allowed disabled:opacity-30"
          style={CHIP_STYLE}
        >
          ↑
        </button>
        <button
          type="button"
          aria-label={`Move ${modelId} down in tier ${tier}`}
          disabled={disabled || index === count - 1}
          onClick={onMoveDown}
          className="border border-b-line px-1.5 py-1 font-mono text-[10px] text-b-text-dim transition-colors hover:text-b-text disabled:cursor-not-allowed disabled:opacity-30"
          style={CHIP_STYLE}
        >
          ↓
        </button>
      </span>
    </div>
  );
}

export default function TierBoard() {
  const queryClient = useQueryClient();
  const [editor, setEditor] = useState<CapabilityEditorState | null>(null);
  const [dryTier, setDryTier] = useState(2);
  const [dryCapability, setDryCapability] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["tier-settings"],
    queryFn: getTierSettings,
  });

  const saveMutation = useMutation({
    mutationFn: (update: TierSettingsUpdateRequest) => putTierSettings(update),
    onSuccess: (fresh: TierSettingsResponse) => {
      queryClient.setQueryData(["tier-settings"], fresh);
      setEditor(null);
    },
  });

  const modelById = useMemo(() => {
    const map = new Map<string, TierModelInfo>();
    for (const model of data?.models ?? []) map.set(model.id, model);
    return map;
  }, [data]);

  const rerank = (tier: number, order: string[]) => {
    saveMutation.mutate({ tier_overrides: { [String(tier)]: order } });
  };

  const toggleEditor = (tier: TierChain, modelId: string) => {
    const key = `${tier.tier}:${modelId}`;
    if (editor?.key === key) {
      setEditor(null);
      return;
    }
    setEditor({
      key,
      modelId,
      tags: modelById.get(modelId)?.capabilities ?? [],
    });
  };

  const toggleTag = (tag: string) => {
    setEditor((prev) => {
      if (!prev) return prev;
      const tags = prev.tags.includes(tag)
        ? prev.tags.filter((t) => t !== tag)
        : [...prev.tags, tag];
      return { ...prev, tags };
    });
  };

  const dryChain = data?.tiers.find((tier) => tier.tier === dryTier)?.effective ?? [];
  const dryCandidates = dryCapability
    ? dryChain.filter((modelId) =>
        modelById.get(modelId)?.capabilities.includes(dryCapability),
      )
    : dryChain;

  return (
    <section aria-label="tier routing">
      <div className="mb-8 max-w-3xl">
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-el-accent-strong">Routing precedence</div>
        <h1 className="font-display text-[36px] font-medium leading-tight text-el-ink">Model tiers</h1>
        <p className="mt-3 text-[14px] leading-6 text-el-muted">Reorder fallback chains, annotate model capabilities, and explain a sample route without invoking a provider.</p>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-3 border-b-red/40 bg-b-bg1 p-4 font-mono text-[12px] text-b-red"
          style={{ borderWidth: "var(--b-bw)", borderRadius: "var(--b-rad-lg)" }}
        >
          failed to load tier settings: {error.message}
        </div>
      )}
      {isLoading && (
        <div className="p-4 font-mono text-[11px] text-b-text-dim">
          loading tiers…
        </div>
      )}
      {saveMutation.isError && (
        <div role="alert" className="mb-3 font-mono text-[10px] text-b-red">
          save failed: {saveMutation.error.message}
        </div>
      )}

      {data && (
        <div className="mb-7 border-y border-el-divider py-5" data-testid="routing-dry-run">
          <div className="mb-3 text-[12px] font-semibold text-el-ink">Dry-run route explanation</div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-[11px] font-semibold text-el-muted">
              Tier
              <select aria-label="Dry run tier" value={dryTier} onChange={(event) => setDryTier(Number(event.target.value))} className="mt-1 block h-10 min-w-28 border border-el-divider bg-el-raised px-3 text-[13px] text-el-ink">
                {data.tiers.map((tier) => <option key={tier.tier} value={tier.tier}>Tier {tier.tier}</option>)}
              </select>
            </label>
            <label className="text-[11px] font-semibold text-el-muted">
              Required capability
              <select aria-label="Dry run capability" value={dryCapability} onChange={(event) => setDryCapability(event.target.value)} className="mt-1 block h-10 min-w-48 border border-el-divider bg-el-raised px-3 text-[13px] text-el-ink">
                <option value="">Any capability</option>
                {data.known_capabilities.map((capability) => <option key={capability} value={capability}>{capability}</option>)}
              </select>
            </label>
            <div className="min-w-0 flex-1 border-l-2 border-el-accent px-4 py-2 text-[12px] leading-5 text-el-secondary">
              {dryCandidates.length > 0 ? (
                <><strong className="text-el-ink">Routes first to {dryCandidates[0]}</strong><br />Candidates: {dryCandidates.join(" → ")}</>
              ) : (
                <strong className="text-el-danger">No tier {dryTier} candidate advertises {dryCapability}.</strong>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-3.5">
        {(data?.tiers ?? []).map((tier) => {
          const order = tier.effective;
          const overridden = tier.override.length > 0;
          return (
            <div key={tier.tier} className="px-[17px] py-[15px]" style={CARD_STYLE}>
              <div className="flex items-center gap-2.5">
                <span
                  className="text-[14px] font-semibold text-b-clay"
                  style={{ fontFamily: "var(--b-font-heading)" }}
                >
                  T{tier.tier}
                </span>
                {tier.tier === 0 && (
                  <span className="font-mono text-[9.5px] text-b-text-faint">
                    deterministic
                  </span>
                )}
                {overridden && <BPill tone="clay">reranked</BPill>}
                {overridden && (
                  <button
                    type="button"
                    aria-label={`Reset tier ${tier.tier} to default`}
                    disabled={saveMutation.isPending}
                    onClick={() =>
                      saveMutation.mutate({
                        tier_overrides: { [String(tier.tier)]: [] },
                      })
                    }
                    className="ml-auto border border-b-line px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.5px] text-b-text-dim transition-colors hover:border-b-clay/50 hover:text-b-clay disabled:opacity-40"
                    style={CHIP_STYLE}
                  >
                    reset to default
                  </button>
                )}
              </div>

              {order.length === 0 ? (
                <p className="mt-2.5 font-mono text-[10px] text-b-text-faint">
                  {tier.tier === 0
                    ? "no model chain — tier 0 runs deterministic (non-LLM) steps"
                    : "no models in this chain"}
                </p>
              ) : (
                <ol className="mt-3 space-y-1.5">
                  {order.map((modelId, index) => {
                    const key = `${tier.tier}:${modelId}`;
                    const expanded = editor?.key === key;
                    return (
                      <li key={key}>
                        <ModelChipRow
                          tier={tier.tier}
                          modelId={modelId}
                          index={index}
                          count={order.length}
                          info={modelById.get(modelId)}
                          expanded={expanded}
                          disabled={saveMutation.isPending}
                          onMoveUp={() => rerank(tier.tier, moveDown(order, index - 1))}
                          onMoveDown={() => rerank(tier.tier, moveDown(order, index))}
                          onToggleEditor={() => toggleEditor(tier, modelId)}
                        />
                        {expanded && editor && (
                          <div
                            className="ml-8 mt-1.5 border border-b-line-soft bg-b-bg0 px-3 py-2.5"
                            style={CHIP_STYLE}
                          >
                            <div className="mb-2 font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim">
                              CAPABILITIES · {modelId}
                              {modelById.get(modelId)?.capability_overridden && (
                                <span className="ml-2 text-b-amber">overridden</span>
                              )}
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {(data?.known_capabilities ?? []).map((cap) => {
                                const active = editor.tags.includes(cap);
                                return (
                                  <button
                                    key={cap}
                                    type="button"
                                    aria-pressed={active}
                                    onClick={() => toggleTag(cap)}
                                    className={`border px-2 py-1 font-mono text-[10px] transition-colors ${
                                      active
                                        ? "border-b-clay bg-b-clay-soft text-b-text"
                                        : "border-b-line bg-b-bg1 text-b-text-faint hover:text-b-text-mid"
                                    }`}
                                    style={CHIP_STYLE}
                                  >
                                    {cap}
                                  </button>
                                );
                              })}
                            </div>
                            <div className="mt-3 flex items-center gap-2">
                              <button
                                type="button"
                                disabled={saveMutation.isPending}
                                onClick={() =>
                                  saveMutation.mutate({
                                    model_capabilities: {
                                      [modelId]: editor.tags,
                                    },
                                  })
                                }
                                className="bg-b-clay px-2.5 py-1 font-mono text-[10px] font-semibold text-b-ink transition-opacity hover:opacity-90 disabled:opacity-40"
                                style={CHIP_STYLE}
                              >
                                save capabilities
                              </button>
                              <button
                                type="button"
                                disabled={saveMutation.isPending}
                                onClick={() =>
                                  saveMutation.mutate({
                                    model_capabilities: { [modelId]: [] },
                                  })
                                }
                                className="border border-b-line px-2.5 py-1 font-mono text-[10px] text-b-text-dim transition-colors hover:text-b-text disabled:opacity-40"
                                style={CHIP_STYLE}
                              >
                                clear override
                              </button>
                            </div>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ol>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
