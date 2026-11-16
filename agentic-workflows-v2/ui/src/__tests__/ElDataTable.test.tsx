import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import {
  DataTable,
  EntityCell,
  NumCell,
  SentenceCell,
  type Column,
  type DataTableProps,
} from "../components/el/DataTable";

interface Run {
  id: string;
  workflow: string;
  what: string;
  took: number | null;
  day: string;
}

const RUNS: readonly Run[] = [
  { id: "c718044a", workflow: "fullstack_generation", what: "Stopped at generate_api", took: 77, day: "Today" },
  { id: "41f9aa02", workflow: "bug_resolution", what: "Waiting for approval", took: 8400, day: "Today" },
  { id: "9e21b0d4", workflow: "code_review", what: "Passed all 5 steps", took: null, day: "Yesterday" },
];

const COLUMNS: readonly Column<Run>[] = [
  { id: "workflow", header: "Workflow", cell: (r) => <EntityCell to={`/runs/${r.id}`} name={r.workflow} id={r.id} /> },
  { id: "what", header: "What happened", sentence: true, cell: (r) => <SentenceCell>{r.what}</SentenceCell> },
  { id: "took", header: "Took", align: "end", stackLabel: "Took", cell: (r) => <NumCell>{r.took}</NumCell> },
  { id: "day", header: "Started", align: "end", hideOnPhone: true, cell: (r) => r.day },
];

function renderTable(props: Partial<DataTableProps<Run>> = {}) {
  return render(
    <MemoryRouter>
      <input aria-label="Search" />
      <DataTable
        aria-label="Runs"
        columns={COLUMNS}
        rows={RUNS}
        getRowKey={(r) => r.id}
        {...props}
      />
    </MemoryRouter>,
  );
}

/** Body rows only: the rows that carry a `data-cursor` slot are data rows. */
function dataRows(): HTMLElement[] {
  return screen
    .getAllByRole("row")
    .filter((row) => row.hasAttribute("tabindex"));
}

