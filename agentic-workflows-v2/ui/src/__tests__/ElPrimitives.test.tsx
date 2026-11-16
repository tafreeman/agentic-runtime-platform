import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "../components/el/Button";
import {
  DeclaredOutputs,
  Evidence,
} from "../components/el/Evidence";
import {
  Delta,
  formatShare,
  Meter,
  meterTone,
} from "../components/el/Meter";
import { PageIntro } from "../components/el/PageIntro";
import {
  Kbd,
  StatusPill,
  TagPill,
  TierPill,
} from "../components/el/StatusPill";
import {
  EL_STATUS,
  type ElStatus,
  statusLabel,
  statusView,
  toElStatus,
} from "../components/el/status";
import { ViewSwitch } from "../components/el/ViewSwitch";

/** Every status string the API, the live stream and the probes emit. */
const API_STATUSES: ReadonlyArray<readonly [string, ElStatus]> = [
  ["success", "passed"],
  ["completed", "passed"],
  ["passed", "passed"],
  ["ok", "passed"],
  ["available", "passed"],
  ["failed", "failed"],
  ["error", "failed"],
  ["unavailable", "failed"],
  ["max_retries_exceeded", "failed"],
  ["running", "running"],
  ["in_progress", "running"],
  ["retrying", "running"],
  ["evaluating", "running"],
  ["pending", "never"],
  ["skipped", "never"],
  ["cancelled", "never"],
  ["connecting", "never"],
  ["review", "warn"],
];

describe("status vocabulary", () => {
  it.each(API_STATUSES)("maps API status %s to %s", (api, expected) => {
    expect(toElStatus(api)).toBe(expected);
  });

  it("ignores case and surrounding whitespace", () => {
    expect(toElStatus("  SUCCESS ")).toBe("passed");
    expect(toElStatus("In_Progress")).toBe("running");
  });

  it.each([null, undefined, "", "  ", "needs_review", "totally-new"])(
    "falls back to grey Never ran for %j instead of asserting an outcome",
    (value) => {
      expect(toElStatus(value)).toBe("never");
    },
  );

  it("never derives Root cause or a false pass from an API string", () => {
    expect(API_STATUSES.some(([, status]) => status === "root")).toBe(false);
    expect(toElStatus("unknown")).not.toBe("passed");
  });

  it("keeps the six fixed words and glyphs", () => {
    expect(Object.values(EL_STATUS).map((spec) => spec.word)).toEqual([
      "Passed",
      "Failed",
      "Root cause",
      "Never ran",
      "Running",
      "Chain exhausted",
    ]);
    expect(Object.values(EL_STATUS).map((spec) => spec.glyph)).toEqual([
      "✓",
      "✕",
      "◆",
      "○",
      "●",
      "!",
    ]);
    expect(statusLabel("root")).toBe("Root cause");
  });

  it("prints the vocabulary word, except for the three states it has no word for", () => {
    expect(statusView("success").label).toBe("Passed");
    expect(statusView("skipped").label).toBe("Never ran");
    expect(statusView("failed").label).toBe("Failed");
    expect(statusView("cancelled")).toEqual({ status: "never", label: "Cancelled" });
    expect(statusView("review")).toEqual({ status: "warn", label: "Review" });
    expect(statusView("connecting")).toEqual({ status: "never", label: "Connecting" });
    // Unknown strings get the grey fill and its word, not a made-up one.
    expect(statusView("mystery")).toEqual({ status: "never", label: "Never ran" });
  });
});

