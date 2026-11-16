import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { ModelProbeResponse } from "../api/types";
import ProviderProbeList from "../components/models/ProviderProbeList";

// Keep the list off the network: the health check is only read for the
// disabled-load hint, which these tests do not exercise.
vi.mock("../hooks/useApiAvailability", () => ({
  useApiAvailability: () => ({
    apiDown: false,
    checking: false,
    reason: undefined,
  }),
}));

const PROBE: ModelProbeResponse = {
  available_providers: ["anthropic", "ollama", "openrouter"],
  unavailable_providers: ["openai"],
  tier_defaults: {},
  no_llm_mode: false,
  models: [
    {
      id: "ollama:llama3.2",
      provider: "ollama",
      tier: 1,
      available: true,
      price_label: "local",
      price_reason: "runs on this machine",
    },
    {
      id: "openrouter:free-model",
      provider: "openrouter",
      tier: 1,
      available: true,
      price_label: "free",
      price_reason: "both prices are 0",
    },
    {
      id: "anthropic:claude-sonnet",
      provider: "anthropic",
      tier: 2,
      available: true,
      price_label: "paid",
      price_reason: "a price is above 0",
    },
    {
      id: "anthropic:claude-mystery",
      provider: "anthropic",
      tier: 3,
      available: true,
      price_label: "unknown",
      price_reason: "no price listed",
    },
    // Older probe response: no price fields at all.
    { id: "openai:gpt-4o", provider: "openai", tier: 2, available: false },
  ],
};

/** The same catalog as an older backend returns it: no price fields. */
const UNLABELLED: ModelProbeResponse = {
  ...PROBE,
  models: PROBE.models.map((model) => ({
    id: model.id,
    provider: model.provider,
    tier: model.tier,
    available: model.available,
  })),
};

function renderList(initial: ModelProbeResponse | undefined = PROBE) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const ui = (probe: ModelProbeResponse | undefined) => (
    <QueryClientProvider client={queryClient}>
      <ProviderProbeList
        probe={probe}
        probing={false}
        probeError={null}
        onOpenInPlayground={vi.fn()}
      />
    </QueryClientProvider>
  );
  const utils = render(ui(initial));
  return {
    ...utils,
    rerenderProbe: (probe: ModelProbeResponse | undefined) =>
      utils.rerender(ui(probe)),
  };
}

// The accordion keeps one provider open at a time, so each test opens the
// provider it inspects.
function expandProvider(name: string) {
  fireEvent.click(screen.getByTestId(`provider-row-${name}`));
}

function toggle() {
  return screen.getByRole("button", { name: "Free and local only" });
}

function count() {
  return screen.getByTestId("catalog-search-count");
}

describe("ProviderProbeList price pills", () => {
  it("shows Local and Free after the model id", () => {
    renderList();

    expandProvider("ollama");
    expect(screen.getByText("Local")).toHaveClass(
      "bg-el-success-soft",
      "text-el-success",
    );

    expandProvider("openrouter");
    expect(screen.getByText("Free")).toHaveClass(
      "bg-el-success-soft",
      "text-el-success",
    );
  });

  it("shows Paid and a dashed Price unknown for the anthropic models", () => {
    renderList();
    expandProvider("anthropic");

    expect(screen.getByText("Paid")).toHaveClass(
      "bg-el-subtle",
      "text-el-secondary",
    );
    expect(screen.getByText("Price unknown")).toHaveClass(
      "border-dashed",
      "text-el-muted",
    );
  });

  it("shows Price unknown for a model with no price field", () => {
    renderList();
    expandProvider("openai");

    expect(screen.getByText("Price unknown")).toBeInTheDocument();
    // No reason to give, so the title is the bare label.
    expect(screen.getByTitle("Price unknown")).toBeInTheDocument();
  });

  it("puts the reason in the title and a screen-reader suffix", () => {
    renderList();
    expandProvider("openrouter");

    expect(screen.getByTitle("Free: both prices are 0")).toBeInTheDocument();
    expect(screen.getByText(": both prices are 0")).toHaveClass("sr-only");
  });

  it("keeps the reason on an unknown label", () => {
    renderList();
    expandProvider("anthropic");

    expect(
      screen.getByTitle("Price unknown: no price listed"),
    ).toBeInTheDocument();
  });
});

describe("ProviderProbeList free and local filter", () => {
  it("starts unpressed with the full count", () => {
    renderList();

    expect(toggle()).toHaveAttribute("aria-pressed", "false");
    expect(toggle()).toBeEnabled();
    expect(count()).toHaveTextContent("5 / 5 models");
  });

  it("keeps only free and local models and shows the filtered count", () => {
    renderList();
    fireEvent.click(toggle());

    expect(toggle()).toHaveAttribute("aria-pressed", "true");
    expect(count()).toHaveTextContent("Showing 2 of 5 models");

    expandProvider("ollama");
    expect(screen.getByText("ollama:llama3.2")).toBeInTheDocument();
    expandProvider("openrouter");
    expect(screen.getByText("openrouter:free-model")).toBeInTheDocument();
  });

  it("drops providers left with no free or local models", () => {
    renderList();
    fireEvent.click(toggle());

    expect(screen.queryByTestId("provider-row-anthropic")).not.toBeInTheDocument();
    expect(screen.queryByTestId("provider-row-openai")).not.toBeInTheDocument();
    expect(screen.getByTestId("provider-row-ollama")).toBeInTheDocument();
    expect(screen.getByTestId("provider-row-openrouter")).toBeInTheDocument();
  });

  it("restores the full list when toggled off", () => {
    renderList();
    fireEvent.click(toggle());
    fireEvent.click(toggle());

    expect(toggle()).toHaveAttribute("aria-pressed", "false");
    expect(count()).toHaveTextContent("5 / 5 models");
    expect(screen.getByTestId("provider-row-anthropic")).toBeInTheDocument();
  });

  it("combines with the search box", () => {
    renderList();
    fireEvent.click(toggle());
    fireEvent.change(screen.getByLabelText("Search catalog models"), {
      target: { value: "free-model" },
    });

    expect(count()).toHaveTextContent("Showing 1 of 5 models");
  });

  it("shows an empty state when the filter leaves nothing", () => {
    renderList({
      ...PROBE,
      models: PROBE.models.filter((model) => model.price_label === "paid"),
    });
    fireEvent.click(toggle());

    expect(
      screen.getByText("no free or local models in this catalog"),
    ).toBeInTheDocument();
    expect(count()).toHaveTextContent("Showing 0 of 1 models");
  });

  it("is disabled when no model has a price label", () => {
    renderList(UNLABELLED);

    expect(toggle()).toBeDisabled();
    expect(toggle()).toHaveAttribute("title", "Price labels need a fresh probe");
    expect(toggle()).toHaveAttribute("aria-pressed", "false");
  });

  it("ignores a stale on state once the labels are gone", () => {
    const { rerenderProbe } = renderList();
    fireEvent.click(toggle());
    expect(count()).toHaveTextContent("Showing 2 of 5 models");

    rerenderProbe(UNLABELLED);

    expect(toggle()).toBeDisabled();
    expect(toggle()).toHaveAttribute("aria-pressed", "false");
    expect(count()).toHaveTextContent("5 / 5 models");
  });
});
