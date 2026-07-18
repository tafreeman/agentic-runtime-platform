import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Image, Paperclip, Send, Square, X } from "lucide-react";
import { sendChat } from "../../api/client";
import type {
  ChatImagePart,
  ChatMessage,
  ChatRequest,
  ChatStreamEvent,
  ModelProbeResponse,
  ProbedModel,
} from "../../api/types";
import { Button } from "../ui/button";
import {
  loadVerifications,
  recordVerification,
  type ModelVerification,
} from "../../lib/modelVerification";

// Chat playground — direct POST /api/chat probe for any model in the catalog.
// Unavailable/local models stay selectable on purpose: sending a message is
// how you find out whether a backend actually replies, so auth/quota/
// connection failures are surfaced prominently instead of filtered away.
// Terminal stream outcomes are persisted to the verification registry, which
// then drives picker ordering, default selection, and finder catalog badges.

const CARD_STYLE = { borderWidth: "var(--b-bw)", borderRadius: "var(--b-rad-lg)" } as const;
const CONTROL_STYLE = { borderWidth: "var(--b-bw)", borderRadius: "var(--b-rad-sm)" } as const;
const FIELD_CLASS =
  "w-full border border-solid border-b-line bg-b-bg0 px-2 py-1.5 font-mono text-[11px] text-b-text placeholder:text-b-text-faint focus:border-b-clay focus:outline-none";
const PULSE_DOT =
  "animate-b-pulse inline-block h-[5px] w-[5px] rounded-full bg-b-green";

/** Server-side default sampling temperature (contracts/chat.py). */
const DEFAULT_TEMPERATURE = 0.2;

interface PlaygroundError {
  readonly message: string;
  /** ErrorCode value from the error frame (e.g. "auth_error"), when present. */
  readonly category: string | null;
}

interface MediaAsset {
  readonly id: string;
  readonly name: string;
  readonly mimeType: "image/png" | "image/jpeg" | "image/webp" | "image/gif";
  readonly url: string;
  readonly size?: number;
}

interface PlaygroundMessage {
  readonly role: "system" | "user" | "assistant";
  readonly content: string;
  readonly media: readonly MediaAsset[];
}

const ACCEPTED_IMAGE_TYPES = new Set<MediaAsset["mimeType"]>([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
]);
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_ATTACHMENTS = 4;

interface PickerGroup {
  readonly name: string;
  readonly available: boolean;
  readonly models: readonly ProbedModel[];
}

type VerificationMap = Readonly<Record<string, ModelVerification>>;

/**
 * Only-use-working-models ordering inside a provider group: playground-
 * verified-ok first, then currently-running (loaded in memory), then tier,
 * then id — evidence of liveness beats static catalog order.
 */
function compareModels(
  a: ProbedModel,
  b: ProbedModel,
  verifications: VerificationMap,
): number {
  const aOk = verifications[a.id]?.status === "ok" ? 1 : 0;
  const bOk = verifications[b.id]?.status === "ok" ? 1 : 0;
  if (aOk !== bOk) return bOk - aOk;
  const aRunning = a.running ? 1 : 0;
  const bRunning = b.running ? 1 : 0;
  if (aRunning !== bRunning) return bRunning - aRunning;
  return a.tier - b.tier || a.id.localeCompare(b.id);
}

/**
 * Group + sort probe models by provider — available providers first, models
 * ordered by verified/running/tier/id (see compareModels).
 */
function groupModelsByProvider(
  probe: ModelProbeResponse | undefined,
  verifications: VerificationMap,
): PickerGroup[] {
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
      models: list.slice().sort((a, b) => compareModels(a, b, verifications)),
    }))
    .sort(
      (a, b) =>
        Number(b.available) - Number(a.available) ||
        b.models.length - a.models.length ||
        a.name.localeCompare(b.name),
    );
}

/** Option label with liveness / verification / credential suffixes. */
function optionLabel(
  item: ProbedModel,
  verification: ModelVerification | undefined,
): string {
  const parts = [item.id];
  if (item.running) parts.push("· live");
  if (verification?.status === "ok") parts.push("· ok");
  if (verification?.status === "error") parts.push("· failed");
  if (!item.available) parts.push("· no keys");
  return parts.join(" ");
}

/** Parse the temperature field, falling back to the server default. */
function parseTemperature(raw: string): number {
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : DEFAULT_TEMPERATURE;
}

