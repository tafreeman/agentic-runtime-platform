import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  deleteHardwareOverride,
  getHardwareOverride,
  putHardwareOverride,
} from "../api/client";
import type { HardwareOverride } from "../api/hardware";

// Client wrappers for the hardware profile-override contract
// (/api/model-finder/profile-override) — see src/api/hardware.ts.

describe("hardware override API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("getHardwareOverride GETs /api/model-finder/profile-override", async () => {
    const mockResponse = { override: { ram_gb: 64 } };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    } as Response);

    const result = await getHardwareOverride();
    expect(result).toEqual(mockResponse);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:3000/api/model-finder/profile-override",
      undefined,
    );
  });

  it("putHardwareOverride PUTs the override as the JSON body", async () => {
    const override: HardwareOverride = {
      cpu_name: "Ryzen 9",
      cpu_cores_logical: 24,
      ram_gb: 64,
      system_tops: 45,
      accelerators: [
        { kind: "gpu", name: "RTX 5090", memory_gb: 32, tops: 1300 },
      ],
    };
    const mockResponse = { profile: {}, override };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    } as Response);

    await putHardwareOverride(override);

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://localhost:3000/api/model-finder/profile-override");
    expect(init.method).toBe("PUT");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body as string)).toEqual(override);
  });

  it("deleteHardwareOverride DELETEs the override", async () => {
    const mockResponse = { profile: {}, override: null };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    } as Response);

    const result = await deleteHardwareOverride();
    expect(result.override).toBeNull();

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("http://localhost:3000/api/model-finder/profile-override");
    expect(init.method).toBe("DELETE");
  });

  it("surfaces a canonical API error on a failed PUT", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 422,
      text: () => Promise.resolve("ram_gb must be positive"),
    } as Response);

    await expect(putHardwareOverride({ ram_gb: -1 })).rejects.toThrow(
      "API 422: ram_gb must be positive",
    );
  });
});
