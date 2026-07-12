import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { sendChat } from "../../api/client";
import type {
  ChatMessage, ChatRequest, ChatStreamEvent, ModelProbeResponse, ProbedModel,
} from "../../api/types";

// Chat playground — direct POST /api/chat probe for any model in the catalog.
// Unavailable/local models stay selectable on purpose: sending a message is
// how you find out whether a backend actually replies, so auth/quota/
// connection failures are surfaced prominently instead of filtered away.

const SECTION_LABEL =
  "font-mono text-[9px] uppercase tracking-[1.6px] text-b-text-faint";
const CAPTION_LABEL =
  "mb-1 font-mono text-[9px] uppercase tracking-[1.2px] text-b-text-faint";
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

interface PickerGroup {
  readonly name: string;
  readonly available: boolean;
  readonly models: readonly ProbedModel[];
}

/**
 * Group + sort probe models by provider — available providers first, models
 * by tier then id (mirrors groupProbeByProvider in ModelFinderPage).
 */
function groupModelsByProvider(probe: ModelProbeResponse | undefined): PickerGroup[] {
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
      models: list.slice().sort((a, b) => a.tier - b.tier || a.id.localeCompare(b.id)),
    }))
    .sort(
      (a, b) =>
        Number(b.available) - Number(a.available) ||
        b.models.length - a.models.length ||
        a.name.localeCompare(b.name),
    );
}

/** Parse the temperature field, falling back to the server default. */
function parseTemperature(raw: string): number {
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : DEFAULT_TEMPERATURE;
}

/** Drop a trailing empty assistant placeholder (stream failed pre-token). */
function withoutEmptyAssistantTail(messages: readonly ChatMessage[]): readonly ChatMessage[] {
  const last = messages[messages.length - 1];
  return last && last.role === "assistant" && last.content === ""
    ? messages.slice(0, -1)
    : messages;
}

/** Immutably append a streamed delta to the trailing assistant message. */
function withDelta(messages: readonly ChatMessage[], delta: string): readonly ChatMessage[] {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "assistant") return messages;
  return [...messages.slice(0, -1), { ...last, content: last.content + delta }];
}

function ChatMessageRow({
  message, streaming,
}: Readonly<{ message: ChatMessage; streaming: boolean }>) {
  const isUser = message.role === "user";
  const accent = isUser ? "rgb(var(--b-clay))" : "rgb(var(--b-green))";
  return (
    <div
      data-testid="chat-message"
      data-role={message.role}
      className={`border border-b-line-soft px-3 py-2 ${isUser ? "bg-b-bg2" : "bg-b-bg0"}`}
      style={{ borderRadius: "var(--b-rad-sm)", borderLeft: `2px solid ${accent}` }}
    >
      <div className="mb-1 flex items-center gap-2">
        <span
          className="border px-1.5 py-px font-mono text-[8.5px] uppercase tracking-[0.3px]"
          style={{ borderColor: accent, color: accent, borderRadius: "3px" }}
        >
          {message.role}
        </span>
        {streaming && <span aria-hidden="true" className={PULSE_DOT} />}
      </div>
      <div className="whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-b-text-mid">
        {message.content}
      </div>
    </div>
  );
}

interface ChatPlaygroundPanelProps {
  /** Probe from the page-level ["model-probe"] query (shared, not re-fetched). */
  probe: ModelProbeResponse | undefined;
  probeLoading: boolean;
}

/**
 * Direct model chat playground. Talks to POST /api/chat, which routes to the
 * picked model verbatim (no SmartModelRouter/tier selection), and streams the
 * reply token-by-token into the transcript.
 */
