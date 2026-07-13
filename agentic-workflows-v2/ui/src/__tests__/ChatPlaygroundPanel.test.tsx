import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatPlaygroundPanel from "../components/models/ChatPlaygroundPanel";
import {
  VERIFICATION_STORAGE_KEY,
  loadVerifications,
  type ModelVerification,
} from "../lib/modelVerification";
import type {
  ChatRequest,
  ChatStreamEvent,
  ModelProbeResponse,
} from "../api/types";

const mockSendChat = vi.fn();

vi.mock("../api/client", async () => {
  const actual = await vi.importActual("../api/client");
  return {
    ...actual,
    sendChat: (...args: unknown[]) => mockSendChat(...args),
  };
});

type ChatEventHandler = (event: ChatStreamEvent) => void;

function makeChatProbe(
  overrides: Partial<ModelProbeResponse> = {},
): ModelProbeResponse {
  return {
    available_providers: ["anthropic", "ollama"],
    unavailable_providers: ["openai"],
    tier_defaults: { "1": "anthropic:claude-haiku-4-5" },
    no_llm_mode: false,
    models: [
      // Deliberately list an unavailable model FIRST so the default-selection
      // assertion proves "first available", not "first in raw probe order".
      { id: "openai:gpt-4o", provider: "openai", tier: 2, available: false },
      {
        id: "anthropic:claude-haiku-4-5",
        provider: "anthropic",
        tier: 1,
        available: true,
      },
      { id: "ollama:qwen3:8b", provider: "ollama", tier: 2, available: true },
    ],
    ...overrides,
  };
}

function renderPanel(
  probe: ModelProbeResponse | undefined,
  probeLoading = false,
  extraProps: { initialModel?: string; probeError?: Error | null } = {},
) {
  return render(
    <ChatPlaygroundPanel
      probe={probe}
      probeLoading={probeLoading}
      {...extraProps}
    />,
  );
}

/** Seed the verification registry with explicit timestamps (recency-safe). */
function seedVerifications(entries: Record<string, ModelVerification>): void {
  localStorage.setItem(VERIFICATION_STORAGE_KEY, JSON.stringify(entries));
}

async function pickerWithDefault(expected: string): Promise<HTMLSelectElement> {
  const picker = screen.getByTestId("chat-model-picker") as HTMLSelectElement;
  await waitFor(() => expect(picker.value).toBe(expected));
  return picker;
}

