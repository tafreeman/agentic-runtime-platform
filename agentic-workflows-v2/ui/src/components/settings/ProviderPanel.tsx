import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getProviderSettings, putProviderSettings } from "../../api/client";
import type {
  ProviderEndpointConfig,
  ProviderSettingsResponse,
  ProviderType,
} from "../../api/types";
import BPill from "../common/BPill";

const CARD_STYLE = {
  background: "rgb(var(--b-bg1))",
  border: "var(--b-bw) solid rgb(var(--b-line))",
  borderRadius: "var(--b-rad-lg)",
} as const;

const INPUT_STYLE = {
  background: "rgb(var(--b-bg0))",
  border: "var(--b-bw) solid rgb(var(--b-line))",
  borderRadius: "var(--b-rad-sm)",
} as const;

const FIELD_LABEL_CLASS =
  "mb-1.5 block font-mono text-[9px] uppercase tracking-[0.8px] text-b-text-dim";

const INPUT_CLASS =
  "w-full px-2 py-1.5 font-mono text-[11px] text-b-text placeholder:text-b-text-faint focus:outline-none focus:ring-1 focus:ring-b-clay/50";

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
  "border border-b-line bg-b-bg2 px-1.5 py-px text-[9.5px] text-b-text-mid";

/** Renders a provider's api_key_env: `$NAME` chip, or a masked raw value. */
function KeyEnvValue({ value }: Readonly<{ value: string | null }>) {
  if (!value) return <span className="text-b-text-faint">none</span>;
  if (ENV_NAME_PATTERN.test(value)) {
    return (
      <span className={CHIP_CLASS} style={{ borderRadius: "var(--b-rad-sm)" }}>
        ${value}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5">
      <span className={CHIP_CLASS} style={{ borderRadius: "var(--b-rad-sm)" }}>
        {value.slice(0, 4)}…
      </span>
      <span
        className="border border-b-amber/40 px-1.5 py-px text-[9px] text-b-amber"
        style={{ borderRadius: "var(--b-rad-sm)" }}
      >
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
  const [draft, setDraft] = useState<DraftProvider | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["provider-settings"],
    queryFn: getProviderSettings,
  });

  const saveMutation = useMutation({
    mutationFn: (providers: ProviderEndpointConfig[]) =>
      putProviderSettings(providers),
    onSuccess: (fresh: ProviderSettingsResponse) => {
      queryClient.setQueryData(["provider-settings"], fresh);
      setAddType(null);
      setDraft(null);
      setValidationError(null);
    },
  });

  const providers = data?.providers ?? [];

  const openAddForm = (type: ProviderType) => {
    setAddType(type);
    setDraft(draftFor(type, providers));
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
    if (providers.some((p) => p.id === id)) {
      setValidationError(`a provider with id "${id}" already exists`);
      return;
    }
    setValidationError(null);
    saveMutation.mutate([...providers, draftToConfig(addType, draft)]);
  };

  const toggleEnabled = (id: string) => {
    saveMutation.mutate(
      providers.map((p) => (p.id === id ? { ...p, enabled: !p.enabled } : p)),
    );
  };

  const deleteProvider = (id: string) => {
    saveMutation.mutate(providers.filter((p) => p.id !== id));
  };

  return (
    <section aria-label="provider endpoints">
      <div className="mb-3 font-mono text-[9px] uppercase tracking-[1.6px] text-b-text-faint">
        PROVIDER ENDPOINTS · GET/PUT /api/settings/providers
      </div>

      {error && (
        <div
          role="alert"
          className="mb-3 border-b-red/40 bg-b-bg1 p-4 font-mono text-[12px] text-b-red"
          style={{ borderWidth: "var(--b-bw)", borderRadius: "var(--b-rad-lg)" }}
        >
          failed to load provider settings: {error.message}
        </div>
      )}
      {isLoading && (
        <div className="p-4 font-mono text-[11px] text-b-text-dim">
          loading providers…
        </div>
      )}

      {/* ─── configured provider cards ─── */}
      {!isLoading && !error && (
        <div className="grid gap-3.5 md:grid-cols-2">
          {providers.length === 0 && (
            <div
              className="p-4 font-mono text-[11px] text-b-text-dim md:col-span-2"
              style={CARD_STYLE}
            >
              no provider endpoints configured — add one below
            </div>
          )}
          {providers.map((p) => (
            <div key={p.id} className="px-[17px] py-[15px]" style={CARD_STYLE}>
              <div className="flex items-center gap-2.5">
                <span
                  className="text-[13px] font-semibold text-b-text"
                  style={{ fontFamily: "var(--b-font-heading)" }}
                >
                  {p.label}
                </span>
                <BPill tone="info">{p.type}</BPill>
                {!p.enabled && <BPill tone="dim">disabled</BPill>}
                <span className="ml-auto flex items-center gap-2">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={p.enabled}
                    aria-label={`Toggle provider ${p.id}`}
                    disabled={saveMutation.isPending}
                    onClick={() => toggleEnabled(p.id)}
                    className={`border px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.5px] transition-colors disabled:opacity-40 ${
                      p.enabled
                        ? "border-b-green/40 text-b-green"
                        : "border-b-line text-b-text-dim"
                    }`}
                    style={{ borderRadius: "var(--b-rad-sm)" }}
                  >
                    {p.enabled ? "on" : "off"}
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete provider ${p.id}`}
                    disabled={saveMutation.isPending}
                    onClick={() => deleteProvider(p.id)}
                    className="border border-b-line px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.5px] text-b-text-dim transition-colors hover:border-b-red/40 hover:text-b-red disabled:opacity-40"
                    style={{ borderRadius: "var(--b-rad-sm)" }}
                  >
                    delete
                  </button>
                </span>
              </div>
              <dl className="mt-3 space-y-1.5 font-mono text-[10.5px]">
                <div className="flex gap-2">
                  <dt className="w-24 flex-none uppercase tracking-[0.5px] text-b-text-faint">
                    id
                  </dt>
                  <dd className="truncate text-b-text-mid">{p.id}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-24 flex-none uppercase tracking-[0.5px] text-b-text-faint">
                    base url
                  </dt>
                  <dd className="truncate text-b-text-mid">
                    {p.base_url || "(provider default)"}
                  </dd>
                </div>
                <div className="flex items-center gap-2">
                  <dt className="w-24 flex-none uppercase tracking-[0.5px] text-b-text-faint">
                    key env
                  </dt>
                  <dd>
                    <KeyEnvValue value={p.api_key_env ?? null} />
                  </dd>
                </div>
                <div className="flex gap-2">
                  <dt className="w-24 flex-none uppercase tracking-[0.5px] text-b-text-faint">
                    default model
                  </dt>
                  <dd className="truncate text-b-text-mid">
                    {p.default_model || "—"}
                  </dd>
                </div>
              </dl>
            </div>
          ))}
        </div>
      )}

      {/* ─── add provider ─── */}
      <div className="mt-4">
        <div className="mb-2 font-mono text-[9px] uppercase tracking-[1px] text-b-text-faint">
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
              className={`border px-2.5 py-1.5 font-mono text-[11px] transition-colors ${
                addType === type
                  ? "border-b-clay bg-b-bg2 text-b-text"
                  : "border-b-line bg-b-bg1 text-b-text-mid hover:border-b-clay/50 hover:text-b-text"
              }`}
              style={{ borderRadius: "var(--b-rad-sm)" }}
            >
              {TYPE_PRESETS[type].label}
            </button>
          ))}
        </div>

        {addType && draft && (
          <form
            className="mt-3 px-[17px] py-[15px]"
            style={{
              ...CARD_STYLE,
              border: "var(--b-bw) solid rgb(var(--b-clay) / 0.5)",
            }}
            onSubmit={(event) => {
              event.preventDefault();
              submitDraft();
            }}
          >
            <div className="mb-3 font-mono text-[9.5px] uppercase tracking-[1.5px] text-b-clay">
              NEW {TYPE_PRESETS[addType].label} ENDPOINT
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
                  className={INPUT_CLASS}
                  style={INPUT_STYLE}
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
                  style={INPUT_STYLE}
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
                  style={INPUT_STYLE}
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
                  style={INPUT_STYLE}
                />
                <p className="mt-1 font-mono text-[9px] text-b-text-faint">
                  name of the environment variable — the key itself is never
                  stored
                </p>
                {draft.api_key_env.trim() !== "" &&
                  !ENV_NAME_PATTERN.test(draft.api_key_env.trim()) && (
                    <p
                      role="alert"
                      className="mt-1 font-mono text-[9px] text-b-amber"
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
                  style={INPUT_STYLE}
                />
              </div>
              <div className="flex items-end pb-1">
                <label className="flex cursor-pointer items-center gap-2 font-mono text-[11px] text-b-text-mid">
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(e) => updateDraft({ enabled: e.target.checked })}
                    className="accent-[rgb(var(--b-clay))]"
                  />
                  enabled
                </label>
              </div>
            </div>

            {validationError && (
              <div role="alert" className="mt-3 font-mono text-[10px] text-b-red">
                {validationError}
              </div>
            )}

            <div className="mt-4 flex items-center gap-2">
              <button
                type="submit"
                disabled={saveMutation.isPending}
                className="bg-b-clay px-3 py-1.5 font-mono text-[11px] font-semibold text-b-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                style={{ borderRadius: "var(--b-rad-sm)" }}
              >
                {saveMutation.isPending ? "saving…" : "save provider"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setAddType(null);
                  setDraft(null);
                  setValidationError(null);
                  saveMutation.reset();
                }}
                className="border border-b-line px-3 py-1.5 font-mono text-[11px] text-b-text-dim transition-colors hover:text-b-text"
                style={{ borderRadius: "var(--b-rad-sm)" }}
              >
                cancel
              </button>
            </div>
          </form>
        )}
      </div>

      {saveMutation.isError && (
        <div role="alert" className="mt-3 font-mono text-[10px] text-b-red">
          save failed: {saveMutation.error.message}
        </div>
      )}

      {/* ─── env-configured strip ─── */}
      {data && data.env_configured_providers.length > 0 && (
        <div className="mt-4 border-t border-b-line-soft pt-2.5 font-mono text-[9.5px] text-b-text-faint">
          configured via environment:{" "}
          <span className="text-b-text-dim">
            {data.env_configured_providers.join(", ")}
          </span>
        </div>
      )}
    </section>
  );
}
