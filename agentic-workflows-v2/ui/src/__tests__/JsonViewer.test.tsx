import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import JsonViewer from "../components/common/JsonViewer";

describe("JsonViewer", () => {
  it("renders primitive and object values", () => {
    render(
      <JsonViewer
        data={{ enabled: true, retries: 2, nested: { mode: "strict" } }}
        defaultExpanded
      />
    );

    expect(screen.getByText('"enabled"')).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
    expect(screen.getByText('"retries"')).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText('"nested"')).toBeInTheDocument();
    fireEvent.click(screen.getByText("{ {1 keys} }"));
    expect(screen.getByText('"mode"')).toBeInTheDocument();
  });

  it("expands long strings on demand", () => {
    const longValue = "x".repeat(240);
    render(<JsonViewer data={longValue} />);

    expect(screen.getByRole("button", { name: /\.\.\.40 more"/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /\.\.\.40 more"/i }));
    expect(screen.getByText(`"${longValue}"`)).toBeInTheDocument();
  });

  it("toggles collapsed arrays", () => {
    render(<JsonViewer data={[{ id: 1 }, { id: 2 }]} />);

    fireEvent.click(screen.getByText("[ Array(2) ]"));
    const nestedSummaries = screen.getAllByText("{ {1 keys} }");
    nestedSummaries.forEach((summary) => fireEvent.click(summary));
    expect(screen.getAllByText('"id"')).toHaveLength(2);
  });
});
