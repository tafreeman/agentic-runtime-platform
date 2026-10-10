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
    name: "CSS font-size or font shorthand below the 11px floor",
    appliesTo: /\.css$/,
    // Two declarations, because only the shorthand has a line-height slot:
    // `font-size: 10px`, and the size slot of `font: 600 10px/1.2 sans-serif`.
    // The shorthand's leading run excludes `/`, so the lazy prefix can never
    // reach past the size into the line height — `font: 1rem/10px sans-serif`
    // sets a 1rem size and must not be read as 10px type.
    find: (code) => [
      ...belowFloor(code, /(?<![\w-])font-size\s*:\s*(\d+(?:\.\d+)?)px/g),
      ...belowFloor(
        code,
        /(?<![\w-])font\s*:(?:\s*[^;}/]*?\s)?(\d+(?:\.\d+)?)px(?=[\s/;}]|$)/g,
      ),
    ],
  },
  {
    name: "hex colour literal (use an el-* or --el-graph-* token)",
    appliesTo: /\.tsx?$/,
    find: (code) => matches(code, /["'`\s(:]#[0-9a-fA-F]{3,8}(?=["'`\s,;)])/g),
  },
  {
    name: "rgb()/hsl() literal not backed by a token (use rgb(var(--el-*)))",
    appliesTo: /\.tsx?$/,
    // Only design tokens may feed a colour call: `var(--el-*)`, not legacy
    // `--b-*` aliases or an arbitrary `--brand-color`.
    find: (code) => matches(code, /\b(?:rgb|hsl)a?\((?!\s*var\(--el-)[^)]*\)/g),
  },
  {
    name: "transition-all / transition: all (name the properties)",
    appliesTo: /\.(tsx?|css)$/,
    find: (code) => matches(code, /\btransition-all\b|transition:\s*all\b/g),
  },
  {
    name: "transition on a layout property (animate transform/opacity, or snap)",
    appliesTo: /\.(tsx?|css)$/,
    find: layoutTransitions,
  },
];

const LAYOUT_PROPERTY =
  /^(?:width|height|min-width|max-width|min-height|max-height|top|left|right|bottom|inset|margin|padding)(?:-|$)/;

/**
 * Every property named by a transition — Tailwind `transition-[a,b]`, CSS
 * `transition: a 1s, b 1s` / `transition-property`, or inline `transition` /
 * `transitionProperty` — so a layout property listed after an allowed one is
 * still caught.
 */
function layoutTransitions(code: string): string[] {
  const declarations = [
    ...[...code.matchAll(/transition-\[([^\]]+)\]/g)].map((m) => [m[0], m[1] ?? ""]),
    ...[
      ...code.matchAll(
        /transition(?:-property|Property)?\s*:\s*["'`]?([^;"'`}]+)/g,
      ),
    ].map((m) => [m[0], m[1] ?? ""]),
  ];
  return declarations
    .filter(([, value = ""]) =>
      value
        .split(",")
        // The shorthand allows property, duration and easing in any order
        // (`120ms width`), and Tailwind writes spaces as underscores.
        .flatMap((segment) => segment.trim().split(/[\s_]+/))
        .some((token) => LAYOUT_PROPERTY.test(token)),
    )
    .map(([declaration = ""]) => declaration);
}

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
    ["x.css", ".a { font: 10px sans-serif; }", ".a { font: 12px sans-serif; }"],
    ["x.css", ".a { font: 600 10px/1.4 Georgia; }", ".a { font: 600 13px/1.4 Georgia; }"],
    ["x.css", ".a { transition: 120ms width; }", ".a { transition: 120ms opacity; }"],
    ["x.tsx", 'className="transition-[opacity_120ms,width_120ms]"', 'className="transition-[opacity_120ms]"'],
    ["x.tsx", 'stroke="#9e321c"', 'stroke="rgb(var(--el-accent))"'],
    ["x.tsx", 'fill: "rgba(0, 0, 0, 0.4)"', 'fill: "rgb(var(--el-graph-edge) / 0.4)"'],
    ["x.tsx", 'className="transition-all"', 'className="transition-colors"'],
    ["x.tsx", 'className="transition-[width]"', 'className="transition-transform"'],
    ["x.tsx", 'className="transition-[opacity,width]"', 'className="transition-[opacity,transform]"'],
    ["x.css", ".a { transition: opacity 120ms, width 120ms; }", ".a { transition: opacity 120ms, transform 120ms; }"],
    ["x.tsx", 'style={{ transitionProperty: "opacity, height" }}', 'style={{ transitionProperty: "opacity" }}'],
    ["x.tsx", 'color: "rgb(var(--b-purple))"', 'color: "rgb(var(--el-plum))"'],
    ["x.tsx", 'color: "rgb(var(--brand-color) / 0.5)"', 'color: "rgb(var(--el-accent) / 0.5)"'],
  ])("catches a violation in %s: %s", (file, bad, good) => {
    expect(violations({ [`../src/${file}`]: bad })).toHaveLength(1);
    expect(violations({ [`../src/${file}`]: good })).toEqual([]);
  });

  // The `font` shorthand carries the line height after a slash. Only the size
  // slot is type, so a small line height on a compliant size is not a floor
  // violation and must not fail the guard.
  it("reads only the size slot of the font shorthand", () => {
    expect(violations({ "../src/x.css": ".a { font: 1rem/10px sans-serif; }" })).toEqual([]);
    expect(violations({ "../src/x.css": ".a { font: 600 1rem/8px Georgia; }" })).toEqual([]);
    expect(violations({ "../src/x.css": ".a { font: 12px/10px sans-serif; }" })).toEqual([]);
    expect(
      violations({ "../src/x.css": ".a { font: 10px/1.5 sans-serif; }" }),
    ).toHaveLength(1);
  });

  it("ignores banned patterns inside comments and exempt files", () => {
    expect(violations({ "../src/x.tsx": "// was text-[9px]\n/* #fff */" })).toEqual([]);
    expect(violations({ "../styles/tokens.css": ".a { font-size: 9px; }" })).toEqual([]);
    expect(violations({ "../__tests__/a.test.tsx": "text-[9px]" })).toEqual([]);
  });
});
