import { describe, expect, it } from "vitest";
import tokensCss from "../styles/tokens.css?raw";

/*
 * Contrast guard for the Evidence Ledger tokens.
 *
 * Reads styles/tokens.css itself and resolves each theme the way the cascade
 * does (paper on :root, dark layered over it), then checks WCAG contrast for
 * every pairing the design system allows. Edit a token and this names the exact
 * pairs that broke in which theme, so keeping two themes honest costs one run.
 *
 * Raw `accent` is a fill and stroke colour, not a text ink: text uses
 * `accent-strong`. It is deliberately absent from the matrix.
 */

type Rgb = readonly [number, number, number];
type TokenMap = ReadonlyMap<string, string>;

interface Rule {
  selectors: string[];
  declarations: [string, string][];
}

const THEMES = ["paper", "dark"] as const;
type Theme = (typeof THEMES)[number];

const AA_TEXT = 4.5;
const AA_UI = 3;

const NEUTRAL_SURFACES = [
  "canvas",
  "surface",
  "surface-raised",
  "surface-subtle",
  "surface-hover",
] as const;

const TEXT_INK = [
  "ink",
  "ink-secondary",
  "ink-muted",
  "ink-faint",
  "accent-strong",
  "success",
  "warning",
  "danger",
  "info",
  "plum",
] as const;

// Status ink sits on its own tint; faint ink is neutral-surface only.
const TINTED_PAIRS: readonly (readonly [string, string])[] = [
  ["accent-strong", "accent-soft"],
  ["success", "success-soft"],
  ["warning", "warning-soft"],
  ["danger", "danger-soft"],
  ["info", "info-soft"],
  ["plum", "plum-soft"],
  ["action-ink", "action"],
];

// Mid-tone colours that read on both canvases, so dark need not override them.
const SHARED_ACROSS_THEMES = new Set(["--el-chart-3"]);

const PAPER_SELECTOR = '[data-theme="paper"]';
const DARK_SELECTOR = '[data-theme="dark"]';

function parseRules(source: string): Rule[] {
  const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: Rule[] = [];
  // Flat rules only: the @keyframes at the end nest and carry no tokens.
  for (const [, selectorText = "", body = ""] of withoutComments.matchAll(
    /([^{}]+)\{([^{}]*)\}/g,
  )) {
    const declarations = body
      .split(";")
      .map((declaration) => declaration.trim())
      .filter((declaration) => declaration.startsWith("--"))
      .map((declaration): [string, string] => {
        const colon = declaration.indexOf(":");
        return [
          declaration.slice(0, colon).trim(),
          declaration.slice(colon + 1).trim(),
        ];
      });
    rules.push({
      selectors: selectorText.split(",").map((selector) => selector.trim()),
      declarations,
    });
  }
  return rules;
}

const RULES = parseRules(tokensCss);

function themeTokens(theme: Theme): TokenMap {
  const own = theme === "dark" ? DARK_SELECTOR : PAPER_SELECTOR;
  const tokens = new Map<string, string>();
  for (const { selectors, declarations } of RULES) {
    if (!selectors.includes(":root") && !selectors.includes(own)) continue;
    for (const [name, value] of declarations) tokens.set(name, value);
  }
  return tokens;
}

function resolve(tokens: TokenMap, name: string, trail: string[] = []): string {
  if (trail.includes(name)) {
    throw new Error(`Circular token reference: ${[...trail, name].join(" -> ")}`);
  }
  const value = tokens.get(name);
  if (value === undefined) throw new Error(`Token ${name} is not defined`);
  const alias = /^var\(\s*(--[\w-]+)\s*\)$/.exec(value);
  return alias?.[1] ? resolve(tokens, alias[1], [...trail, name]) : value;
}