/** Drop a trailing empty assistant placeholder (stream failed pre-token). */
function withoutEmptyAssistantTail(
  messages: readonly PlaygroundMessage[],
): readonly PlaygroundMessage[] {
  const last = messages[messages.length - 1];
  return last &&
    last.role === "assistant" &&
    last.content === "" &&
    last.media.length === 0
    ? messages.slice(0, -1)
    : messages;
}

/** Immutably append a streamed delta to the trailing assistant message. */
function withDelta(
  messages: readonly PlaygroundMessage[],
  delta: string,
): readonly PlaygroundMessage[] {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "assistant") return messages;
  return [...messages.slice(0, -1), { ...last, content: last.content + delta }];
}

function withMedia(
  messages: readonly PlaygroundMessage[],
  media: MediaAsset,
): readonly PlaygroundMessage[] {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "assistant") return messages;
  return [
    ...messages.slice(0, -1),
    { ...last, media: [...last.media, media] },
  ];
}

function toWireMessage(message: PlaygroundMessage): ChatMessage {
  if (message.media.length === 0) {
    return { role: message.role, content: message.content };
  }
  const images: ChatImagePart[] = message.media.map((asset) => ({
    type: "image_url",
    url: asset.url,
    detail: "auto",
  }));
  return {
    role: message.role,
    content: [
      ...(message.content ? [{ type: "text" as const, text: message.content }] : []),
      ...images,
    ],
  };
}

function readImage(file: File): Promise<MediaAsset> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.onload = () =>
      resolve({
        id: `${file.name}-${file.lastModified}-${file.size}`,
        name: file.name,
        mimeType: file.type as MediaAsset["mimeType"],
        url: String(reader.result),
        size: file.size,
      });
    reader.readAsDataURL(file);
  });
}