describe("DataTable structure", () => {
  it("renders a real table with scoped column headers", () => {
    renderTable();
    const table = screen.getByRole("table", { name: "Runs" });
    expect(table.tagName).toBe("TABLE");
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual([
      "Workflow",
      "What happened",
      "Took",
      "Started",
    ]);
    for (const h of headers) expect(h).toHaveAttribute("scope", "col");
  });

  it("names the table from a caption when one is given", () => {
    renderTable({ "aria-label": undefined, caption: "Recorded runs" });
    expect(screen.getByRole("table", { name: "Recorded runs" })).toBeInTheDocument();
  });

  it("adds one caption row per group, in row order", () => {
    const { container } = renderTable({ groupBy: (r) => r.day });
    const captions = [...container.querySelectorAll('th[scope="rowgroup"]')].map(
      (th) => th.textContent,
    );
    expect(captions).toEqual(["Today", "Yesterday"]);
    // Each caption heads its own group of rows.
    const bodies = container.querySelectorAll("tbody");
    expect(bodies).toHaveLength(2);
    expect(within(bodies[0] as HTMLElement).getAllByRole("link")).toHaveLength(2);
    expect(within(bodies[1] as HTMLElement).getAllByRole("link")).toHaveLength(1);
  });

  it("adds no captions without groupBy", () => {
    const { container } = renderTable();
    expect(container.querySelector('th[scope="rowgroup"]')).toBeNull();
  });

  it("marks only the selected row aria-selected", () => {
    renderTable({ selectedKey: "41f9aa02" });
    const rows = dataRows();
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveAttribute("aria-selected", "true");
    expect(rows[0]).not.toHaveAttribute("aria-selected");
    expect(rows[2]).not.toHaveAttribute("aria-selected");
  });

  it("right-aligns numeric columns in tabular figures and keeps the header aligned", () => {
    renderTable();
    const header = screen.getByRole("columnheader", { name: "Took" });
    expect(header.className).toContain("text-end");
    const cell = screen.getByText("8400").closest("td");
    expect(cell?.className).toContain("text-end");
    expect(cell?.className).toContain("tabular-nums");
    expect(cell?.className).toContain("font-sans");
  });

  it("shows an absent figure as a dash, never zero", () => {
    renderTable();
    const nullRow = dataRows()[2] as HTMLElement;
    expect(within(nullRow).getByText("—")).toBeInTheDocument();
    expect(within(nullRow).queryByText("0")).toBeNull();
  });

  it("hides hideOnPhone columns at 760px and below, header and cells alike", () => {
    renderTable();
    const header = screen.getByRole("columnheader", { name: "Started" });
    expect(header.className).toContain("max-[760px]:hidden");
    const cell = screen.getByText("Yesterday").closest("td");
    expect(cell?.className).toContain("max-[760px]:hidden");
    expect(screen.getByRole("columnheader", { name: "Workflow" }).className).not.toContain(
      "max-[760px]:hidden",
    );
  });

  it("turns rows into blocks on phones only when stack is set", () => {
    const { rerender } = renderTable();
    expect(screen.getByRole("table").className).not.toContain("max-[760px]:block");
    expect(dataRows()[0]?.className).not.toContain("max-[760px]:flex");

    rerender(
      <MemoryRouter>
        <DataTable aria-label="Runs" stack columns={COLUMNS} rows={RUNS} getRowKey={(r) => r.id} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("table").className).toContain("max-[760px]:block");
    expect(dataRows()[0]?.className).toContain("max-[760px]:flex");
    // The sentence keeps a whole line; status and sentence are never dropped.
    const sentence = screen.getByText("Stopped at generate_api").closest("td");
    expect(sentence?.className).toContain("max-[760px]:basis-full");
    // Block layout labels a value with its column name.
    expect(within(dataRows()[0] as HTMLElement).getByText("Took")).toBeInTheDocument();
  });

  it("keeps hideOnPhone columns hidden in the phone block layout", () => {
    // tailwind-merge keeps the later of two display classes, so the order in
    // which stack and hideOnPhone are applied decides whether the column drops.
    renderTable({ stack: true });
    const header = screen.getByRole("columnheader", { name: "Started" });
    expect(header.className).toContain("max-[760px]:hidden");
    expect(header.className).not.toContain("max-[760px]:block");
    const cell = screen.getAllByText("Yesterday", { selector: "td" })[0] as HTMLElement;
    expect(cell.className).toContain("max-[760px]:hidden");
    expect(cell.className).not.toContain("max-[760px]:block");
  });

  it("moves the select rail from the first cell to the row in the phone block layout", () => {
    renderTable({ stack: true, selectedKey: "41f9aa02" });
    const row = dataRows()[1] as HTMLElement;
    expect(row.className).toContain("max-[760px]:aria-selected:shadow-");
    expect(row.className).toContain("min-[760px]:[&[aria-selected=true]>td:first-child]:shadow-");
  });

  it("styles the ledger variant as mono ink cells without hover", () => {
    renderTable({ variant: "ledger" });
    expect(dataRows()[0]?.className).not.toContain("hover:bg-el-select-soft");
    expect(screen.getByText("Waiting for approval").closest("td")?.className).toContain(
      "font-mono",
    );
  });

  it("styles code inside a sentence as a mono identifier", () => {
    render(
      <SentenceCell>
        Stopped <code>generate_api</code>
      </SentenceCell>,
    );
    const sentence = screen.getByText(/Stopped/);
    expect(sentence.className).toContain("text-[15px]");
    expect(sentence.className).toContain("[&_code]:font-mono");
    expect(screen.getByText("generate_api").tagName).toBe("CODE");
  });

  it("renders the entity as a link with its id under it in mono", () => {
    renderTable();
    const link = screen.getByRole("link", { name: "fullstack_generation" });
    expect(link).toHaveAttribute("href", "/runs/c718044a");
    const id = screen.getByText("c718044a");
    expect(id.className).toContain("font-mono");
    expect(id.tagName).toBe("SPAN");
  });

  it("renders a plain href entity as an anchor", () => {
    render(<EntityCell href="https://example.test/x" name="external" />);
    expect(screen.getByRole("link", { name: "external" })).toHaveAttribute(
      "href",
      "https://example.test/x",
    );
  });
});

