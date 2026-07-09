import { describe, expect, it } from "vitest";
import { parseBooleanFlag } from "../config/featureFlags";

describe("parseBooleanFlag", () => {
  it.each(["1", "true", "TRUE", " yes ", "on"])("treats %s as enabled", (value) => {
    expect(parseBooleanFlag(value)).toBe(true);
  });

  it.each([undefined, null, "", "0", "false", "off", "disabled"])(
    "treats %s as disabled",
    (value) => {
      expect(parseBooleanFlag(value)).toBe(false);
    }
  );
});
