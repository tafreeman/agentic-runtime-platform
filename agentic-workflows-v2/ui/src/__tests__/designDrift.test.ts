import { describe, expect, it } from "vitest";

/*
 * Design-drift guard for the Evidence Ledger system (DESIGN.md).
 *
 * Scans every non-test source file and fails on patterns the critique/audit
 * pass removed, so a regression shows up in CI instead of the next audit:
 *   - type below the 11px floor (`text-[10px]`, inline `fontSize: 10`)
 *   - colour literals in TS/TSX — use el-* / --el-graph-* tokens instead
 *   - `transition-all` and transitions on layout properties
 *
 * tokens.css defines the palette and prototype-lab.css is an intentional lab
 * page (documented in DESIGN.md), so both are exempt.
 */

const SOURCES = import.meta.glob<string>("../**/*.{ts,tsx,css}", {
  query: "?raw",
  import: "default",
  eager: true,
});

const EXEMPT = [
  /\/__tests__\//,
  /\.test\.tsx?$/,
  /\/test\//,
  /\/styles\/tokens\.css$/,
  /\/styles\/prototype-lab\.css$/,
];

const TYPE_FLOOR_PX = 11;

interface Rule {
  readonly name: string;
  readonly appliesTo: RegExp;
  readonly find: (code: string) => string[];
}

function matches(code: string, pattern: RegExp): string[] {
  return [...code.matchAll(pattern)].map((m) => m[0]);
}

function belowFloor(code: string, pattern: RegExp): string[] {
  return [...code.matchAll(pattern)]
    .filter((m) => Number(m[1]) < TYPE_FLOOR_PX)
    .map((m) => m[0]);
}

const RULES: readonly Rule[] = [
  {
    name: "arbitrary text size below the 11px floor (use text-micro or text-xs)",
    appliesTo: /\.(tsx?|css)$/,
    find: (code) => belowFloor(code, /text-\[(\d+(?:\.\d+)?)px\]/g),
  },
  {
    name: "inline fontSize below the 11px floor",
    appliesTo: /\.tsx?$/,
    find: (code) =>
      belowFloor(code, /fontSize:\s*["'`]?(\d+(?:\.\d+)?)(?:px)?["'`]?(?=\s*[,}\n])/g),
  },
  {
    name: "CSS font-size below the 11px floor",
    appliesTo: /\.css$/,
    find: (code) => belowFloor(code, /font-size:\s*(\d+(?:\.\d+)?)px/g),
  },
  {
    name: "hex colour literal (use an el-* or --el-graph-* token)",
    appliesTo: /\.tsx?$/,
    find: (code) => matches(code, /["'`\s(:]#[0-9a-fA-F]{3,8}(?=["'`\s,;)])/g),
  },
  {
    name: "rgb()/hsl() literal not backed by a token (use rgb(var(--el-*)))",
    appliesTo: /\.tsx?$/,
    find: (code) => matches(code, /\b(?:rgb|hsl)a?\((?!\s*var\()[^)]*\)/g),
  },
  {
    name: "transition-all / transition: all (name the properties)",
    appliesTo: /\.(tsx?|css)$/,
    find: (code) => matches(code, /\btransition-all\b|transition:\s*all\b/g),
  },
  {
    name: "transition on a layout property (animate transform/opacity, or snap)",
    appliesTo: /\.(tsx?|css)$/,
    find: (code) =>
      matches(
        code,
        /transition-\[(?:width|height|top|left|right|bottom|margin|padding)[^\]]*\]|transition(?:Property)?:\s*["'`]?(?:width|height|top|left|right|bottom|margin|padding)\b/g,
      ),
  },
];

/** Drop comments so prose about a banned pattern doesn't trip the guard. */
function stripComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
}

function violations(files: Record<string, string>): string[] {
  const found: string[] = [];
  for (const [path, raw] of Object.entries(files)) {
    if (EXEMPT.some((pattern) => pattern.test(path))) continue;
    const code = stripComments(raw);
    for (const rule of RULES) {
      if (!rule.appliesTo.test(path)) continue;
      for (const hit of rule.find(code)) found.push(`${path}: ${hit.trim()} — ${rule.name}`);
    }
  }
  return found;
}

describe("design drift", () => {
  it("scans the source tree", () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
  });

  it("finds no banned patterns in non-test source", () => {
    expect(violations(SOURCES)).toEqual([]);
  });

  // Mutation check: each rule must catch a known-bad sample and pass a
  // compliant one, so a broken regex can't silently turn the guard off.
  it.each([
    ["x.tsx", '<p className="text-[10px]">', "<p className=\"text-[11px]\">"],
    ["x.tsx", "style={{ fontSize: 9 }}", "style={{ fontSize: 12 }}"],
    ["x.css", ".a { font-size: 10px; }", ".a { font-size: 12px; }"],
    ["x.tsx", 'stroke="#9e321c"', 'stroke="rgb(var(--el-accent))"'],
    ["x.tsx", 'fill: "rgba(0, 0, 0, 0.4)"', 'fill: "rgb(var(--el-graph-edge) / 0.4)"'],
    ["x.tsx", 'className="transition-all"', 'className="transition-colors"'],
    ["x.tsx", 'className="transition-[width]"', 'className="transition-transform"'],
  ])("catches a violation in %s: %s", (file, bad, good) => {
    expect(violations({ [`../src/${file}`]: bad })).toHaveLength(1);
    expect(violations({ [`../src/${file}`]: good })).toEqual([]);
  });

  it("ignores banned patterns inside comments and exempt files", () => {
    expect(violations({ "../src/x.tsx": "// was text-[9px]\n/* #fff */" })).toEqual([]);
    expect(violations({ "../styles/tokens.css": ".a { font-size: 9px; }" })).toEqual([]);
    expect(violations({ "../__tests__/a.test.tsx": "text-[9px]" })).toEqual([]);
  });
});