describe("ChatPlaygroundPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockSendChat.mockResolvedValue(undefined);
  });

  it("groups models per provider and defaults to the first available model", async () => {
    renderPanel(makeChatProbe());

    const picker = await pickerWithDefault("anthropic:claude-haiku-4-5");

    // One optgroup per provider, available providers first.
    const groupLabels = Array.from(picker.querySelectorAll("optgroup")).map(
      (group) => group.label,
    );
    expect(groupLabels).toEqual(["anthropic", "ollama", "openai"]);

    // Unavailable models stay selectable — testing them is the point — but
    // carry the "no keys" marker in their label.
    expect(
      screen.getByRole("option", { name: "openai:gpt-4o · no keys" }),
    ).toBeInTheDocument();
  });

  it("falls back to the first catalog model when nothing is available", async () => {
    renderPanel(
      makeChatProbe({
        available_providers: [],
        unavailable_providers: ["ollama", "openai"],
        models: [
          { id: "openai:gpt-4o", provider: "openai", tier: 2, available: false },
          { id: "ollama:qwen3:8b", provider: "ollama", tier: 2, available: false },
        ],
      }),
    );

    // Grouped order (equal counts, none available) is alphabetical, so the
    // first catalog model is ollama's.
    await pickerWithDefault("ollama:qwen3:8b");
  });

  it("sends the typed message and streams the reply into an assistant row", async () => {
    mockSendChat.mockImplementation(
      async (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({ type: "token", delta: "Hel" });
        onEvent({ type: "token", delta: "lo" });
        onEvent({ type: "done", model: "anthropic:claude-haiku-4-5" });
      },
    );
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "say hi" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() =>
      expect(screen.getAllByTestId("chat-message")).toHaveLength(2),
    );
    const rows = screen.getAllByTestId("chat-message");
    expect(rows[0]).toHaveAttribute("data-role", "user");
    expect(rows[0]).toHaveTextContent("say hi");
    expect(rows[1]).toHaveAttribute("data-role", "assistant");
    await waitFor(() => expect(rows[1]).toHaveTextContent("Hello"));

    expect(mockSendChat).toHaveBeenCalledTimes(1);
    const request = mockSendChat.mock.calls[0]?.[0] as ChatRequest;
    expect(request.model).toBe("anthropic:claude-haiku-4-5");
    expect(request.temperature).toBe(0.2);
    expect(request.messages).toEqual([{ role: "user", content: "say hi" }]);

    // Stream finished — typing again re-enables send.
    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "again" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("chat-send")).not.toBeDisabled(),
    );
  });

  it("surfaces in-stream error frames and drops the empty assistant bubble", async () => {
    mockSendChat.mockImplementation(
      async (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({
          type: "error",
          message: "provider rejected the API key",
          category: "auth_error",
        });
      },
    );
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "hello?" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));

    const alert = await screen.findByTestId("chat-error");
    expect(alert).toHaveTextContent("auth_error");
    expect(alert).toHaveTextContent("provider rejected the API key");

    // No tokens arrived, so the placeholder assistant row is dropped.
    const rows = screen.getAllByTestId("chat-message");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute("data-role", "user");

    // Composer unlocks for a retry.
    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "retry" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("chat-send")).not.toBeDisabled(),
    );
  });

  it("keeps partial text when the stream errors mid-reply", async () => {
    mockSendChat.mockImplementation(
      async (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({ type: "token", delta: "partial reply" });
        onEvent({
          type: "error",
          message: "connection reset",
          category: "transient",
        });
      },
    );
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "keep going" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));

    const alert = await screen.findByTestId("chat-error");
    expect(alert).toHaveTextContent("connection reset");
    const rows = screen.getAllByTestId("chat-message");
    expect(rows).toHaveLength(2);
    expect(rows[1]).toHaveTextContent("partial reply");
  });

  it("shows the thrown message when the chat request itself fails", async () => {
    mockSendChat.mockRejectedValue(new Error("API 502: bad gateway"));
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "anyone there?" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));

    const alert = await screen.findByTestId("chat-error");
    expect(alert).toHaveTextContent("API 502: bad gateway");
    // Only the user turn survives — the empty assistant bubble is dropped.
    expect(screen.getAllByTestId("chat-message")).toHaveLength(1);
  });

  it("shows the placeholder-mode banner when the probe reports no-LLM mode", () => {
    renderPanel(makeChatProbe({ no_llm_mode: true }));

    expect(
      screen.getByText(/placeholder mode — replies are canned \(AGENTIC_NO_LLM\)/),
    ).toBeInTheDocument();
  });

  it("omits the placeholder banner in normal LLM mode", () => {
    renderPanel(makeChatProbe());

    expect(screen.queryByText(/placeholder mode/)).not.toBeInTheDocument();
  });

  it("sends the full running transcript on the second turn", async () => {
    mockSendChat.mockImplementation(
      async (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({ type: "token", delta: "Hi!" });
        onEvent({ type: "done", model: "anthropic:claude-haiku-4-5" });
      },
    );
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "first" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));
    await waitFor(() =>
      expect(screen.getAllByTestId("chat-message")).toHaveLength(2),
    );

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "second" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("chat-send")).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByTestId("chat-send"));
    await waitFor(() =>
      expect(screen.getAllByTestId("chat-message")).toHaveLength(4),
    );

    expect(mockSendChat).toHaveBeenCalledTimes(2);
    const second = mockSendChat.mock.calls[1]?.[0] as ChatRequest;
    expect(second.messages).toEqual([
      { role: "user", content: "first" },
      { role: "assistant", content: "Hi!" },
      { role: "user", content: "second" },
    ]);
  });

  it("lets you probe an unavailable model with a custom temperature", async () => {
    mockSendChat.mockImplementation(
      async (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({
          type: "error",
          message: "no API key configured for openai",
          category: "auth_error",
        });
      },
    );
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-model-picker"), {
      target: { value: "openai:gpt-4o" },
    });
    fireEvent.change(screen.getByLabelText("Temperature"), {
      target: { value: "1.5" },
    });
    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "ping" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));

    await screen.findByTestId("chat-error");
    const request = mockSendChat.mock.calls[0]?.[0] as ChatRequest;
    expect(request.model).toBe("openai:gpt-4o");
    expect(request.temperature).toBe(1.5);
  });

  it("clear resets the transcript and the error banner", async () => {
    mockSendChat.mockRejectedValue(new Error("boom"));
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "will fail" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));
    await screen.findByTestId("chat-error");

    fireEvent.click(screen.getByRole("button", { name: "clear" }));

    expect(screen.queryByTestId("chat-error")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId("chat-message")).toHaveLength(0);
  });

  it("disables send while the probe is still loading", () => {
    renderPanel(undefined, true);

    expect(
      screen.getByRole("option", { name: "probing models…" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "hi" },
    });
    expect(screen.getByTestId("chat-send")).toBeDisabled();
    expect(mockSendChat).not.toHaveBeenCalled();
  });

  it("stop aborts a stalled stream, keeps partial text, and unlocks", async () => {
    let capturedSignal: AbortSignal | undefined;
    mockSendChat.mockImplementation(
      (
        _request: ChatRequest,
        onEvent: ChatEventHandler,
        options?: { signal?: AbortSignal },
      ) => {
        capturedSignal = options?.signal;
        onEvent({ type: "token", delta: "partial before stall" });
        // Stalled provider: the promise never settles on its own.
        return new Promise<void>(() => {});
      },
    );
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "probe a flaky provider" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));
    const stop = await screen.findByTestId("chat-stop");

    fireEvent.click(stop);

    expect(capturedSignal?.aborted).toBe(true);
    await waitFor(() =>
      expect(screen.queryByTestId("chat-stop")).not.toBeInTheDocument(),
    );
    // Partial tokens survive the cancel; no error banner appears.
    const rows = screen.getAllByTestId("chat-message");
    expect(rows[1]).toHaveTextContent("partial before stall");
    expect(screen.queryByTestId("chat-error")).not.toBeInTheDocument();
    // Composer is unlocked for the next turn.
    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "again" },
    });
    expect(screen.getByTestId("chat-send")).not.toBeDisabled();
  });

  it("latches the model on first send so a probe refresh cannot retarget the transcript", async () => {
    mockSendChat.mockImplementation(
      async (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({ type: "done", model: "anthropic:claude-haiku-4-5" });
      },
    );
    const { rerender } = renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "first turn" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));
    await waitFor(() => expect(mockSendChat).toHaveBeenCalledTimes(1));

    // A rescan surfaces a new model that now sorts as the computed default…
    rerender(
      <ChatPlaygroundPanel
        probe={makeChatProbe({
          models: [
            {
              id: "ollama:new-hot-model",
              provider: "ollama",
              tier: 1,
              available: true,
            },
            ...makeChatProbe().models,
          ],
        })}
        probeLoading={false}
      />,
    );

    // …but the conversation's model under test stays latched.
    expect(
      (screen.getByTestId("chat-model-picker") as HTMLSelectElement).value,
    ).toBe("anthropic:claude-haiku-4-5");
  });

  it("sends on Enter but not on Shift+Enter", async () => {
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    const input = screen.getByTestId("chat-input");
    fireEvent.change(input, { target: { value: "via keyboard" } });

    // Shift+Enter is a line break — no request goes out.
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(mockSendChat).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(mockSendChat).toHaveBeenCalledTimes(1));
    const request = mockSendChat.mock.calls[0]?.[0] as ChatRequest;
    expect(request.messages).toEqual([
      { role: "user", content: "via keyboard" },
    ]);
  });

  it("explains the blocked send while the probe is still loading", () => {
    renderPanel(undefined, true);

    expect(screen.getByTestId("chat-blocked-hint")).toHaveTextContent(
      "probing providers…",
    );
  });

  it("explains the blocked send when the probe found no models", () => {
    renderPanel(
      makeChatProbe({
        available_providers: [],
        unavailable_providers: [],
        models: [],
      }),
      false,
    );

    expect(screen.getByTestId("chat-blocked-hint")).toHaveTextContent(
      "no model selected",
    );
  });

  it("explains the blocked send while a stream is in flight, then clears", async () => {
    mockSendChat.mockImplementation(
      (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({ type: "token", delta: "…" });
        // Stalled provider: promise never settles on its own.
        return new Promise<void>(() => {});
      },
    );
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    // A sendable composer shows no hint.
    expect(screen.queryByTestId("chat-blocked-hint")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "hang" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));

    expect(await screen.findByTestId("chat-blocked-hint")).toHaveTextContent(
      "streaming — press stop first",
    );

    fireEvent.click(screen.getByTestId("chat-stop"));
    await waitFor(() =>
      expect(screen.queryByTestId("chat-blocked-hint")).not.toBeInTheDocument(),
    );
  });

  it("prefers a running model over a merely-available one as the default", async () => {
    renderPanel(
      makeChatProbe({
        models: [
          { id: "openai:gpt-4o", provider: "openai", tier: 2, available: false },
          {
            id: "anthropic:claude-haiku-4-5",
            provider: "anthropic",
            tier: 1,
            available: true,
          },
          {
            id: "ollama:qwen3:8b",
            provider: "ollama",
            tier: 2,
            available: true,
            running: true,
          },
        ],
      }),
    );

    // anthropic sorts first among available providers, but the loaded-in-
    // memory ollama model is the stronger liveness signal.
    await pickerWithDefault("ollama:qwen3:8b");
  });

  it("prefers the most-recently-verified-ok model over running/available", async () => {
    seedVerifications({
      "anthropic:claude-haiku-4-5": {
        status: "ok",
        at: "2026-07-12T10:00:00.000Z",
      },
      "openai:gpt-4o": { status: "ok", at: "2026-07-13T09:00:00.000Z" },
    });
    renderPanel(
      makeChatProbe({
        models: [
          // openai has no keys yet verified ok most recently — it wins.
          { id: "openai:gpt-4o", provider: "openai", tier: 2, available: false },
          {
            id: "anthropic:claude-haiku-4-5",
            provider: "anthropic",
            tier: 1,
            available: true,
          },
          {
            id: "ollama:qwen3:8b",
            provider: "ollama",
            tier: 2,
            available: true,
            running: true,
          },
        ],
      }),
    );

    await pickerWithDefault("openai:gpt-4o");
  });

  it("labels options with live / ok / failed / no-keys suffixes", async () => {
    seedVerifications({
      "anthropic:claude-haiku-4-5": {
        status: "ok",
        at: "2026-07-13T09:00:00.000Z",
      },
      "openai:gpt-4o": {
        status: "error",
        at: "2026-07-13T09:01:00.000Z",
        message: "auth failed",
      },
    });
    renderPanel(
      makeChatProbe({
        models: [
          { id: "openai:gpt-4o", provider: "openai", tier: 2, available: false },
          {
            id: "anthropic:claude-haiku-4-5",
            provider: "anthropic",
            tier: 1,
            available: true,
          },
          {
            id: "ollama:qwen3:8b",
            provider: "ollama",
            tier: 2,
            available: true,
            running: true,
          },
        ],
      }),
    );
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    expect(
      screen.getByRole("option", { name: "ollama:qwen3:8b · live" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "anthropic:claude-haiku-4-5 · ok" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "openai:gpt-4o · failed · no keys" }),
    ).toBeInTheDocument();
  });

  it("preselects the deep-linked initialModel over the computed default", async () => {
    renderPanel(makeChatProbe(), false, { initialModel: "openai:gpt-4o" });

    const picker = screen.getByTestId("chat-model-picker") as HTMLSelectElement;
    await waitFor(() => expect(picker.value).toBe("openai:gpt-4o"));
  });

  it("records a verified-ok outcome when the stream completes", async () => {
    mockSendChat.mockImplementation(
      async (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({ type: "token", delta: "pong" });
        onEvent({ type: "done", model: "anthropic:claude-haiku-4-5" });
      },
    );
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "ping" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() =>
      expect(
        loadVerifications()["anthropic:claude-haiku-4-5"]?.status,
      ).toBe("ok"),
    );
  });

  it("records a failed outcome with the message on an error frame", async () => {
    mockSendChat.mockImplementation(
      async (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({
          type: "error",
          message: "provider rejected the API key",
          category: "auth_error",
        });
      },
    );
    renderPanel(makeChatProbe());
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "hello?" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));
    await screen.findByTestId("chat-error");

    expect(loadVerifications()["anthropic:claude-haiku-4-5"]).toMatchObject({
      status: "error",
      message: "provider rejected the API key",
    });
  });

  it("does not record verifications in no-LLM placeholder mode", async () => {
    mockSendChat.mockImplementation(
      async (_request: ChatRequest, onEvent: ChatEventHandler) => {
        onEvent({ type: "token", delta: "canned" });
        onEvent({ type: "done", model: "anthropic:claude-haiku-4-5" });
      },
    );
    renderPanel(makeChatProbe({ no_llm_mode: true }));
    await pickerWithDefault("anthropic:claude-haiku-4-5");

    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "ping" },
    });
    fireEvent.click(screen.getByTestId("chat-send"));
    await waitFor(() =>
      expect(screen.getAllByTestId("chat-message")).toHaveLength(2),
    );

    // Placeholder replies would fake-verify the whole catalog.
    expect(loadVerifications()).toEqual({});
  });

  it("surfaces a page-level probe failure inside the playground", () => {
    renderPanel(undefined, false, {
      probeError: new Error("API 500: probe exploded"),
    });

    const alert = screen.getByTestId("playground-probe-error");
    expect(alert).toHaveTextContent("probe failed: API 500: probe exploded");
  });
});
