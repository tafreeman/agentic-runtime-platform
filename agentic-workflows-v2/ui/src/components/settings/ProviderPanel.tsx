import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getProviderSettings, probeProvider, putProviderSettings } from "../../api/client";
import type {
  ProviderEndpointConfig,
  ProviderProbeResponse,
  ProviderSettingsResponse,
  ProviderType,
} from "../../api/types";
import { useApiAvailability } from "../../hooks/useApiAvailability";
import { describeApiError } from "../../lib/apiErrors";
import BPill from "../common/BPill";
import { apiErrorText } from "../common/apiErrorText";
import { Button } from "../ui/button";

const CARD_CLASS = "rounded-lg border border-el-divider bg-el-surface";

const FIELD_LABEL_CLASS =
  "mb-1.5 block font-mono text-micro uppercase tracking-[0.8px] text-el-muted";

const INPUT_CLASS =
  "h-10 w-full rounded-md border border-el-divider bg-el-canvas px-2.5 font-mono text-xs text-el-ink placeholder:text-el-faint focus-ring focus-visible:border-el-focus disabled:opacity-60";

/** Compact card action: mono micro label on the shared outline Button. */
const CARD_ACTION_CLASS = "font-mono text-micro uppercase tracking-[0.5px]";

/** Valid provider id: lowercase slug, must start alphanumeric. */
const ID_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;

/**
 * A plausible environment-variable NAME (`OLLAMA_API_KEY`), as opposed to a
 * raw secret pasted by mistake (`sk-ant-…`). Values failing this are masked
 * on display and flagged in the form so a real key never sits on screen.
 */
const ENV_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

const KEY_WARNING_TEXT = "looks like a raw key — use an env var name";

const CHIP_CLASS =
  "rounded-sm border border-el-divider bg-el-subtle px-1.5 py-px text-micro text-el-secondary";

/** Renders a provider's api_key_env: `$NAME` chip, or a masked raw value. */
function KeyEnvValue({ value }: Readonly<{ value: string | null }>) {
  if (!value) return <span className="text-el-muted">none</span>;
  if (ENV_NAME_PATTERN.test(value)) {
    return <span className={CHIP_CLASS}>${value}</span>;
  }
  return (
    <span className="flex items-center gap-1.5">
      <span className={CHIP_CLASS}>{value.slice(0, 4)}…</span>
      <span className="rounded-sm border border-el-warning/40 bg-el-warning-soft px-1.5 py-px text-micro text-el-warning">
        {KEY_WARNING_TEXT}
      </span>
    </span>
  );
}

interface TypePreset {
  readonly label: string;
  readonly base_url: string;
  readonly api_key_env: string;
}

/** Human labels + per-type sensible defaults for the add-provider form. */
const TYPE_PRESETS: Record<ProviderType, TypePreset> = {
  openai: { label: "OpenAI", base_url: "", api_key_env: "OPENAI_API_KEY" },
  anthropic: { label: "Anthropic", base_url: "", api_key_env: "ANTHROPIC_API_KEY" },
  gh: { label: "GitHub Models", base_url: "", api_key_env: "GITHUB_TOKEN" },
  ollama: { label: "Ollama", base_url: "http://localhost:11434", api_key_env: "" },
  foundry_local: {
    label: "Foundry Local",
    base_url: "http://localhost:5273/v1",
    api_key_env: "",
  },
  custom: { label: "Custom endpoint", base_url: "", api_key_env: "" },
};

const TYPE_ORDER: readonly ProviderType[] = [
  "openai",
  "anthropic",
  "gh",
  "ollama",
  "foundry_local",
  "custom",
];

interface DraftProvider {
  id: string;
  label: string;
  base_url: string;
  api_key_env: string;
  default_model: string;
  enabled: boolean;
}