describe("StatusPill, TierPill, TagPill, Kbd", () => {
  it.each(Object.entries(EL_STATUS) as [ElStatus, (typeof EL_STATUS)[ElStatus]][])(
    "renders %s as a hidden glyph plus its word",
    (status, spec) => {
      const { container } = render(<StatusPill status={status} />);
      const glyph = container.querySelector("[aria-hidden='true']");
      expect(glyph).toHaveTextContent(spec.glyph);
      // The word is the accessible text; the glyph adds nothing to it.
      expect(screen.getByText(spec.word)).not.toHaveAttribute("aria-hidden");
      expect(container.firstElementChild?.className).toContain(spec.fill);
    },
  );

  it("shares one solid, white-on-fill, 24px, fully rounded spec", () => {
    const { container } = render(<StatusPill status="passed" />);
    const pill = container.firstElementChild;
    for (const cls of [
      "h-6",
      "rounded-full",
      "min-w-30",
      "text-xs",
      "font-semibold",
      "text-el-on-badge",
    ]) {
      expect(pill?.className).toContain(cls);
    }
    // The grey default must lose to the status fill, not sit beside it.
    expect(pill?.className).not.toContain("bg-el-badge-neutral");
  });

  it("tells Failed and Root cause apart by glyph and word, not fill", () => {
    const { container } = render(
      <>
        <StatusPill status="failed" />
        <StatusPill status="root" />
      </>,
    );
    const [failed, root] = Array.from(container.children);
    expect(failed?.className).toContain("bg-el-badge-danger");
    expect(root?.className).toContain("bg-el-badge-danger");
    expect(failed?.textContent).not.toBe(root?.textContent);
  });

  it("narrows to 104px in tables and lets a label override the word", () => {
    const { container } = render(<StatusPill status="warn" compact label="Waiting" />);
    expect(container.firstElementChild?.className).toContain("min-w-26");
    expect(container.firstElementChild?.className).not.toContain("min-w-30");
    expect(screen.getByText("Waiting")).toBeInTheDocument();
    expect(screen.queryByText("Chain exhausted")).toBeNull();
  });

  it("forwards native attributes and merges className", () => {
    render(<StatusPill status="running" title="In flight" className="ml-2" />);
    const pill = screen.getByTitle("In flight");
    expect(pill.className).toContain("ml-2");
    expect(pill.className).toContain("bg-el-badge-info");
  });

  it("writes a tier as a capability, in the one documented T2 · coder form", () => {
    const { rerender } = render(<TierPill tier={2} capability="coder" />);
    expect(screen.getByText("T2 · coder")).toBeInTheDocument();
    rerender(<TierPill tier={0} />);
    expect(screen.getByText("T0")).toBeInTheDocument();
    expect(screen.getByText("T0").className).toContain("font-mono");
    expect(screen.getByText("T0").className).toContain("bg-el-badge-neutral");
  });

  it("renders tags as grey mono pills and keys as outlined key caps", () => {
    render(
      <>
        <TagPill>c718044a</TagPill>
        <Kbd>Ctrl K</Kbd>
      </>,
    );
    const tag = screen.getByText("c718044a");
    expect(tag.className).toContain("font-mono");
    expect(tag.className).toContain("rounded-full");
    const kbd = screen.getByText("Ctrl K");
    expect(kbd.tagName).toBe("KBD");
    expect(kbd.className).toContain("border-el-divider");
    expect(kbd.className).not.toMatch(/\bbg-/);
  });
});