describe("DataTable loading and empty", () => {
  it("keeps the header and shows five skeleton rows while loading", () => {
    const { container } = renderTable({ loading: true, rows: [] });
    expect(screen.getByRole("table")).toHaveAttribute("aria-busy", "true");
    expect(screen.getAllByRole("columnheader")).toHaveLength(COLUMNS.length);
    expect(container.querySelectorAll('[data-slot="skeleton-row"]')).toHaveLength(5);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("does not show real rows or the empty state while loading", () => {
    renderTable({ loading: true, empty: "No runs yet." });
    expect(screen.queryByText("No runs yet.")).toBeNull();
    expect(screen.queryByText("fullstack_generation")).toBeNull();
  });

  it("is not busy once loaded", () => {
    renderTable();
    expect(screen.getByRole("table")).not.toHaveAttribute("aria-busy");
  });

  it("renders the empty state under the header when there are no rows", () => {
    renderTable({
      rows: [],
      empty: <p>No runs match. Clear the filters to see every run.</p>,
    });
    expect(screen.getByText(/No runs match/)).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(COLUMNS.length);
    expect(screen.getByText(/No runs match/).closest("td")).toHaveAttribute(
      "colspan",
      String(COLUMNS.length),
    );
  });

  it("does not show the empty state when there are rows", () => {
    renderTable({ empty: <p>Nothing here.</p> });
    expect(screen.queryByText("Nothing here.")).toBeNull();
  });
});

describe("DataTable keyboard cursor", () => {
  it("starts on the first row, moves with j and k, and activates on Enter", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate });

    expect(dataRows()[0]).toHaveAttribute("data-cursor", "true");

    fireEvent.keyDown(window, { key: "j" });
    expect(dataRows()[1]).toHaveAttribute("data-cursor", "true");
    expect(dataRows()[0]).not.toHaveAttribute("data-cursor");
    expect(dataRows()[1]).toHaveFocus();

    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).toHaveBeenCalledTimes(1);
    expect(onRowActivate).toHaveBeenLastCalledWith(RUNS[1]);

    fireEvent.keyDown(window, { key: "k" });
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).toHaveBeenLastCalledWith(RUNS[0]);
  });

  it("stops at the first and last rows", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate });
    fireEvent.keyDown(window, { key: "k" });
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).toHaveBeenLastCalledWith(RUNS[0]);

    for (let i = 0; i < 6; i += 1) fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).toHaveBeenLastCalledWith(RUNS[2]);
  });

  it("ignores j, k and Enter while an input has focus", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate });
    const input = screen.getByLabelText("Search");
    input.focus();

    fireEvent.keyDown(input, { key: "j" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRowActivate).not.toHaveBeenCalled();
    expect(dataRows()[0]).toHaveAttribute("data-cursor", "true");

    // Once focus leaves the field the cursor still sits on row 0: j never moved it.
    input.blur();
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).toHaveBeenLastCalledWith(RUNS[0]);
  });

  it("ignores j and k in a textarea, a select and a contenteditable element", () => {
    renderTable();
    for (const tag of ["textarea", "select"]) {
      const el = document.createElement(tag);
      document.body.append(el);
      el.focus();
      fireEvent.keyDown(el, { key: "j" });
      el.remove();
    }
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    editable.tabIndex = 0;
    document.body.append(editable);
    editable.focus();
    fireEvent.keyDown(editable, { key: "j" });
    editable.remove();
    expect(dataRows()[0]).toHaveAttribute("data-cursor", "true");
  });

  it("leaves Enter to a focused link so the link is followed natively", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate });
    screen.getByRole("link", { name: "bug_resolution" }).focus();
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).not.toHaveBeenCalled();
  });

  it("follows focus: tabbing onto a row's link moves the cursor to that row", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate });
    const link = screen.getByRole("link", { name: "code_review" });
    act(() => link.focus());
    expect(dataRows()[2]).toHaveAttribute("data-cursor", "true");
    // With focus off the link, Enter now acts on that row.
    act(() => link.blur());
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).toHaveBeenLastCalledWith(RUNS[2]);
  });

  it("ignores keys with Ctrl, Alt or Meta held", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate });
    fireEvent.keyDown(window, { key: "j", ctrlKey: true });
    fireEvent.keyDown(window, { key: "j", metaKey: true });
    fireEvent.keyDown(window, { key: "Enter", altKey: true });
    expect(onRowActivate).not.toHaveBeenCalled();
    expect(dataRows()[0]).toHaveAttribute("data-cursor", "true");
  });

  it("stays quiet while a dialog is open", () => {
    const onRowActivate = vi.fn();
    render(
      <MemoryRouter>
        <div role="dialog" aria-label="Re-run" tabIndex={-1} data-testid="dlg" />
        <DataTable
          aria-label="Runs"
          columns={COLUMNS}
          rows={RUNS}
          getRowKey={(r) => r.id}
          onRowActivate={onRowActivate}
        />
      </MemoryRouter>,
    );
    screen.getByTestId("dlg").focus();
    fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).not.toHaveBeenCalled();
  });

  it("does not bind keys when hotkeys is off", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate, hotkeys: false });
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).not.toHaveBeenCalled();
  });

  it("removes its window listener on unmount", () => {
    const onRowActivate = vi.fn();
    const { unmount } = renderTable({ onRowActivate });
    unmount();
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).not.toHaveBeenCalled();
  });

  it("supports a controlled cursor", () => {
    const onCursorChange = vi.fn();
    renderTable({ cursorKey: "41f9aa02", onCursorChange });
    expect(dataRows()[1]).toHaveAttribute("data-cursor", "true");
    fireEvent.keyDown(window, { key: "j" });
    expect(onCursorChange).toHaveBeenCalledTimes(1);
    expect(onCursorChange).toHaveBeenCalledWith("9e21b0d4");
  });

  it("falls back to the first row when the cursor row is filtered out", () => {
    const onRowActivate = vi.fn();
    const { rerender } = renderTable({ cursorKey: "9e21b0d4", onRowActivate });
    rerender(
      <MemoryRouter>
        <DataTable
          aria-label="Runs"
          columns={COLUMNS}
          rows={RUNS.slice(0, 2)}
          getRowKey={(r) => r.id}
          cursorKey="9e21b0d4"
          onRowActivate={onRowActivate}
        />
      </MemoryRouter>,
    );
    expect(dataRows()[0]).toHaveAttribute("data-cursor", "true");
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).toHaveBeenLastCalledWith(RUNS[0]);
  });

  it("does nothing on j, k or Enter when there are no rows", () => {
    const onRowActivate = vi.fn();
    renderTable({ rows: [], onRowActivate, empty: "None." });
    fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onRowActivate).not.toHaveBeenCalled();
  });
});

describe("DataTable pointer", () => {
  it("activates a row on a click outside its links", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate });
    fireEvent.click(screen.getByText("Waiting for approval"));
    expect(onRowActivate).toHaveBeenCalledTimes(1);
    expect(onRowActivate).toHaveBeenCalledWith(RUNS[1]);
    expect(dataRows()[1]).toHaveAttribute("data-cursor", "true");
  });

  it("leaves a click on the entity link to the link", () => {
    const onRowActivate = vi.fn();
    renderTable({ onRowActivate });
    fireEvent.click(screen.getByRole("link", { name: "bug_resolution" }));
    expect(onRowActivate).not.toHaveBeenCalled();
  });

  it("is not clickable when nothing handles activation", () => {
    renderTable();
    expect(dataRows()[0]?.className).not.toContain("cursor-pointer");
  });

  it("keeps the row out of the tab order: the entity link is the tab stop", () => {
    renderTable();
    for (const row of dataRows()) expect(row).toHaveAttribute("tabindex", "-1");
    expect(screen.getAllByRole("link")).toHaveLength(3);
  });
});
