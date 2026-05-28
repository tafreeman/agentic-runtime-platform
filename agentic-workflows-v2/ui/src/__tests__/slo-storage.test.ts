import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, writeFileSync, readFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import {
  readP95,
  recordLatency,
  InsufficientDataError,
  DEFAULT_MIN_SAMPLES,
} from "../../e2e/slo-storage";

describe("slo-storage", () => {
  let tmpDir: string;
  let tmpFile: string;

  beforeEach(() => {
    tmpDir = mkdtempSync(join(tmpdir(), "slo-storage-"));
    tmpFile = join(tmpDir, "first-span-latency.json");
    writeFileSync(
      tmpFile,
      JSON.stringify({ version: 1, max_records: 1000, records: [] }),
      { encoding: "utf8" }
    );
  });

  afterEach(() => {
    rmSync(tmpDir, { recursive: true, force: true });
  });

  // Sprint B #2: readP95 now throws InsufficientDataError on an empty window
  // instead of returning 0. The old return-0-silently path produced trivial-
  // pass green for `expect(p95).toBeLessThanOrEqual(2000)`.
  it("throws InsufficientDataError when no records exist", async () => {
    await expect(
      readP95({ windowDays: 7, pathOverride: tmpFile })
    ).rejects.toThrow(InsufficientDataError);
  });

  it("throws InsufficientDataError when below minSamples threshold", async () => {
    // 5 records, default minSamples=10 -> must throw.
    const records = Array.from({ length: 5 }, (_, i) => ({
      timestamp: new Date().toISOString(),
      latency_ms: i * 10,
      commit: "test",
    }));
    writeFileSync(
      tmpFile,
      JSON.stringify({ version: 1, max_records: 1000, records }),
      { encoding: "utf8" }
    );
    await expect(
      readP95({ windowDays: 7, pathOverride: tmpFile })
    ).rejects.toThrow(InsufficientDataError);
  });

  it("honors minSamples override below default", async () => {
    // Single record with an explicit minSamples=1 should succeed.
    const records = [
      { timestamp: new Date().toISOString(), latency_ms: 42, commit: "test" },
    ];
    writeFileSync(
      tmpFile,
      JSON.stringify({ version: 1, max_records: 1000, records }),
      { encoding: "utf8" }
    );
    const p95 = await readP95({
      windowDays: 7,
      pathOverride: tmpFile,
      minSamples: 1,
    });
    expect(p95).toBe(42);
  });

  it("exposes DEFAULT_MIN_SAMPLES as 10", () => {
    expect(DEFAULT_MIN_SAMPLES).toBe(10);
  });

  it("records latency and updates the file", async () => {
    await recordLatency(1234, tmpFile);
    const data = JSON.parse(readFileSync(tmpFile, { encoding: "utf8" }));
    expect(data.records).toHaveLength(1);
    expect(data.records[0].latency_ms).toBe(1234);
    expect(data.records[0].timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it("computes p95 as nearest-rank ceil(n*0.95)-1 across 100 samples", async () => {
    // Insert deterministic records 0..99 ms with current timestamps directly,
    // bypassing recordLatency (which would invoke git for each sample).
    const records = Array.from({ length: 100 }, (_, i) => ({
      timestamp: new Date().toISOString(),
      latency_ms: i,
      commit: "test",
    }));
    writeFileSync(
      tmpFile,
      JSON.stringify({ version: 1, max_records: 1000, records }),
      { encoding: "utf8" }
    );
    const p95 = await readP95({ windowDays: 7, pathOverride: tmpFile });
    // Canonical nearest-rank p95 for n=100: ceil(100*0.95)-1 = 94 -> value 94.
    expect(p95).toBe(94);
  });

  it("computes p95 via nearest-rank on small/odd sample counts", async () => {
    // n=20: ceil(20*0.95)-1 = 18 -> sorted[18].
    // Values 1..20 so sorted[18] = 19.
    const records = Array.from({ length: 20 }, (_, i) => ({
      timestamp: new Date().toISOString(),
      latency_ms: i + 1,
      commit: "test",
    }));
    writeFileSync(
      tmpFile,
      JSON.stringify({ version: 1, max_records: 1000, records }),
      { encoding: "utf8" }
    );
    const p95 = await readP95({ windowDays: 7, pathOverride: tmpFile });
    expect(p95).toBe(19);
  });

  it("excludes records older than the windowDays cutoff", async () => {
    // One old record, ten recent records (meets default minSamples=10).
    const oldTs = new Date(Date.now() - 30 * 86400 * 1000).toISOString();
    const records = [
      { timestamp: oldTs, latency_ms: 9999, commit: "old" },
      ...Array.from({ length: 10 }, () => ({
        timestamp: new Date().toISOString(),
        latency_ms: 100,
        commit: "new",
      })),
    ];
    writeFileSync(
      tmpFile,
      JSON.stringify({ version: 1, max_records: 1000, records }),
      { encoding: "utf8" }
    );
    const p95 = await readP95({ windowDays: 7, pathOverride: tmpFile });
    // Only the 10 recent records (100ms each) should be considered; 9999 excluded.
    expect(p95).toBe(100);
  });

  it("trims records when exceeding max_records", async () => {
    // Seed with max_records=3 and 3 existing records, then push one more.
    const records = [
      { timestamp: new Date().toISOString(), latency_ms: 1, commit: "a" },
      { timestamp: new Date().toISOString(), latency_ms: 2, commit: "b" },
      { timestamp: new Date().toISOString(), latency_ms: 3, commit: "c" },
    ];
    writeFileSync(
      tmpFile,
      JSON.stringify({ version: 1, max_records: 3, records }),
      { encoding: "utf8" }
    );
    await recordLatency(4, tmpFile);
    const data = JSON.parse(readFileSync(tmpFile, { encoding: "utf8" }));
    expect(data.records).toHaveLength(3);
    expect(data.records.map((r: { latency_ms: number }) => r.latency_ms)).toEqual([2, 3, 4]);
  });
});