describe("Button", () => {
  it("builds each variant on the Evidence Ledger tokens", () => {
    render(
      <>
        <Button variant="primary">Fix and re-run</Button>
        <Button variant="secondary">Export</Button>
        <Button variant="quiet">Copy as Markdown</Button>
      </>,
    );
    const primary = screen.getByRole("button", { name: "Fix and re-run" });
    expect(primary.className).toContain("bg-el-action");
    expect(primary.className).toContain("text-el-action-ink");
    expect(primary).toHaveAttribute("data-el-variant", "primary");

    const secondary = screen.getByRole("button", { name: "Export" });
    expect(secondary.className).toContain("border-el-control-border");
    expect(secondary.className).not.toContain("bg-el-action");

    const quiet = screen.getByRole("button", { name: "Copy as Markdown" });
    expect(quiet.className).toContain("border-transparent");
    expect(quiet.className).not.toContain("border-el-control-border");
  });

  it("defaults to secondary so a primary is always a deliberate choice", () => {
    render(<Button>Open output</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("data-el-variant", "secondary");
  });

  it("is 36px high with 16px side padding, 32px when small, and a 36px square as an icon", () => {
    render(
      <>
        <Button>Default</Button>
        <Button size="sm">Small</Button>
        <Button size="icon" aria-label="Switch theme">
          x
        </Button>
      </>,
    );
    const sized = screen.getByRole("button", { name: "Default" }).className;
    expect(sized).toContain("h-9");
    expect(sized).toContain("px-4");
    expect(sized).not.toContain("h-10");
    expect(screen.getByRole("button", { name: "Small" }).className).toContain("h-8");
    const icon = screen.getByRole("button", { name: "Switch theme" }).className;
    expect(icon).toContain("size-9");
    expect(icon).not.toContain("w-10");
  });

  it("keeps the compliant focus ring and 4px radius of the shared button", () => {
    render(<Button variant="primary">Run</Button>);
    const button = screen.getByRole("button", { name: "Run" });
    expect(button.className).toContain("focus-ring");
    expect(button.className).toContain("rounded-md");
    expect(button.className).not.toMatch(/transition-all|outline-none/);
  });

  it("forwards native props, className and clicks", () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" aria-haspopup="dialog" type="submit" className="ml-4" onClick={onClick}>
        Fix and re-run
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Fix and re-run" });
    expect(button).toHaveAttribute("aria-haspopup", "dialog");
    expect(button).toHaveAttribute("type", "submit");
    expect(button.className).toContain("ml-4");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("forwards disabled to the native button and never fires onClick", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Re-run
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Re-run" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps its label while loading, swaps the icon for a spinner and ignores clicks", () => {
    const onClick = vi.fn();
    const { container } = render(
      <Button loading icon={<span data-testid="icon">i</span>} onClick={onClick}>
        Export
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Export" });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    expect(screen.queryByTestId("icon")).toBeNull();
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("lets a caller's own aria-disabled through when not loading", () => {
    render(<Button aria-disabled="true">Export</Button>);
    expect(screen.getByRole("button", { name: "Export" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("button", { name: "Export" })).not.toHaveAttribute("aria-busy");
  });

  it("requires a name on an icon-only button", () => {
    // @ts-expect-error an icon button without aria-label must not type-check
    render(<Button size="icon">x</Button>);
  });
});

describe("ViewSwitch", () => {
  const ITEMS = [
    { id: "record", label: "Record" },
    { id: "board", label: "Tier board" },
    { id: "rewind", label: "Rewind" },
  ] as const;

  it("is a labelled group that marks only the current view pressed", () => {
    render(<ViewSwitch items={ITEMS} value="board" onChange={() => {}} />);
    const group = screen.getByRole("group", { name: "View" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual(["false", "true", "false"]);
    expect(within(group).getByRole("button", { name: "Tier board" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("raises the pressed segment on surface-raised and no other", () => {
    render(<ViewSwitch items={ITEMS} value="record" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Record" }).className).toContain("bg-el-raised");
    expect(screen.getByRole("button", { name: "Rewind" }).className).not.toContain("bg-el-raised");
  });

  it("reports the clicked view and uses real, focusable buttons", () => {
    const onChange = vi.fn();
    render(<ViewSwitch items={ITEMS} value="record" onChange={onChange} />);
    const rewind = screen.getByRole("button", { name: "Rewind" });
    expect(rewind.tagName).toBe("BUTTON");
    expect(rewind).toHaveAttribute("type", "button");
    expect(rewind.tabIndex).not.toBe(-1);
    expect(rewind.className).toContain("focus-ring");
    rewind.focus();
    expect(rewind).toHaveFocus();
    fireEvent.click(rewind);
    expect(onChange).toHaveBeenCalledExactlyOnceWith("rewind");
  });

  it("takes the full row on phones", () => {
    render(<ViewSwitch items={ITEMS} value="record" onChange={() => {}} />);
    expect(screen.getByRole("group").className).toContain("max-[760px]:basis-full");
  });

  describe("number-key shortcuts", () => {
    const press = (key: string, init: KeyboardEventInit = {}) =>
      globalThis.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, ...init }));

    it("jump to views 1, 2, 3 when enabled and announce the keys", () => {
      const onChange = vi.fn();
      render(<ViewSwitch items={ITEMS} value="record" onChange={onChange} shortcuts />);
      press("2");
      press("3");
      expect(onChange.mock.calls).toEqual([["board"], ["rewind"]]);
      expect(screen.getByRole("button", { name: "Tier board" })).toHaveAttribute(
        "aria-keyshortcuts",
        "2",
      );
    });

    it("do nothing by default, so a status filter never fights the run switch", () => {
      const onChange = vi.fn();
      render(<ViewSwitch items={ITEMS} value="record" onChange={onChange} />);
      press("2");
      expect(onChange).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Tier board" })).not.toHaveAttribute(
        "aria-keyshortcuts",
      );
    });

    it("ignore keys beyond the views, modified keys and typing in a field", () => {
      const onChange = vi.fn();
      render(
        <>
          <input aria-label="Search" />
          <ViewSwitch items={ITEMS} value="record" onChange={onChange} shortcuts />
        </>,
      );
      press("4");
      press("0");
      press("a");
      press("2", { ctrlKey: true });
      press("2", { metaKey: true });
      const input = screen.getByLabelText("Search");
      input.focus();
      press("2");
      fireEvent.keyDown(input, { key: "2" });
      expect(onChange).not.toHaveBeenCalled();
    });

    it("stop listening once unmounted", () => {
      const onChange = vi.fn();
      const { unmount } = render(
        <ViewSwitch items={ITEMS} value="record" onChange={onChange} shortcuts />,
      );
      unmount();
      press("1");
      expect(onChange).not.toHaveBeenCalled();
    });
  });
});

describe("Meter", () => {
  it("prints its value and exposes it as a meter on a 0 to 1 scale", () => {
    render(<Meter value={0.34} threshold={0.8} aria-label="fullstack_generation" />);
    const meter = screen.getByRole("meter", { name: "fullstack_generation" });
    expect(meter).toHaveAttribute("aria-valuemin", "0");
    expect(meter).toHaveAttribute("aria-valuemax", "1");
    expect(meter).toHaveAttribute("aria-valuenow", "0.34");
    expect(meter).toHaveAttribute("aria-valuetext", "0.34, threshold 0.80");
    expect(within(meter).getByText("0.34")).toBeInTheDocument();
  });

  it("places the 2px threshold mark and the fill on the true scale", () => {
    const { container } = render(<Meter value={0.5} threshold={0.8} aria-label="m" />);
    const mark = container.querySelector("[data-threshold]");
    expect(mark).toHaveStyle({ left: "80%" });
    expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(mark?.className).toContain("w-0.5");
    expect(container.querySelector("[data-fill]")).toHaveStyle({ width: "50%" });
  });

  it.each([
    [1.0, "success"],
    [0.8, "success"],
    [0.79, "warning"],
    // 0.80 - 0.10 is 0.7000000000000001 in floats; the edge must still warn.
    [0.7, "warning"],
    [0.69, "danger"],
    [0.34, "danger"],
    [0, "danger"],
  ])("fills a %s score against a 0.80 threshold as %s", (value, tone) => {
    expect(meterTone(value, 0.8)).toBe(tone);
    const { container } = render(<Meter value={value} threshold={0.8} aria-label="m" />);
    expect(container.querySelector("[data-fill]")).toHaveAttribute("data-fill", tone);
  });

  it("is neutral without a threshold and obeys an explicit tone", () => {
    const { container, rerender } = render(<Meter value={0.52} format={formatShare} aria-label="Steps on T2" />);
    expect(container.querySelector("[data-fill]")).toHaveAttribute("data-fill", "neutral");
    expect(container.querySelector("[data-threshold]")).toBeNull();
    expect(screen.getByText("52%")).toBeInTheDocument();
    rerender(<Meter value={0.1} threshold={0.8} tone="neutral" aria-label="m" />);
    expect(container.querySelector("[data-fill]")).toHaveAttribute("data-fill", "neutral");
  });

  it("clamps out-of-range values instead of overflowing the track", () => {
    const { container } = render(<Meter value={1.4} aria-label="m" />);
    expect(container.querySelector("[data-fill]")).toHaveStyle({ width: "100%" });
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "1");
  });

  it("shows absent data as a dash with no fill, never 0.00", () => {
    const { container } = render(<Meter value={null} threshold={0.8} aria-label="m" />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0.00")).toBeNull();
    expect(screen.queryByRole("meter")).toBeNull();
    expect(container.querySelector("[data-fill]")).toBeNull();
  });

  it("sets numbers in the sans with tabular figures", () => {
    render(<Meter value={0.8} aria-label="m" />);
    const printed = screen.getByText("0.80");
    expect(printed.className).toContain("tabular-nums");
    expect(printed.className).not.toContain("font-mono");
  });
});

describe("Delta", () => {
  it("prints the size of the change with a direction glyph", () => {
    const { container, rerender } = render(<Delta value={0.15} />);
    expect(container).toHaveTextContent("▲");
    expect(container).toHaveTextContent("0.15");
    rerender(<Delta value={-0.46} />);
    expect(container).toHaveTextContent("▼");
    expect(container).toHaveTextContent("0.46");
    // The sign lives in the glyph, so the number is never printed with a minus.
    expect(container).not.toHaveTextContent("-0.46");
  });

  it("says the direction in words for screen readers and hides the glyph", () => {
    const { container, rerender } = render(<Delta value={0.15} />);
    expect(screen.getByText("Up")).toHaveClass("sr-only");
    expect(container.querySelector("[aria-hidden='true']")).toHaveTextContent("▲");
    rerender(<Delta value={-0.15} />);
    expect(screen.getByText("Down")).toHaveClass("sr-only");
    rerender(<Delta value={0} />);
    expect(screen.getByText("Unchanged")).toHaveClass("sr-only");
  });

  it("colours only a change for the worse", () => {
    const { container, rerender } = render(<Delta value={-0.46} />);
    const delta = () => container.firstElementChild;
    expect(delta()?.className).toContain("text-el-danger");
    rerender(<Delta value={0.15} />);
    expect(delta()?.className).not.toMatch(/text-el-(danger|success|warning)/);
    rerender(<Delta value={0} />);
    expect(delta()?.className).not.toMatch(/text-el-(danger|success|warning)/);
  });

  it("flips which direction is worse for durations and costs", () => {
    const { container, rerender } = render(<Delta value={120} lowerIsBetter format={(n) => `${n} ms`} />);
    expect(container.firstElementChild?.className).toContain("text-el-danger");
    expect(container).toHaveTextContent("120 ms");
    rerender(<Delta value={-120} lowerIsBetter format={(n) => `${n} ms`} />);
    expect(container.firstElementChild?.className).not.toContain("text-el-danger");
    expect(container).toHaveTextContent("▼");
  });

  it("reads a change that prints as zero, or float noise, as unchanged", () => {
    const { container, rerender } = render(<Delta value={0.004} />);
    expect(container.firstElementChild).toHaveAttribute("data-direction", "flat");
    expect(container).toHaveTextContent("=");
    rerender(<Delta value={0.1 + 0.2 - 0.3} />);
    expect(container.firstElementChild).toHaveAttribute("data-direction", "flat");
    // A tiny drop that prints as 0.00 must not be coloured as a regression.
    rerender(<Delta value={-0.004} />);
    expect(container.firstElementChild?.className).not.toContain("text-el-danger");
  });

  it("shows no earlier value as a dash, not a zero change", () => {
    const { container } = render(<Delta value={null} />);
    expect(container).toHaveTextContent("—");
    expect(container.querySelector("[data-direction]")).toBeNull();
    expect(screen.queryByText("0.00")).toBeNull();
  });
});

describe("Evidence", () => {
  const RAW =
    "All model attempts failed (last model=ollama:qwen3-coder:30b):\n  response failed declared output requirements <b>{x}</b>";

  it("renders the machine's text verbatim, whitespace and markup characters included", () => {
    const { container } = render(
      <Evidence caption="Verbatim step_error.error from generate_api">{RAW}</Evidence>,
    );
    const code = container.querySelector("code");
    expect(code?.textContent).toBe(RAW);
    // Characters that look like markup are text, not elements.
    expect(container.querySelector("b")).toBeNull();
    expect(code?.className).toContain("whitespace-pre-wrap");
    expect(code?.className).toContain("font-mono");
  });

  it("is a figure whose caption names the source", () => {
    render(
      <Evidence caption={<>Verbatim <code>step_error.error</code> from generate_api at T+77.1 ms</>}>
        boom
      </Evidence>,
    );
    const figure = screen.getByRole("figure");
    const caption = within(figure).getByText(/from generate_api/);
    expect(caption.tagName).toBe("FIGCAPTION");
    expect(within(caption).getByText("step_error.error").tagName).toBe("CODE");
  });

  it("quotes errors on danger-soft by default and raw logs on surface-sunken", () => {
    const { rerender } = render(<Evidence caption="c">e</Evidence>);
    expect(screen.getByRole("figure").className).toContain("bg-el-danger-soft");
    expect(screen.getByRole("figure").className).toContain("border-el-danger");
    rerender(
      <Evidence caption="c" variant="plain">
        e
      </Evidence>,
    );
    expect(screen.getByRole("figure").className).toContain("bg-el-surface-sunken");
    expect(screen.getByRole("figure").className).not.toContain("bg-el-danger-soft");
    rerender(
      <Evidence caption="c" variant="ledger">
        e
      </Evidence>,
    );
    expect(screen.getByRole("figure").className).not.toMatch(/\b(bg-|border)/);
  });

  it("lists declared outputs with a glyph and a spoken status, not colour alone", () => {
    render(
      <DeclaredOutputs
        outputs={[
          { name: "content", present: true },
          { name: "backend", present: false },
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("✓");
    expect(items[0]).toHaveTextContent("content");
    expect(items[1]).toHaveTextContent("✕");
    expect(items[1]).toHaveTextContent("backend");
    expect(within(items[1] as HTMLElement).getByText(", missing")).toHaveClass("sr-only");
    expect(items[1]?.className).toContain("text-el-danger");
    expect(items[0]?.className).toContain("text-el-success");
  });
});

describe("PageIntro", () => {
  it("leads with the finding as the page's h1 in the display serif", () => {
    render(<PageIntro finding="The gate failed: one case scored 0.34 against 0.80." />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("The gate failed: one case scored 0.34 against 0.80.");
    expect(heading.className).toContain("font-display");
    expect(heading.className).toContain("font-normal");
  });

  it("accepts nodes so identifiers can be code, and renders the standfirst and note", () => {
    render(
      <PageIntro
        finding={
          <>
            <code>generate_api</code> stopped the run.
          </>
        }
        standfirst="Three of four golden cases passed."
        note="Updated 2 min ago"
      />,
    );
    expect(within(screen.getByRole("heading")).getByText("generate_api").tagName).toBe("CODE");
    expect(screen.getByText("Three of four golden cases passed.").className).toContain(
      "text-el-secondary",
    );
    expect(screen.getByText("Updated 2 min ago").className).toContain("text-el-muted");
  });

  it("omits the standfirst and note elements when not given", () => {
    const { container } = render(<PageIntro finding="One sentence." />);
    expect(container.querySelectorAll("p")).toHaveLength(0);
    expect(container.querySelectorAll("div")).toHaveLength(2);
  });

  it("can step down from h1 when the shell header already owns it", () => {
    const { rerender } = render(<PageIntro as="h2" finding="Finding." />);
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Finding.");
    rerender(<PageIntro as="p" finding="Finding." />);
    expect(screen.queryByRole("heading")).toBeNull();
  });
});
