import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  FilterBar,
  FilterSearch,
  FilterSegments,
  FilterSelect,
  type FilterOption,
} from "../components/el/FilterBar";

type Status = "all" | "passed" | "failed" | "running";

const STATUS: readonly FilterOption<Status>[] = [
  { value: "all", label: "All" },
  { value: "passed", label: "Passed" },
  { value: "failed", label: "Failed" },
  { value: "running", label: "Running" },
];

const WORKFLOWS: readonly FilterOption[] = [
  { value: "all", label: "All workflows" },
  { value: "code_review", label: "code_review" },
  { value: "bug_resolution", label: "bug_resolution" },
];

/** A parent that owns the state, as a page does. */
function Harness({ onStatus }: Readonly<{ onStatus?: (s: Status) => void }>) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<Status>("all");
  const [workflow, setWorkflow] = useState("all");
  return (
    <FilterBar>
      <FilterSearch
        aria-label="Search runs by id or workflow"
        placeholder="Search runs by id or workflow"
        value={query}
        onChange={setQuery}
      />
      <FilterSelect
        aria-label="Workflow"
        value={workflow}
        onChange={setWorkflow}
        options={WORKFLOWS}
      />
      <FilterSegments
        aria-label="Status"
        value={status}
        onChange={(s) => {
          setStatus(s);
          onStatus?.(s);
        }}
        options={STATUS}
      />
      <output data-testid="state">{`${query}|${workflow}|${status}`}</output>
    </FilterBar>
  );
}