function rgb(tokens: TokenMap, token: string): Rgb {
  const value = resolve(tokens, `--el-${token}`);
  const channels = value.split(/\s+/).map(Number);
  if (
    channels.length !== 3 ||
    channels.some((channel) => !Number.isInteger(channel) || channel < 0 || channel > 255)
  ) {
    throw new Error(`--el-${token} is not an "R G B" triplet: "${value}"`);
  }
  return channels as unknown as Rgb;
}

function luminance([r, g, b]: Rgb): number {
  const linear = (channel: number) => {
    const scaled = channel / 255;
    return scaled <= 0.04045 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrast(a: Rgb, b: Rgb): number {
  const first = luminance(a);
  const second = luminance(b);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

function cross(
  foregrounds: readonly string[],
  backgrounds: readonly string[],
): [string, string][] {
  return foregrounds.flatMap((fg) =>
    backgrounds.map((bg): [string, string] => [fg, bg]),
  );
}

function failingPairs(
  tokens: TokenMap,
  pairs: readonly (readonly [string, string])[],
  minimum: number,
): string[] {
  const failures: string[] = [];
  for (const [fg, bg] of pairs) {
    const ratio = contrast(rgb(tokens, fg), rgb(tokens, bg));
    if (ratio < minimum) {
      failures.push(`${fg} on ${bg} = ${ratio.toFixed(2)}:1 (needs ${minimum}:1)`);
    }
  }
  return failures;
}

describe.each(THEMES)("%s theme tokens", (theme) => {
  const tokens = themeTokens(theme);

  it("keeps text at WCAG AA on every neutral surface", () => {
    expect(
      failingPairs(tokens, cross(TEXT_INK, NEUTRAL_SURFACES), AA_TEXT),
    ).toEqual([]);
  });

  it("keeps status ink at WCAG AA on its own tint", () => {
    expect(failingPairs(tokens, TINTED_PAIRS, AA_TEXT)).toEqual([]);
  });

  it("keeps the focus ring visible on every neutral surface", () => {
    expect(
      failingPairs(tokens, cross(["focus"], NEUTRAL_SURFACES), AA_UI),
    ).toEqual([]);
  });

  it("keeps control boundaries (inputs, selects, graph nodes) at 3:1", () => {
    expect(
      failingPairs(tokens, cross(["control-border"], NEUTRAL_SURFACES), AA_UI),
    ).toEqual([]);
  });
});

describe("token parsing", () => {
  it("computes WCAG contrast ratios", () => {
    expect(contrast([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 5);
    expect(contrast([119, 119, 119], [255, 255, 255])).toBeCloseTo(4.48, 2);
  });

  it("layers dark over paper and resolves aliases per theme", () => {
    const paper = themeTokens("paper");
    const dark = themeTokens("dark");
    expect(rgb(dark, "canvas")).not.toEqual(rgb(paper, "canvas"));
    expect(rgb(paper, "neutral")).toEqual(rgb(paper, "ink-muted"));
    expect(rgb(dark, "neutral")).toEqual(rgb(dark, "ink-muted"));
  });

  it("gives dark an override for every literal paper colour", () => {
    const literalTriplet = /^\d+\s+\d+\s+\d+$/;
    const paperColours = RULES.filter(
      ({ selectors }) =>
        selectors.includes(":root") && !selectors.includes(DARK_SELECTOR),
    )
      .flatMap(({ declarations }) => declarations)
      .filter(([name, value]) => name.startsWith("--el-") && literalTriplet.test(value))
      .map(([name]) => name);
    const darkOverrides = new Set(
      RULES.filter(
        ({ selectors }) =>
          selectors.includes(DARK_SELECTOR) && !selectors.includes(":root"),
      ).flatMap(({ declarations }) => declarations.map(([name]) => name)),
    );

    expect(paperColours.length).toBeGreaterThan(20);
    expect(
      paperColours.filter(
        (name) => !darkOverrides.has(name) && !SHARED_ACROSS_THEMES.has(name),
      ),
    ).toEqual([]);
  });
});