/** Suggest a unique slug id for a new provider of the given type. */
function suggestId(type: ProviderType, existing: ProviderEndpointConfig[]): string {
  const taken = new Set(existing.map((p) => p.id));
  if (!taken.has(type)) return type;
  let n = 2;
  while (taken.has(`${type}-${n}`)) n += 1;
  return `${type}-${n}`;
}

function draftFor(
  type: ProviderType,
  existing: ProviderEndpointConfig[],
): DraftProvider {
  const preset = TYPE_PRESETS[type];
  return {
    id: suggestId(type, existing),
    label: preset.label,
    base_url: preset.base_url,
    api_key_env: preset.api_key_env,
    default_model: "",
    enabled: true,
  };
}

/** Turn a draft form into the wire-format provider entry. */
function draftToConfig(type: ProviderType, draft: DraftProvider): ProviderEndpointConfig {
  return {
    id: draft.id.trim(),
    type,
    label: draft.label.trim() || TYPE_PRESETS[type].label,
    base_url: draft.base_url.trim() || null,
    api_key_env: draft.api_key_env.trim() || null,
    default_model: draft.default_model.trim() || null,
    enabled: draft.enabled,
    options: {},
  };
}

export default function ProviderPanel() {
  const queryClient = useQueryClient();
  const [addType, setAddType] = useState<ProviderType | null>(null);
  const [editId, setEditId] = useState<string | null>(null);
  const [draft, setDraft] = useState<DraftProvider | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [probeResults, setProbeResults] = useState<Record<string, ProviderProbeResponse>>({});
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["provider-settings"],
    queryFn: getProviderSettings,
  });
  // Saving, toggling, deleting and probing all hit the API: disabled while it
  // is unreachable, each pointing at a visible reason.
  const { apiDown, reason: apiDownReason } = useApiAvailability();
  const listHintId = useId();
  const formHintId = useId();
  const loadErrorInfo = error ? describeApiError(error) : null;

  const saveMutation = useMutation({
    mutationFn: (providers: ProviderEndpointConfig[]) =>
      putProviderSettings(providers),
    onSuccess: (fresh: ProviderSettingsResponse) => {
      queryClient.setQueryData(["provider-settings"], fresh);
      setAddType(null);
      setEditId(null);
      setDraft(null);
      setValidationError(null);
    },
  });

  const probeMutation = useMutation({
    mutationFn: probeProvider,
    onSuccess: (result) =>
      setProbeResults((current) => ({ ...current, [result.provider_id]: result })),
  });

  const providers = data?.providers ?? [];

  const openAddForm = (type: ProviderType) => {
    setAddType(type);
    setEditId(null);
    setDraft(draftFor(type, providers));
    setValidationError(null);
    saveMutation.reset();
  };

  const openEditForm = (provider: ProviderEndpointConfig) => {
    setAddType(provider.type);
    setEditId(provider.id);
    setDraft({
      id: provider.id,
      label: provider.label,
      base_url: provider.base_url ?? "",
      api_key_env: provider.api_key_env ?? "",
      default_model: provider.default_model ?? "",
      enabled: provider.enabled,
    });
    setValidationError(null);
    saveMutation.reset();
  };

  const updateDraft = (patch: Partial<DraftProvider>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  const submitDraft = () => {
    if (!addType || !draft) return;
    const id = draft.id.trim();
    if (!ID_PATTERN.test(id)) {
      setValidationError(
        "id must be a lowercase slug: letters/digits first, then a-z, 0-9, - or _",
      );
      return;
    }
    if (providers.some((p) => p.id === id && p.id !== editId)) {
      setValidationError(`a provider with id "${id}" already exists`);
      return;
    }
    setValidationError(null);
    const config = draftToConfig(addType, draft);
    saveMutation.mutate(
      editId
        ? providers.map((provider) => (provider.id === editId ? config : provider))
        : [...providers, config],
    );
  };

  const toggleEnabled = (id: string) => {
    saveMutation.mutate(
      providers.map((p) => (p.id === id ? { ...p, enabled: !p.enabled } : p)),
    );
  };

  const deleteProvider = (id: string) => {
    saveMutation.mutate(providers.filter((p) => p.id !== id));
    setPendingDeleteId(null);
  };

  return (
    <section aria-label="provider endpoints">
      <div className="mb-8 max-w-3xl">
        <div className="mb-3 text-micro font-semibold uppercase tracking-[0.14em] text-el-muted">Endpoint registry</div>
        <h1 className="font-display text-[36px] font-medium leading-tight text-el-ink">Providers</h1>
        <p className="mt-3 text-[14px] leading-6 text-el-muted">Manage saved endpoints, environment-variable references, availability, and live discovery probes. Credentials are never accepted or displayed.</p>
      </div>

      {error && loadErrorInfo?.unreachable && (
        // The shell banner already reports the outage — a quiet note here.
        <p className="mb-3 font-mono text-micro text-el-muted">
          provider settings unavailable — {loadErrorInfo.summary}
        </p>
      )}
      {error && !loadErrorInfo?.unreachable && (
        <div
          role="alert"
          className="mb-3 rounded-lg border border-el-danger/40 bg-el-danger-soft p-4 font-mono text-xs text-el-danger"
        >
          failed to load provider settings: {apiErrorText(error)}
        </div>
      )}
      {isLoading && (
        <div className="p-4 font-mono text-xs text-el-muted">
          loading providers…
        </div>
      )}
      {apiDown && !error && (
        <p id={listHintId} className="mb-3 text-micro text-el-muted">
          Saving and probing are unavailable: {apiDownReason}
        </p>
      )}

      {/* ─── configured provider cards ─── */}
      {!isLoading && !error && (
        <div className="grid gap-3.5 md:grid-cols-2">
          {providers.length === 0 && (
            <div className={`${CARD_CLASS} p-4 font-mono text-xs text-el-muted md:col-span-2`}>
              no provider endpoints configured — add one below
            </div>
          )}
          {providers.map((p) => (
            <div key={p.id} className={`${CARD_CLASS} px-4 py-3.5`}>
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="font-display text-[13px] font-semibold text-el-ink">
                  {p.label}
                </span>
                <BPill tone="info">{p.type}</BPill>
                {!p.enabled && <BPill tone="dim">disabled</BPill>}
                <span className="ml-auto flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    aria-label={`Probe provider ${p.id}`}
                    aria-describedby={apiDown ? listHintId : undefined}
                    disabled={probeMutation.isPending || !p.enabled || apiDown}
                    onClick={() => probeMutation.mutate(p.id)}
                    className={`${CARD_ACTION_CLASS} text-el-secondary`}
                  >
                    probe
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    aria-label={`Edit provider ${p.id}`}
                    disabled={saveMutation.isPending}
                    onClick={() => openEditForm(p)}
                    className={`${CARD_ACTION_CLASS} text-el-secondary`}
                  >
                    edit
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    role="switch"
                    aria-checked={p.enabled}
                    aria-label={`Toggle provider ${p.id}`}
                    aria-describedby={apiDown ? listHintId : undefined}
                    disabled={saveMutation.isPending || apiDown}
                    onClick={() => toggleEnabled(p.id)}
                    className={`${CARD_ACTION_CLASS} ${
                      p.enabled
                        ? "border-el-success/40 text-el-success"
                        : "text-el-muted"
                    }`}
                  >
                    {p.enabled ? "on" : "off"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    aria-label={`Delete provider ${p.id}`}
                    aria-describedby={apiDown ? listHintId : undefined}
                    disabled={saveMutation.isPending || apiDown}
                    onClick={() => setPendingDeleteId(p.id)}
                    className={`${CARD_ACTION_CLASS} text-el-secondary hover:border-el-danger/40 hover:text-el-danger`}
                  >
                    delete
                  </Button>
                </span>
              </div>
              <dl className="mt-3 space-y-1.5 font-mono text-micro">
                <div className="flex gap-2">
                  <dt className="w-24 flex-none uppercase tracking-[0.5px] text-el-muted">
                    id
                  </dt>
                  <dd className="truncate text-el-secondary">{p.id}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-24 flex-none uppercase tracking-[0.5px] text-el-muted">
                    base url
                  </dt>
                  <dd className="truncate text-el-secondary">
                    {p.base_url || "(provider default)"}
                  </dd>
                </div>
                <div className="flex items-center gap-2">
                  <dt className="w-24 flex-none uppercase tracking-[0.5px] text-el-muted">
                    key env
                  </dt>
                  <dd>
                    <KeyEnvValue value={p.api_key_env ?? null} />
                  </dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-24 flex-none uppercase tracking-[0.5px] text-el-muted">
                    default model
                  </dt>
                  <dd className="truncate text-el-secondary">
                    {p.default_model || "—"}
                  </dd>
                </div>
              </dl>
              {probeResults[p.id] && (
                <div
                  className={`mt-3 border-l-2 px-3 py-2 text-xs ${
                    probeResults[p.id]!.status === "available"
                      ? "border-el-success bg-el-surface text-el-success"
                      : "border-el-danger bg-el-surface text-el-danger"
                  }`}
                  role="status"
                >
                  <span className="font-semibold">{probeResults[p.id]!.status}</span>
                  {` · ${probeResults[p.id]!.latency_ms} ms · ${probeResults[p.id]!.discovered_model_count} models`}
                  <span className="mt-1 block text-el-muted">{probeResults[p.id]!.detail}</span>
                </div>
              )}
              {pendingDeleteId === p.id && (
                <div className="mt-3 flex flex-wrap items-center gap-2 border-l-2 border-el-danger bg-el-surface px-3 py-2 text-xs text-el-danger" role="alert">
                  <span className="mr-auto">Remove this saved endpoint? Environment variables are unaffected.</span>
                  <Button type="button" variant="ghost" size="xs" className="text-el-muted" onClick={() => setPendingDeleteId(null)}>Cancel</Button>
                  <Button
                    type="button"
                    variant="destructive"
                    size="xs"
                    aria-describedby={apiDown ? listHintId : undefined}
                    disabled={saveMutation.isPending || apiDown}
                    onClick={() => deleteProvider(p.id)}
                  >
                    Remove provider
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ─── add provider ─── */}
      <div className="mt-4">
        <div className="mb-2 font-mono text-micro uppercase tracking-[1px] text-el-muted">
          ADD PROVIDER
        </div>
        <div className="flex flex-wrap gap-1.5">
          {TYPE_ORDER.map((type) => (
            <button
              key={type}
              type="button"
              aria-label={`Add ${TYPE_PRESETS[type].label} provider`}
              aria-pressed={addType === type}
              onClick={() => openAddForm(type)}
              className={`min-h-9 rounded-md border px-3 py-1.5 font-mono text-xs transition-colors focus-ring ${
                addType === type
                  ? "border-el-accent-strong bg-el-subtle text-el-ink"
                  : "border-el-divider bg-el-surface text-el-secondary hover:border-el-faint hover:text-el-ink"
              }`}
            >
              {TYPE_PRESETS[type].label}
            </button>
          ))}
        </div>

        {addType && draft && (
          <form
            className={`${CARD_CLASS} mt-3 px-4 py-3.5`}
            onSubmit={(event) => {
              event.preventDefault();
              submitDraft();
            }}
          >
            <div className="mb-3 font-mono text-micro font-semibold uppercase tracking-[1.5px] text-el-secondary">
              {editId ? "EDIT" : "NEW"} {TYPE_PRESETS[addType].label} ENDPOINT
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <div>
                <label htmlFor="provider-id" className={FIELD_LABEL_CLASS}>
                  id (slug)
                </label>
                <input
                  id="provider-id"
                  value={draft.id}
                  onChange={(e) => updateDraft({ id: e.target.value })}
                  required
                  disabled={editId !== null}
                  className={INPUT_CLASS}
                />
              </div>
              <div>
                <label htmlFor="provider-label" className={FIELD_LABEL_CLASS}>
                  label
                </label>
                <input
                  id="provider-label"
                  value={draft.label}
                  onChange={(e) => updateDraft({ label: e.target.value })}
                  className={INPUT_CLASS}
                />
              </div>
              <div>
                <label htmlFor="provider-base-url" className={FIELD_LABEL_CLASS}>
                  base url
                </label>
                <input
                  id="provider-base-url"
                  value={draft.base_url}
                  onChange={(e) => updateDraft({ base_url: e.target.value })}
                  placeholder="(provider default)"
                  className={INPUT_CLASS}
                />
              </div>
              <div>
                <label htmlFor="provider-key-env" className={FIELD_LABEL_CLASS}>
                  api key env var
                </label>
                <input
                  id="provider-key-env"
                  value={draft.api_key_env}
                  onChange={(e) => updateDraft({ api_key_env: e.target.value })}
                  placeholder="OLLAMA_API_KEY (env var name, not the key)"
                  className={INPUT_CLASS}
                />
                <p className="mt-1 font-mono text-micro text-el-muted">
                  name of the environment variable — the key itself is never
                  stored
                </p>
                {draft.api_key_env.trim() !== "" &&
                  !ENV_NAME_PATTERN.test(draft.api_key_env.trim()) && (
                    <p
                      role="alert"
                      className="mt-1 font-mono text-micro text-el-warning"
                    >
                      {KEY_WARNING_TEXT}
                    </p>
                  )}
              </div>
              <div>
                <label htmlFor="provider-default-model" className={FIELD_LABEL_CLASS}>
                  default model
                </label>
                <input
                  id="provider-default-model"
                  value={draft.default_model}
                  onChange={(e) => updateDraft({ default_model: e.target.value })}
                  className={INPUT_CLASS}
                />
              </div>
              <div className="flex items-end pb-1">
                <label className="flex min-h-9 cursor-pointer items-center gap-2 font-mono text-xs text-el-secondary">
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(e) => updateDraft({ enabled: e.target.checked })}
                    className="size-4 accent-el-action focus-ring"
                  />
                  enabled
                </label>
              </div>
            </div>

            {validationError && (
              <div role="alert" className="mt-3 font-mono text-xs text-el-danger">
                {validationError}
              </div>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button
                type="submit"
                size="sm"
                aria-describedby={apiDown ? formHintId : undefined}
                disabled={saveMutation.isPending || apiDown}
                className="font-mono"
              >
                {saveMutation.isPending
                  ? "saving…"
                  : editId
                    ? "save changes"
                    : "save provider"}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setAddType(null);
                  setEditId(null);
                  setDraft(null);
                  setValidationError(null);
                  saveMutation.reset();
                }}
                className="font-mono font-normal text-el-secondary"
              >
                cancel
              </Button>
              {apiDown && (
                <p id={formHintId} className="text-micro text-el-muted">
                  Saving is unavailable: {apiDownReason}
                </p>
              )}
            </div>
          </form>
        )}
      </div>

      {saveMutation.isError && (
        <div role="alert" className="mt-3 font-mono text-xs text-el-danger">
          save failed: {apiErrorText(saveMutation.error)}
        </div>
      )}

      {/* ─── env-configured strip ─── */}
      {data && data.env_configured_providers.length > 0 && (
        <div className="mt-4 border-t border-el-divider-soft pt-2.5 font-mono text-micro text-el-muted">
          configured via environment:{" "}
          <span className="text-el-secondary">
            {data.env_configured_providers.join(", ")}
          </span>
        </div>
      )}
    </section>
  );
}