describe("FilterSearch", () => {
  it("is a labelled search field, controlled by its value", () => {
    const { rerender } = render(
      <FilterSearch aria-label="Search runs" value="abc" onChange={() => {}} />,
    );
    const field = screen.getByRole("searchbox", { name: "Search runs" });
    expect(field).toHaveValue("abc");

    rerender(<FilterSearch aria-label="Search runs" value="xyz" onChange={() => {}} />);
    expect(field).toHaveValue("xyz");
  });

  it("reports the typed text and not the event", () => {
    const onChange = vi.fn();
    render(<FilterSearch aria-label="Search runs" value="" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Search runs"), { target: { value: "c71" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("c71");
  });

  it("does not keep its own copy of the value", () => {
    render(<FilterSearch aria-label="Search runs" value="fixed" onChange={() => {}} />);
    const field = screen.getByLabelText("Search runs");
    fireEvent.change(field, { target: { value: "typed" } });
    expect(field).toHaveValue("fixed");
  });

  it("passes placeholder and other input attributes through", () => {
    render(
      <FilterSearch
        aria-label="Search runs"
        placeholder="Search runs by id or workflow"
        value=""
        onChange={() => {}}
      />,
    );
    expect(screen.getByPlaceholderText("Search runs by id or workflow")).toBeInTheDocument();
  });

  it("focuses on / and keeps the slash out of the field", () => {
    render(<FilterSearch aria-label="Search runs" value="" onChange={() => {}} />);
    const field = screen.getByLabelText("Search runs");
    expect(field).not.toHaveFocus();
    const notPrevented = fireEvent.keyDown(window, { key: "/" });
    expect(field).toHaveFocus();
    // fireEvent returns false when the handler called preventDefault.
    expect(notPrevented).toBe(false);
    expect(field).toHaveAttribute("aria-keyshortcuts", "/");
  });

  it("does not steal / from another text field", () => {
    render(
      <>
        <input aria-label="Other" />
        <FilterSearch aria-label="Search runs" value="" onChange={() => {}} />
      </>,
    );
    const other = screen.getByLabelText("Other");
    other.focus();
    fireEvent.keyDown(other, { key: "/" });
    expect(other).toHaveFocus();
  });

  it("ignores / with a modifier and while a dialog is focused", () => {
    render(
      <>
        <div role="dialog" aria-label="Sheet" tabIndex={-1} data-testid="dlg" />
        <FilterSearch aria-label="Search runs" value="" onChange={() => {}} />
      </>,
    );
    const field = screen.getByLabelText("Search runs");
    fireEvent.keyDown(window, { key: "/", ctrlKey: true });
    expect(field).not.toHaveFocus();
    screen.getByTestId("dlg").focus();
    fireEvent.keyDown(window, { key: "/" });
    expect(field).not.toHaveFocus();
  });

  it("can turn the shortcut off or move it to another key", () => {
    const { rerender } = render(
      <FilterSearch aria-label="Search runs" value="" onChange={() => {}} focusShortcut={false} />,
    );
    const field = screen.getByLabelText("Search runs");
    fireEvent.keyDown(window, { key: "/" });
    expect(field).not.toHaveFocus();
    expect(field).not.toHaveAttribute("aria-keyshortcuts");

    rerender(
      <FilterSearch aria-label="Search runs" value="" onChange={() => {}} focusShortcut="f" />,
    );
    fireEvent.keyDown(window, { key: "/" });
    expect(field).not.toHaveFocus();
    fireEvent.keyDown(window, { key: "f" });
    expect(field).toHaveFocus();
  });

  it("stops listening after it unmounts", () => {
    const { unmount } = render(
      <FilterSearch aria-label="Search runs" value="" onChange={() => {}} />,
    );
    unmount();
    expect(fireEvent.keyDown(window, { key: "/" })).toBe(true);
  });
});

describe("FilterSegments", () => {
  it("is a named group of buttons with exactly one pressed", () => {
    render(<FilterSegments aria-label="Status" value="failed" onChange={() => {}} options={STATUS} />);
    const group = screen.getByRole("group", { name: "Status" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["All", "Passed", "Failed", "Running"]);
    expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual([
      "false",
      "false",
      "true",
      "false",
    ]);
  });

  it("calls onChange with the option value and moves the pressed state", () => {
    const onStatus = vi.fn();
    render(<Harness onStatus={onStatus} />);
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Failed" }));
    expect(onStatus).toHaveBeenCalledWith("failed");
    expect(screen.getByRole("button", { name: "Failed" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
  });

  it("uses type=button so it never submits a surrounding form", () => {
    render(<FilterSegments aria-label="Status" value="all" onChange={() => {}} options={STATUS} />);
    for (const b of screen.getAllByRole("button")) expect(b).toHaveAttribute("type", "button");
  });

  it("goes full width on phones", () => {
    render(<FilterSegments aria-label="Status" value="all" onChange={() => {}} options={STATUS} />);
    expect(screen.getByRole("group").className).toContain("max-[760px]:basis-full");
    expect(screen.getByRole("button", { name: "All" }).className).toContain("max-[760px]:flex-1");
  });
});

describe("FilterSelect", () => {
  it("is a labelled combobox showing the controlled value", () => {
    render(<FilterSelect aria-label="Workflow" value="code_review" onChange={() => {}} options={WORKFLOWS} />);
    const select = screen.getByRole("combobox", { name: "Workflow" });
    expect(select).toHaveValue("code_review");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All workflows",
      "code_review",
      "bug_resolution",
    ]);
  });

  it("calls onChange with the chosen option's value", () => {
    const onChange = vi.fn();
    render(<FilterSelect aria-label="Workflow" value="all" onChange={onChange} options={WORKFLOWS} />);
    fireEvent.change(screen.getByLabelText("Workflow"), { target: { value: "bug_resolution" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("bug_resolution");
  });

  it("ignores a value that is not one of its options", () => {
    const onChange = vi.fn();
    render(<FilterSelect aria-label="Workflow" value="all" onChange={onChange} options={WORKFLOWS} />);
    const select = screen.getByLabelText("Workflow");
    // jsdom drops an unknown value to "", which matches no option.
    fireEvent.change(select, { target: { value: "no_such_workflow" } });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("is at least 40px tall and 4px radius", () => {
    render(<FilterSelect aria-label="Workflow" value="all" onChange={() => {}} options={WORKFLOWS} />);
    const { className } = screen.getByLabelText("Workflow");
    expect(className).toContain("h-10");
    expect(className).toContain("rounded-md");
    expect(className).toContain("focus-ring");
  });
});

describe("FilterBar", () => {
  it("wraps its controls in one row that can wrap", () => {
    render(<Harness />);
    const bar = screen.getByTestId("state").parentElement as HTMLElement;
    expect(bar.dataset.slot).toBe("filter-bar");
    expect(bar.className).toContain("flex-wrap");
  });

  it("keeps search, select and segments independent in one state owner", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Search runs by id or workflow"), {
      target: { value: "c71" },
    });
    fireEvent.change(screen.getByLabelText("Workflow"), { target: { value: "code_review" } });
    fireEvent.click(screen.getByRole("button", { name: "Running" }));
    expect(screen.getByTestId("state")).toHaveTextContent("c71|code_review|running");
  });
});
