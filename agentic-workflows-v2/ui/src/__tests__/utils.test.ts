import { describe, expect, it } from "vitest";
import { cn } from "../lib/utils";

describe("cn", () => {
  it("keeps a text color next to the custom text-micro size", () => {
    expect(cn("text-el-ink", "text-micro")).toBe("text-el-ink text-micro");
  });

  it("treats text-micro as a font size that overrides other sizes", () => {
    expect(cn("text-xs", "text-micro")).toBe("text-micro");
    expect(cn("text-micro", "text-sm")).toBe("text-sm");
  });
});