export default function ChatPlaygroundPanel({
  probe, probeLoading,
}: Readonly<ChatPlaygroundPanelProps>) {
  const [model, setModel] = useState("");
  const [temperature, setTemperature] = useState(String(DEFAULT_TEMPERATURE));
  const [messages, setMessages] = useState<readonly ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<PlaygroundError | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const groups = useMemo(() => groupModelsByProvider(probe), [probe]);
  const defaultModelId = useMemo(() => {
    const ordered = groups.flatMap((group) => group.models);
    return ordered.find((item) => item.available)?.id ?? ordered[0]?.id ?? "";
  }, [groups]);

  // Effective selection: an explicit pick sticks; until then the default
  // (first available model, else the first overall) applies as soon as the
  // probe arrives. Derived at render time so the select never sits on ""
  // while options exist — state adoption via effect would lag one frame.
  const effectiveModel = model !== "" ? model : defaultModelId;

  // Abort any in-flight stream when the panel unmounts (e.g. tab switch).
  useEffect(() => () => abortRef.current?.abort(), []);

  const failStream = (message: string, category: string | null) => {
    setMessages((prev) => withoutEmptyAssistantTail(prev));
    setError({ message, category });
    setStreaming(false);
  };

  const handleEvent = (event: ChatStreamEvent) => {
    if (event.type === "token") {
      setMessages((prev) => withDelta(prev, event.delta));
    } else if (event.type === "done") {
      setStreaming(false);
    } else {
      failStream(event.message, event.category);
    }
  };

  const handleSend = () => {
    const content = input.trim();
    if (content === "" || effectiveModel === "" || streaming) return;
    // Latch the model under test on first send: without this, a probe
    // refetch (rescan) could re-derive the default and silently retarget an
    // in-progress conversation to a different model.
    if (model === "") setModel(effectiveModel);
    const transcript: ChatMessage[] = [...messages, { role: "user", content }];
    const request: ChatRequest = {
      model: effectiveModel,
      messages: transcript,
      temperature: parseTemperature(temperature),
    };
    setMessages([...transcript, { role: "assistant", content: "" }]);
    setInput("");
    setError(null);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    sendChat(request, handleEvent, { signal: controller.signal })
      .then(() => {
        // Defensive: unlock if the server closed without a terminal frame.
        if (!controller.signal.aborted) setStreaming(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        failStream(err instanceof Error ? err.message : String(err), null);
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
  };

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1
          className="text-[24px] font-semibold text-b-text"
          style={{ fontFamily: "var(--b-font-heading)", letterSpacing: "-0.5px" }}
        >
          chat playground
        </h1>
        <p className="mt-1 max-w-3xl font-mono text-[11px] leading-5 text-b-text-dim">
          Talks straight to the picked model via POST /api/chat — no tier
          routing. Every catalog model is selectable, even without keys:
          sending a message is the probe, and failures surface below.
        </p>
      </div>

      {probe?.no_llm_mode && (
        <div
          className="border-b-amber/50 bg-b-bg1 p-3 font-mono text-[11px] text-b-amber"
          style={CARD_STYLE}
        >
          placeholder mode — replies are canned (AGENTIC_NO_LLM)
        </div>
      )}

      <div>
        <div className={`${SECTION_LABEL} mb-3`}>MODEL UNDER TEST · DIRECT ROUTE</div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[260px] flex-1">
            <div className={CAPTION_LABEL}>model</div>
            <select
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
                      {`${item.id}${item.available ? "" : " · no keys"}`}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          <div className="w-24">
            <div className={CAPTION_LABEL}>temp</div>
            <input
              type="number" step="0.1" min="0" max="2" aria-label="Temperature"
              value={temperature}
              onChange={(event) => setTemperature(event.target.value)}
              className={FIELD_CLASS} style={CONTROL_STYLE}
            />
          </div>
          <button
            type="button" onClick={handleClear}
            disabled={streaming || (messages.length === 0 && error === null)}
            className="btn-ghost disabled:cursor-not-allowed disabled:opacity-50"
          >
            clear
          </button>
        </div>
      </div>

      <div>
        <div className={`${SECTION_LABEL} mb-3 flex items-center gap-3`}>
          <span>
            TRANSCRIPT · {messages.length} message{messages.length === 1 ? "" : "s"}
          </span>
          {streaming && (
            <span className="flex items-center gap-[5px] font-mono text-[9px] normal-case tracking-normal text-b-green">
              <span aria-hidden="true" className={PULSE_DOT} /> streaming
            </span>
          )}
        </div>
        <div
          aria-live="polite" aria-relevant="additions text" aria-label="Chat transcript"
          className="flex max-h-[440px] min-h-[180px] flex-col gap-2 overflow-y-auto border-b-line bg-b-bg1 p-3"
          style={CARD_STYLE}
        >
          {messages.length === 0 && (
            <div className="m-auto font-mono text-[10px] text-b-text-faint">
              no messages yet — pick a model and send something
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
      </div>

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

      <div className="flex items-end gap-2">
        <textarea
          data-testid="chat-input" aria-label="Message" rows={2} value={input}
          onChange={(event) => setInput(event.target.value)} onKeyDown={handleKeyDown}
          placeholder="message the selected model — Enter sends, Shift+Enter breaks"
          className={`${FIELD_CLASS} resize-y`} style={CONTROL_STYLE}
        />
        {streaming && (
          <button
            type="button" data-testid="chat-stop" onClick={handleStop}
            className="btn-ghost"
          >
            stop
          </button>
        )}
        <button
          type="button" data-testid="chat-send" onClick={handleSend}
          className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
          disabled={streaming || input.trim() === "" || effectiveModel === ""}
        >
          send
        </button>
      </div>
    </div>
  );
}