function ChatMessageRow({
  message, streaming,
}: Readonly<{ message: PlaygroundMessage; streaming: boolean }>) {
  const isUser = message.role === "user";
  return (
    <div
      data-testid="chat-message"
      data-role={message.role}
      className={`max-w-[88%] border px-4 py-3 ${
        isUser
          ? "ml-auto border-el-divider bg-el-subtle"
          : "mr-auto border-el-divider-soft bg-el-raised"
      }`}
      style={{ borderRadius: "var(--el-radius-lg)" }}
    >
      <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold text-el-muted">
        <span>{isUser ? "You" : "Model"}</span>
        {streaming && <span aria-hidden="true" className={PULSE_DOT} />}
      </div>
      {message.content && (
        <div className="whitespace-pre-wrap break-words text-[14px] leading-6 text-el-secondary">
          {message.content}
        </div>
      )}
      {message.media.length > 0 && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {message.media.map((asset) => (
            <figure key={asset.id} className="overflow-hidden border border-el-divider-soft bg-el-canvas">
              <img
                src={asset.url}
                alt={asset.name}
                className="max-h-80 w-full object-contain"
              />
              <figcaption className="truncate border-t border-el-divider-soft px-2 py-1 font-mono text-[10px] text-el-muted">
                {asset.name}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}

interface ChatPlaygroundPanelProps {
  /** Probe from the page-level ["model-probe"] query (shared, not re-fetched). */
  probe: ModelProbeResponse | undefined;
  probeLoading: boolean;
  /**
   * Deep-linked model id (?model= search param). Seeds the picker on mount —
   * safe as a mount-time initializer because the panel remounts per tab switch.
   */
  initialModel?: string;
  /** Probe query failure — surfaced inline so playground-tab failures are visible. */
  probeError?: Error | null;
}

/**
 * Direct model chat playground. Talks to POST /api/chat, which routes to the
 * picked model verbatim (no SmartModelRouter/tier selection), and streams the
 * reply token-by-token into the transcript.
 */
export default function ChatPlaygroundPanel({
  probe, probeLoading, initialModel = "", probeError = null,
}: Readonly<ChatPlaygroundPanelProps>) {
  const [model, setModel] = useState(initialModel);
  const [temperature, setTemperature] = useState(String(DEFAULT_TEMPERATURE));
  const [messages, setMessages] = useState<readonly PlaygroundMessage[]>([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<readonly MediaAsset[]>([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<PlaygroundError | null>(null);
  const [verifications, setVerifications] = useState<VerificationMap>(() =>
    loadVerifications(),
  );
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const groups = useMemo(
    () => groupModelsByProvider(probe, verifications),
    [probe, verifications],
  );

  // Default preference: most-recently-verified-ok model present in the probe,
  // then the first running (loaded) model, then the first with credentials,
  // then the first overall — strongest liveness evidence wins.
  const defaultModelId = useMemo(() => {
    const ordered = groups.flatMap((group) => group.models);
    const verifiedOk = ordered
      .filter((item) => verifications[item.id]?.status === "ok")
      .sort((a, b) =>
        (verifications[b.id]?.at ?? "").localeCompare(verifications[a.id]?.at ?? ""),
      );
    return (
      verifiedOk[0]?.id ??
      ordered.find((item) => item.running)?.id ??
      ordered.find((item) => item.available)?.id ??
      ordered[0]?.id ??
      ""
    );
  }, [groups, verifications]);

  // Effective selection: an explicit pick sticks; until then the default
  // applies as soon as the probe arrives. Derived at render time so the
  // select never sits on "" while options exist — state adoption via effect
  // would lag one frame.
  const effectiveModel = model !== "" ? model : defaultModelId;

  // In no-LLM mode every model "answers" via the deterministic placeholder,
  // so a done frame would fake-verify the whole catalog — skip recording.
  const verificationEnabled = !(probe?.no_llm_mode ?? false);

  // Abort any in-flight stream when the panel unmounts (e.g. tab switch).
  useEffect(() => () => abortRef.current?.abort(), []);

  const recordOutcome = (
    modelId: string,
    status: "ok" | "error",
    message?: string,
  ) => {
    if (!verificationEnabled) return;
    recordVerification(modelId, status, message);
    setVerifications(loadVerifications());
  };

  const failStream = (modelId: string, message: string, category: string | null) => {
    recordOutcome(modelId, "error", message);
    setMessages((prev) => withoutEmptyAssistantTail(prev));
    setError({ message, category });
    setStreaming(false);
  };

  const handleEvent = (modelId: string, event: ChatStreamEvent) => {
    if (event.type === "route") {
      // The Playground uses the explicit-model overload, but tolerate routed
      // clients sharing this handler without treating routing metadata as an
      // inference failure.
      return;
    } else if (event.type === "token") {
      setMessages((prev) => withDelta(prev, event.delta));
    } else if (event.type === "media") {
      setMessages((prev) =>
        withMedia(prev, {
          id: `${modelId}-${event.url.slice(-32)}`,
          name: event.alt,
          mimeType: event.mime_type,
          url: event.url,
        }),
      );
    } else if (event.type === "done") {
      // A completed stream is the strongest liveness signal the UI has.
      recordOutcome(modelId, "ok");
      setStreaming(false);
    } else {
      failStream(modelId, event.message, event.category);
    }
  };

  const handleSend = () => {
    const content = input.trim();
    if (
      (content === "" && attachments.length === 0) ||
      effectiveModel === "" ||
      streaming
    )
      return;
    // Latch the model under test on first send: without this, a probe
    // refetch (rescan) could re-derive the default and silently retarget an
    // in-progress conversation to a different model.
    if (model === "") setModel(effectiveModel);
    const transcript: PlaygroundMessage[] = [
      ...messages,
      { role: "user", content, media: attachments },
    ];
    const request: ChatRequest = {
      model: effectiveModel,
      messages: transcript.map(toWireMessage),
      temperature: parseTemperature(temperature),
    };
    setMessages([
      ...transcript,
      { role: "assistant", content: "", media: [] },
    ]);
    setInput("");
    setAttachments([]);
    setAttachmentError(null);
    setError(null);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    sendChat(request, (event) => handleEvent(request.model, event), {
      signal: controller.signal,
    })
      .then(() => {
        // Defensive: unlock if the server closed without a terminal frame.
        if (!controller.signal.aborted) setStreaming(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        failStream(
          request.model,
          err instanceof Error ? err.message : String(err),
          null,
        );
      });
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const handleStop = () => {
    // A stalled provider is this tool's mainline scenario — the user must be
    // able to bail out without losing the transcript. Abort the fetch (the
    // rejection handler sees signal.aborted and stays silent), keep any
    // partial tokens, drop an all-empty assistant bubble, and unlock.
    abortRef.current?.abort();
    setMessages((prev) => withoutEmptyAssistantTail(prev));
    setStreaming(false);
  };

  const handleClear = () => {
    setMessages([]);
    setError(null);
    setInput("");
    setAttachments([]);
    setAttachmentError(null);
  };

  const handleImages = async (files: FileList | null) => {
    if (!files) return;
    const candidates = Array.from(files);
    if (attachments.length + candidates.length > MAX_ATTACHMENTS) {
      setAttachmentError(`Attach at most ${MAX_ATTACHMENTS} images per message.`);
      return;
    }
    const invalid = candidates.find(
      (file) =>
        !ACCEPTED_IMAGE_TYPES.has(file.type as MediaAsset["mimeType"]) ||
        file.size > MAX_IMAGE_BYTES,
    );
    if (invalid) {
      setAttachmentError(
        `${invalid.name} must be a PNG, JPEG, WebP, or GIF no larger than 5 MiB.`,
      );
      return;
    }
    try {
      const loaded = await Promise.all(candidates.map(readImage));
      setAttachments((current) => [...current, ...loaded]);
      setAttachmentError(null);
    } catch (readError) {
      setAttachmentError(
        readError instanceof Error ? readError.message : "Could not read image.",
      );
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // Why is send a no-op right now? Rendered as a dim status line so Enter
  // "doing nothing" during a slow probe or a hung stream is explained.
  const blockedHint = streaming
    ? "streaming — press stop first"
    : effectiveModel === ""
      ? probeLoading
        ? "probing providers…"
        : "no model selected"
      : null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
      <div className="max-w-3xl">
        <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-el-accent-strong">
          <Image className="h-4 w-4" aria-hidden="true" />
          Direct model session
        </div>
        <h1
          className="font-display text-[36px] font-medium leading-[1.1] text-el-ink"
        >
          Chat playground
        </h1>
        <p className="mt-3 max-w-2xl text-[14px] leading-6 text-el-muted">
          Talk directly to one model without tier routing. Stream text, attach
          raster images for vision-capable models, and display image output
          when the provider returns it. A completed response is recorded as
          liveness evidence.
        </p>
      </div>

      {probeError && (
        <div
          role="alert" data-testid="playground-probe-error"
          className="border-b-red/40 bg-b-bg1 p-3 font-mono text-[11px] text-b-red"
          style={CARD_STYLE}
        >
          probe failed: {probeError.message}
        </div>
      )}

      {probe?.no_llm_mode && (
        <div
          className="border-b-amber/50 bg-b-bg1 p-3 font-mono text-[11px] text-b-amber"
          style={CARD_STYLE}
        >
          placeholder mode — replies are canned (AGENTIC_NO_LLM)
        </div>
      )}

      <section className="border-y border-el-divider py-5" aria-label="Session configuration">
        <div className="mb-4 text-[11px] font-semibold uppercase tracking-[0.12em] text-el-muted">
          Session configuration
        </div>
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-[260px] flex-1">
            <label htmlFor="chat-model-picker" className="mb-2 block text-[12px] font-semibold text-el-secondary">Model</label>
            <select
              id="chat-model-picker"
              data-testid="chat-model-picker" aria-label="Playground model"
              value={effectiveModel}
              onChange={(event) => setModel(event.target.value)}
              className={FIELD_CLASS} style={CONTROL_STYLE}
            >
              {groups.length === 0 && (
                <option value="">
                  {probeLoading ? "probing models…" : "no models discovered"}
                </option>
              )}
              {groups.map((group) => (
                <optgroup key={group.name} label={group.name}>
                  {group.models.map((item) => (
                    <option key={item.id} value={item.id}>
                      {optionLabel(item, verifications[item.id])}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          <div className="w-24">
            <label htmlFor="chat-temperature" className="mb-2 block text-[12px] font-semibold text-el-secondary">Temperature</label>
            <input
              id="chat-temperature"
              type="number" step="0.1" min="0" max="2" aria-label="Temperature"
              value={temperature}
              onChange={(event) => setTemperature(event.target.value)}
              className={FIELD_CLASS} style={CONTROL_STYLE}
            />
          </div>
          <Button
            variant="outline"
            aria-label="clear"
            type="button" onClick={handleClear}
            disabled={streaming || (messages.length === 0 && error === null)}
          >
            Clear session
          </Button>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-el-muted">
          <span>
            Transcript · {messages.length} message{messages.length === 1 ? "" : "s"}
          </span>
          {streaming && (
            <span className="flex items-center gap-[5px] font-mono text-[9px] normal-case tracking-normal text-b-green">
              <span aria-hidden="true" className={PULSE_DOT} /> streaming
            </span>
          )}
        </div>
        <div
          aria-live="polite" aria-relevant="additions text" aria-label="Chat transcript"
          className="flex max-h-[520px] min-h-[280px] flex-col gap-3 overflow-y-auto border border-el-divider bg-el-surface p-4 sm:p-6"
          style={{ borderRadius: "var(--el-radius-lg)" }}
        >
          {messages.length === 0 && (
            <div className="m-auto font-mono text-[10px] text-b-text-faint">
              Start with a question or attach an image for a vision-capable model.
            </div>
          )}
          {messages.map((message, index) => (
            <ChatMessageRow
              key={`${index}-${message.role}`} message={message}
              streaming={
                streaming && index === messages.length - 1 && message.role === "assistant"
              }
            />
          ))}
        </div>
      </section>

      {error && (
        <div
          role="alert" data-testid="chat-error"
          className="flex flex-wrap items-center gap-2 border-b-red/60 bg-b-bg1 p-3 font-mono text-[11px] text-b-red"
          style={CARD_STYLE}
        >
          <span className="font-semibold uppercase tracking-[0.5px]">stream failed</span>
          {error.category && (
            <span
              className="border border-b-red/60 px-1.5 py-px text-[8.5px] uppercase tracking-[0.3px]"
              style={{ borderRadius: "3px" }}
            >
              {error.category}
            </span>
          )}
          <span className="min-w-0 break-words">{error.message}</span>
        </div>
      )}

      <section
        className="border border-el-divider bg-el-raised p-3 shadow-[var(--el-shadow-raised)]"
        style={{ borderRadius: "var(--el-radius-lg)" }}
        aria-label="Message composer"
      >
        {attachments.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2" aria-label="Attached images">
            {attachments.map((asset) => (
              <div
                key={asset.id}
                className="group relative h-20 w-24 overflow-hidden border border-el-divider bg-el-canvas"
              >
                <img
                  src={asset.url}
                  alt={asset.name}
                  className="h-full w-full object-cover"
                />
                <button
                  type="button"
                  aria-label={`Remove ${asset.name}`}
                  onClick={() =>
                    setAttachments((current) =>
                      current.filter((item) => item.id !== asset.id),
                    )
                  }
                  className="absolute right-1 top-1 grid h-6 w-6 place-items-center bg-el-action text-el-raised"
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
                <span className="absolute inset-x-0 bottom-0 truncate bg-el-action/80 px-1 py-0.5 text-[9px] text-el-raised">
                  {asset.name}
                </span>
              </div>
            ))}
          </div>
        )}
        {attachmentError && (
          <p className="mb-2 text-[12px] text-el-danger" role="alert">
            {attachmentError}
          </p>
        )}
        <textarea
          data-testid="chat-input"
          aria-label="Message"
          rows={3}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question or describe what to inspect in the attached image…"
          className="min-h-[88px] w-full resize-y border-0 bg-transparent px-2 py-2 text-[14px] leading-6 text-el-ink placeholder:text-el-faint focus:outline-none"
        />
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-el-divider-soft pt-3">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            className="sr-only"
            aria-label="Attach images"
            onChange={(event) => void handleImages(event.target.files)}
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={streaming || attachments.length >= MAX_ATTACHMENTS}
          >
            <Paperclip className="h-4 w-4" aria-hidden="true" />
            Attach image
          </Button>
          <span className="text-[11px] text-el-muted">
            PNG, JPEG, WebP, or GIF · 5 MiB each
          </span>
          <div className="ml-auto flex gap-2">
            {streaming && (
              <Button
                type="button"
                variant="outline"
                data-testid="chat-stop"
                onClick={handleStop}
              >
                <Square className="h-3.5 w-3.5" aria-hidden="true" />
                Stop
              </Button>
            )}
            <Button
              type="button"
              data-testid="chat-send"
              onClick={handleSend}
              disabled={
                streaming ||
                (input.trim() === "" && attachments.length === 0) ||
                effectiveModel === ""
              }
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              Send
            </Button>
          </div>
        </div>
      </section>

      {blockedHint && (
        <div
          data-testid="chat-blocked-hint"
          className="-mt-5 text-[11px] text-el-muted"
        >
          Send blocked — {blockedHint}
        </div>
      )}
    </div>
  );
}
