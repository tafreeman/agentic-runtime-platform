import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useTheme } from "../hooks/useTheme";

function Probe({ id }: Readonly<{ id: string }>) {
  const [theme, setTheme] = useTheme();
  return (
    <button type="button" onClick={() => setTheme(theme === "dark" ? "paper" : "dark")}>
      {id}:{theme}
    </button>
  );
}

describe("useTheme", () => {
  it("keeps every consumer on the same theme", () => {
    render(
      <>
        <Probe id="sidebar" />
        <Probe id="mobile" />
      </>,
    );
    const before = screen.getByRole("button", { name: /^sidebar:/ }).textContent?.split(":")[1];
    act(() => screen.getByRole("button", { name: /^mobile:/ }).click());
    const after = before === "dark" ? "paper" : "dark";
    expect(screen.getByRole("button", { name: `sidebar:${after}` })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `mobile:${after}` })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe(after);
  });
});
