import { useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getTierSettings, putTierSettings } from "../../api/client";
import type {
  TierChain,
  TierModelInfo,
  TierSettingsResponse,
  TierSettingsUpdateRequest,
} from "../../api/types";
import { useApiAvailability } from "../../hooks/useApiAvailability";
import { describeApiError } from "../../lib/apiErrors";
import BPill from "../common/BPill";
import { apiErrorText } from "../common/apiErrorText";
import { Button } from "../ui/button";

const CARD_CLASS = "rounded-lg border border-el-divider bg-el-surface";

/** >=36x36px centred ::after hit area for visually compact toggles. */
const HIT_AREA =
  "relative after:absolute after:top-1/2 after:left-1/2 after:size-full after:min-h-9 after:min-w-9 after:-translate-x-1/2 after:-translate-y-1/2";

const SELECT_CLASS =
  "mt-1 block h-10 rounded-md border border-el-control-border bg-el-raised px-3 text-[13px] text-el-ink focus-ring focus-visible:border-el-focus";

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
  describedBy,
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
  /** id of the visible reason the move buttons are disabled (API down). */
  describedBy?: string;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onToggleEditor: () => void;
}>) {
  const isWinner = index === 0;
  return (
    <div className="flex items-center gap-2">
      <span
        className={`w-6 flex-none text-right font-mono text-micro tabular-nums ${
          isWinner ? "font-semibold text-el-ink" : "text-el-muted"
        }`}
      >
        {index + 1}.
      </span>
      {/* The routing winner reads through weight, an ink outline and the
          "routes here" label — no vermilion: with one winner per tier, an
          accent fill would repeat five times down the page (§4.2 restraint).
          The dry-run result's rule stays the view's single accent mark. */}
      <button
        type="button"
        aria-label={`Edit capabilities for ${modelId} in tier ${tier}`}
        aria-expanded={expanded}
        onClick={onToggleEditor}
        className={`flex min-h-9 min-w-0 flex-1 items-center gap-2 rounded-sm border px-2.5 py-1.5 text-left font-mono text-xs transition-colors hover:text-el-ink focus-ring ${
          isWinner
            ? "border-el-ink/70 bg-el-raised font-semibold text-el-ink"
            : "border-el-divider bg-el-subtle text-el-secondary"
        }`}
      >
        <span className="truncate">{modelId}</span>
        {isWinner && (
          <span className="flex-none font-mono text-micro font-normal uppercase tracking-[0.5px] text-el-secondary">
            ▸ routes here
          </span>
        )}
        <span className="ml-auto flex flex-none items-center gap-1">
          {(info?.capabilities ?? []).map((cap) => (
            <span
              key={cap}
              className="rounded-sm border border-el-divider px-1.5 py-px font-mono text-micro uppercase tracking-[0.3px] text-el-muted"
            >
              {cap}
            </span>
          ))}
          {info?.capability_overridden && <BPill tone="warn">overridden</BPill>}
        </span>
      </button>
      <span className="flex flex-none gap-1">
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label={`Move ${modelId} up in tier ${tier}`}
          aria-describedby={describedBy}
          disabled={disabled || index === 0}
          onClick={onMoveUp}
          className="font-mono text-xs font-normal text-el-secondary"
        >
          ↑
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label={`Move ${modelId} down in tier ${tier}`}
          aria-describedby={describedBy}
          disabled={disabled || index === count - 1}
          onClick={onMoveDown}
          className="font-mono text-xs font-normal text-el-secondary"
        >
          ↓
        </Button>
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

  // Every tier edit is a PUT: disabled while the API is unreachable, with
  // the visible reason referenced by aria-describedby.
  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const apiHintId = useId();
  const describedBy = apiDown ? apiHintId : undefined;
  const loadErrorInfo = error ? describeApiError(error) : null;

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
        <div className="mb-3 text-micro font-semibold uppercase tracking-[0.14em] text-el-muted">Routing precedence</div>
        <h1 className="font-display text-[36px] font-medium leading-tight text-el-ink">Model tiers</h1>
        <p className="mt-3 text-[14px] leading-6 text-el-muted">Reorder fallback chains, annotate model capabilities, and explain a sample route without invoking a provider.</p>
      </div>

      {error && loadErrorInfo?.unreachable && (
        // The shell banner already reports the outage — a quiet note here.
        <p className="mb-3 font-mono text-micro text-el-muted">
          tier settings unavailable — {loadErrorInfo.summary}
        </p>
      )}
      {error && !loadErrorInfo?.unreachable && (
        <div
          role="alert"
          className="mb-3 rounded-lg border border-el-danger/40 bg-el-danger-soft p-4 font-mono text-xs text-el-danger"
        >
          failed to load tier settings: {apiErrorText(error)}
        </div>
      )}
      {isLoading && (
        <div className="p-4 font-mono text-xs text-el-muted">
          loading tiers…
        </div>
      )}
      {saveMutation.isError && (
        <div role="alert" className="mb-3 font-mono text-xs text-el-danger">
          save failed: {apiErrorText(saveMutation.error)}
        </div>
      )}
      {apiDown && data && (
        <p id={apiHintId} className="mb-3 text-micro text-el-muted">
          Reordering and saving are unavailable: {apiDownReason}
        </p>
      )}

      {data && (
        <div className="mb-7 border-y border-el-divider py-5" data-testid="routing-dry-run">
          <div className="mb-3 text-xs font-semibold text-el-ink">Dry-run route explanation</div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-micro font-semibold text-el-muted">
              Tier
              <select aria-label="Dry run tier" value={dryTier} onChange={(event) => setDryTier(Number(event.target.value))} className={`${SELECT_CLASS} min-w-28`}>
                {data.tiers.map((tier) => <option key={tier.tier} value={tier.tier}>Tier {tier.tier}</option>)}
              </select>
            </label>
            <label className="text-micro font-semibold text-el-muted">
              Required capability
              <select aria-label="Dry run capability" value={dryCapability} onChange={(event) => setDryCapability(event.target.value)} className={`${SELECT_CLASS} min-w-48`}>
                <option value="">Any capability</option>
                {data.known_capabilities.map((capability) => <option key={capability} value={capability}>{capability}</option>)}
              </select>
            </label>
            <div className="min-w-0 flex-1 border-l-2 border-el-accent px-4 py-2 text-xs leading-5 text-el-secondary">
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
            <div key={tier.tier} className={`${CARD_CLASS} px-4 py-3.5`}>
              <div className="flex items-center gap-2.5">
                <span className="font-display text-[14px] font-semibold text-el-ink">
                  T{tier.tier}
                </span>
                {tier.tier === 0 && (
                  <span className="font-mono text-micro text-el-muted">
                    deterministic
                  </span>
                )}
                {overridden && <BPill tone="clay">reranked</BPill>}
                {overridden && (
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    aria-label={`Reset tier ${tier.tier} to default`}
                    aria-describedby={describedBy}
                    disabled={saveMutation.isPending || apiDown}
                    onClick={() =>
                      saveMutation.mutate({
                        tier_overrides: { [String(tier.tier)]: [] },
                      })
                    }
                    className="ml-auto font-mono text-micro uppercase tracking-[0.5px] text-el-secondary"
                  >
                    reset to default
                  </Button>
                )}
              </div>

              {order.length === 0 ? (
                <p className="mt-2.5 font-mono text-xs text-el-muted">
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
                          disabled={saveMutation.isPending || apiDown}
                          describedBy={describedBy}
                          onMoveUp={() => rerank(tier.tier, moveDown(order, index - 1))}
                          onMoveDown={() => rerank(tier.tier, moveDown(order, index))}
                          onToggleEditor={() => toggleEditor(tier, modelId)}
                        />
                        {expanded && editor && (
                          <div className="ml-8 mt-1.5 rounded-md border border-el-divider-soft bg-el-canvas px-3 py-2.5">
                            <div className="mb-2 font-mono text-micro uppercase tracking-[0.8px] text-el-muted">
                              CAPABILITIES · {modelId}
                              {modelById.get(modelId)?.capability_overridden && (
                                <span className="ml-2 text-el-warning">overridden</span>
                              )}
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {(data?.known_capabilities ?? []).map((cap) => {
                                const active = editor.tags.includes(cap);
                                return (
                                  // Pressed state = darker border + tint + a
                                  // check glyph, not color alone.
                                  <button
                                    key={cap}
                                    type="button"
                                    aria-pressed={active}
                                    onClick={() => toggleTag(cap)}
                                    className={`${HIT_AREA} h-8 rounded-sm border px-2.5 font-mono text-micro transition-colors focus-ring ${
                                      active
                                        ? "border-el-ink/70 bg-el-subtle text-el-ink"
                                        : "border-el-divider bg-el-surface text-el-muted hover:text-el-secondary"
                                    }`}
                                  >
                                    {active && <span aria-hidden="true">✓ </span>}
                                    {cap}
                                  </button>
                                );
                              })}
                            </div>
                            <div className="mt-3 flex items-center gap-2">
                              <Button
                                type="button"
                                size="xs"
                                aria-describedby={describedBy}
                                disabled={saveMutation.isPending || apiDown}
                                onClick={() =>
                                  saveMutation.mutate({
                                    model_capabilities: {
                                      [modelId]: editor.tags,
                                    },
                                  })
                                }
                                className="font-mono"
                              >
                                save capabilities
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                size="xs"
                                aria-describedby={describedBy}
                                disabled={saveMutation.isPending || apiDown}
                                onClick={() =>
                                  saveMutation.mutate({
                                    model_capabilities: { [modelId]: [] },
                                  })
                                }
                                className="font-mono font-normal text-el-secondary"
                              >
                                clear override
                              </Button>
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
