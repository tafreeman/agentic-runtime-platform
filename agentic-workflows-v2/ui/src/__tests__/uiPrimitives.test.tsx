import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BAsciiBar from "../components/common/BAsciiBar";
import BPill from "../components/common/BPill";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Input } from "../components/ui/input";
import { Switch } from "../components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Textarea } from "../components/ui/textarea";

/** shadcn's 50%-tint ring (~2.4:1) and blanket outline suppression fail AA. */
const NON_COMPLIANT_FOCUS = /ring-ring\/|ring-3|outline-hidden|outline-none|transition-all/;

describe("UI primitives — focus, motion and geometry", () => {
  it("gives the button a full-strength focus ring and a 4px radius", () => {
    render(<Button>Run</Button>);
    const button = screen.getByRole("button", { name: "Run" });
    expect(button.className).toContain("focus-ring");
    expect(button.className).toContain("rounded-md");
    expect(button.className).not.toMatch(NON_COMPLIANT_FOCUS);
  });

  it.each(["xs", "sm", "icon-xs", "icon-sm"] as const)(
    "keeps the %s button compact but gives it a >=36px hit area",
    (size) => {
      render(
        <Button size={size} aria-label="compact">
          x
        </Button>,
      );
      const button = screen.getByRole("button", { name: "compact" });
      expect(button.className).toContain("relative");
      expect(button.className).toContain("after:min-h-9");
      expect(button.className).toContain("after:min-w-9");
    },
  );

  it("lets a caller position the button absolutely without losing the hit area", () => {
    render(
      <Button size="icon-sm" aria-label="close" className="absolute top-2 right-2">
        x
      </Button>,
    );
    const button = screen.getByRole("button", { name: "close" });
    expect(button.className).toContain("absolute");
    expect(button.className).not.toMatch(/\brelative\b/);
    expect(button.className).toContain("after:min-h-9");
  });

  it("uses the theme-flipping destructive foreground, not hardcoded white", () => {
    render(<Button variant="destructive">Delete</Button>);
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button.className).toContain("text-destructive-foreground");
    expect(button.className).not.toContain("text-white");
  });

  it("renders badges as 2px tags, not pills, without transition-all", () => {
    render(<Badge>passed</Badge>);
    const badge = screen.getByText("passed");
    expect(badge.className).toContain("rounded-sm");
    expect(badge.className).not.toContain("rounded-4xl");
    expect(badge.className).not.toMatch(NON_COMPLIANT_FOCUS);
  });

  it("gives text inputs, checkbox, switch and tabs a compliant focus ring", () => {
    render(
      <>
        <Input aria-label="name" />
        <Textarea aria-label="notes" />
        <Checkbox aria-label="agree" />
        <Switch aria-label="enabled" />
        <Tabs defaultValue="a">
          <TabsList>
            <TabsTrigger value="a">Alpha</TabsTrigger>
          </TabsList>
        </Tabs>
      </>,
    );
    for (const el of [
      screen.getByRole("textbox", { name: "name" }),
      screen.getByRole("textbox", { name: "notes" }),
      screen.getByRole("checkbox", { name: "agree" }),
      screen.getByRole("switch", { name: "enabled" }),
      screen.getByRole("tab", { name: "Alpha" }),
    ]) {
      expect(el.className).toMatch(/focus-ring/);
      expect(el.className).not.toMatch(NON_COMPLIANT_FOCUS);
    }
    // The active tab rail is state-bearing: accent-strong, not raw accent.
    expect(screen.getByRole("tab", { name: "Alpha" }).className).toContain(
      "data-[state=active]:border-el-accent-strong",
    );
  });

  it("expands the checkbox and switch hit areas to at least 36px", () => {
    render(
      <>
        <Checkbox aria-label="agree" />
        <Switch aria-label="enabled" />
      </>,
    );
    expect(screen.getByRole("checkbox", { name: "agree" }).className).toContain(
      "after:-inset-2.5",
    );
    expect(screen.getByRole("switch", { name: "enabled" }).className).toContain(
      "after:-inset-3",
    );
  });
});

describe("BPill / BAsciiBar", () => {
  it("renders status pills as 2px tags with el tokens and a text label", () => {
    render(<BPill tone="err">failed</BPill>);
    const pill = screen.getByText("failed");
    expect(pill.className).toContain("rounded-sm");
    expect(pill.className).toContain("text-el-danger");
    expect(pill.className).toContain("bg-el-danger-soft");
    expect(pill.className).toContain("text-micro");
    expect(pill.className).not.toMatch(/b-(red|line|text)/);
  });

  it("keeps the vermilion tone restrained to an outlined mark", () => {
    render(<BPill tone="clay">winner</BPill>);
    const pill = screen.getByText("winner");
    expect(pill.className).toContain("text-el-accent-strong");
    expect(pill.className).toContain("bg-transparent");
  });

  it("maps legacy and semantic bar colors to static el classes", () => {
    const { rerender } = render(<BAsciiBar value={0.5} color="b-red" />);
    expect(screen.getByRole("progressbar").className).toContain("text-el-danger");
    rerender(<BAsciiBar value={0.5} color="info" />);
    expect(screen.getByRole("progressbar").className).toContain("text-el-info");
    rerender(<BAsciiBar value={0.5} />);
    const bar = screen.getByRole("progressbar");
    expect(bar.className).toContain("text-el-success");
    expect(bar.className).toContain("text-micro");
  });
});
