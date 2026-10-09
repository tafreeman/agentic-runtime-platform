---
name: Agentic Runtime Platform Dashboard
description: Evidence Ledger — a warm-paper, ink-on-ledger operator console for inspecting AI workflow runs.
colors:
  canvas: "#f2efe8"
  surface: "#f8f5ef"
  surface-raised: "#fffdfa"
  surface-subtle: "#ede9e0"
  surface-hover: "#e8e3d9"
  ink: "#1b1b18"
  ink-secondary: "#49453f"
  ink-muted: "#5a554c"
  ink-faint: "#6a645a"
  divider: "#bdb7aa"
  divider-soft: "#d3cec4"
  divider-faint: "#e2ddd4"
  control-border: "#857f73"
  action: "#1c1d19"
  action-ink: "#f8f5ef"
  accent: "#ef5a36"
  accent-strong: "#b6381e"
  accent-soft: "#f6ddd4"
  focus: "#9e321c"
  success: "#236c4b"
  warning: "#7a5317"
  danger: "#a33228"
  info: "#2f6788"
  plum: "#695385"
  plum-soft: "#e6dff1"
typography:
  display:
    fontFamily: "Georgia, 'Times New Roman', serif"
  body:
    fontFamily: "'Geist Variable', Inter, system-ui, -apple-system, sans-serif"
  micro:
    fontFamily: "'Geist Variable', Inter, system-ui, sans-serif"
    fontSize: "11px"
    lineHeight: "15px"
  metadata:
    fontSize: "11px"
  mono:
    fontFamily: "ui-monospace, 'Cascadia Code', 'SFMono-Regular', Consolas, monospace"
rounded:
  sm: "2px"
  md: "4px"
  lg: "8px"
spacing:
  page-gutter: "40px"
  nav-width: "216px"
  header-height: "56px"
components:
  badge:
    rounded: "{rounded.sm}"
  button-primary:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-ink}"
    rounded: "{rounded.md}"
    height: "36px"
  input:
    rounded: "{rounded.md}"
    height: "40px"
---

# Design System: Agentic Runtime Platform Dashboard

Values are authoritative in `agentic-workflows-v2/ui/src/styles/tokens.css` (with the verified contrast table); rules are in `docs/ui/evidence-ledger-design-system.md`. Where this file and `tokens.css` disagree, `tokens.css` wins.

## Overview

**Creative North Star: "The Evidence Ledger"**

The system treats each run as an auditable record. Surfaces are warm paper, text is near-black ink, and structure comes from hairline dividers rather than shadows or color fills. The mood is calm, forensic and legible: an operator should read run state like a ledger, not watch a light show.

Density is operator-grade: a fixed 216px nav, a 56px header and 40px page gutters. Serif display type gives records a document feel; sans carries UI; mono carries ids, logs and step output. The paper theme is always the default; dark is a secondary preference, selected with `data-theme` (Tailwind's `dark:` variant is bound to it).

**Key Characteristics:**
- Warm paper neutrals, never pure white or pure black.
- One scarce vermilion accent; status uses its own semantic hues.
- Hairline borders over shadows; small radii.
- Tokens are RGB triplets so opacity modifiers work.

## Colors

Warm-paper neutrals with a single vermilion accent and muted, ink-dark status colors.

### Primary
- **Ledger Ink** (#1b1b18 text, #1c1d19 for primary actions): body text and filled buttons.

### Secondary
- **Vermilion Mark** (#ef5a36; strong #b6381e, soft #f6ddd4): active DAG edges, selection and the single point of emphasis. `accent` is for marks and fills only (below 3:1 on light canvas); accent text and state-bearing rails use `accent-strong`. Focus ring uses Oxblood Focus (#9e321c).
- **Plum** (#695385, soft #e6dff1): the one categorical secondary hue (persona, cloud, kickback/rework). Never a status.

### Neutral
- **Canvas Paper** (#f2efe8), **Page Surface** (#f8f5ef), **Raised Sheet** (#fffdfa), **Subtle Fill** (#ede9e0), **Hover Fill** (#e8e3d9): layered backgrounds.
- **Secondary / Muted / Faint Ink** (#49453f / #5a554c / #6a645a): text hierarchy. Every tier is at least 4.5:1 on every surface in both themes.
- **Divider** (#bdb7aa), soft (#d3cec4), faint (#e2ddd4): decorative hairlines (~1.7:1).
- **Control Border** (#857f73; dark #8a8276): the at-least-3:1 boundary for inputs, selects, textareas and graph nodes. Dividers must not be the only boundary of an interactive control.

### Status
- **Success** #236c4b, **Warning** #7a5317, **Danger** #a33228, **Info** #2f6788, each with a soft tint background and at least 4.5:1 on its tint.

### Dark theme (`[data-theme="dark"]`)
ink-muted #c4baad, ink-faint #b2aa9f, success #6ec497, danger #fa8c7e, plum #b8a1d8, plum-soft #3f354e, control-border #8a8276.

### Graph tokens
Graph code uses the `--el-graph-*` set (node, node-border, step status, edges, badges) via `rgb(var(--el-graph-x))` or the matching `bg-/text-/border-/stroke-el-graph-x` classes, never `rgb()` or hex literals. Canvas #ede9e0 with a decorative grid #c7c1b5.

### Named Rules
**The One Mark Rule.** Vermilion marks the thing the operator should look at now (active edge, selection). It never decorates.
**The One Signal Rule.** One thing per view carries vermilion; accent text and state rails use `accent-strong`.
**The Triplet Rule.** Define colors as RGB triplets under `--el-*`; new code uses `el-*` or shadcn semantic tokens.
**The Floor Rule.** No essential text below 11px, no text tier below 4.5:1, no control boundary below 3:1, no focus indicator below a solid 2px ring.

## Typography

**Display Font:** Georgia (serif fallback stack)
**Body Font:** Geist Variable (Inter, system-ui fallback)
**Mono Font:** ui-monospace / Cascadia Code / Consolas

**Character:** Document serif for titles against a neutral UI sans, with mono for machine output. Scale floor: `text-micro` (11px/15px) for labels, IDs, timestamps and tags; `text-xs` (12px) for secondary copy; `text-sm` (14px) for controls; inputs use 13px. Nothing essential is smaller than 11px. No eyebrow labels above headings.

### Named Rules
**The Machine Text Rule.** Monospace only for ids, code, CLI commands, logs and aligned numbers, never as decoration.

## Layout

App shell: fixed left nav (216px), 56px header, 40px page gutter. Metrics use the ruled **Scoreline** (aligned columns between hairline rules), not KPI cards. At most one notice above a page's data. DAG graph surfaces use a recessed canvas with a muted grid.

## Elevation & Depth

Flat by default; depth comes from tonal layering (canvas, surface, raised sheet) and hairline dividers. One shadow exists: raised overlays (`0 16px 40px rgb(27 27 24 / 0.12)`).

### Named Rules
**The Flat-Ledger Rule.** Cards and panels never carry shadows; only popovers/overlays do.

## Shapes

Radii are 2/4/8 only: 2px (sm, badges and tags), 4px (md, buttons, inputs, menus), 8px (lg, dialogs and sheets). 1px borders. Pills only for tiny status dots.

## Motion

120ms fast (hover, focus, button feedback), 180ms standard, 240ms slow (drawers, sheets, graph settle). Animate paint properties only: never width, height or padding, and never `transition-all`. Under `prefers-reduced-motion` every loop stops, transform and size changes snap, and paint feedback is capped at 120ms.

## Components

Built on owned shadcn sources in `ui/src/components/ui/` mapped to `--el-*` tokens (`--primary` = action ink, `--ring` = focus, `--accent` = accent-soft, `--input` = control-border). Active DAG edges animate with a dash flow.

### Buttons
- **Shape:** 4px radius, 1px border, `text-sm` semibold, 150ms color transition.
- **Default:** ink fill (#1c1d19), paper text, hover ink at 90%.
- **Outline / Secondary / Ghost:** divider border or subtle fill; hover to Subtle/Hover Fill. **Destructive:** danger fill, raised-surface text (AA in both themes).
- **Sizes:** default h-40px, lg 44px, sm 32px, xs 28px; icon variants square. Compact sizes keep a 36px minimum hit area via an invisible overlay.
- **Disabled:** 45% opacity.

### Inputs / Fields
- **Style:** 40px tall, 4px radius, 1px `control-border`, Raised Sheet fill, 13px text, no shadow.
- **Focus:** `focus-ring` and border shift to Oxblood Focus. **Error:** danger border. **Disabled:** subtle fill, 50% opacity.

### Focus
`focus-ring`: a 2px `--el-focus` outline with 2px offset on `:focus-visible`. `focus-ring-inset` (offset -2px) for rows, tabs and anything inside `overflow-hidden`. Custom interactive elements must adopt one of them.

### Status marker
`StatusBadge`: icon, sentence-case word and semantic color. It is the one vocabulary for runs, steps, DAG nodes, evaluations and gates; it replaces the `[ ok ]` / `[fail]` labels. Badges (`ui/badge.tsx`) are 20px tall, 2px radius, 12px medium text.

### Tier mark
`TierMark`: `T0` to `T5` with an accessible "Tier N — capability tier" description.

### Scoreline
Ruled metric band of `dl` columns between hairlines; replaces KPI cards. No data renders an em dash with a "no data" label, never 0, 0.0% or NaN.

### Navigation
Seven destinations, each an icon plus a sentence-case label, no section numbers. On mobile: four destinations plus a labeled **More** sheet. The palette hint reads ⌘K on Apple platforms and Ctrl K elsewhere.

### Offline banner
One shell-level notice with the `just dev` remedy and a Retry. API-backed actions are disabled with a visible reason.

### Cards / Containers
Page Surface fill, 1px divider border, no shadow. Prefer plain tokenized containers; the old `.card`/`.btn` utilities no longer exist in `globals.css`.

### Domain surfaces
Feature areas under `components/`: dag (run graph), runs, live (streaming), evaluations, datasets, models, editor, settings, dashboard, layout (shell), states (empty/error/loading).

## Do's and Don'ts

### Do:
- **Do** use `el-*` or shadcn semantic tokens and keep the paper theme as default.
- **Do** separate regions with 1px dividers and tonal steps.
- **Do** use the Scoreline for metrics, StatusBadge for every status, and `focus-ring` on custom controls.
- **Do** show an em dash with a "no data" label instead of 0, 0.0% or NaN.
- **Do** show a CLI equivalent only when a real `agentic` command exists.

### Don't:
- **Don't** add new uses of the legacy `b-*` classes or `--b-*` aliases.
- **Don't** use pure #fff/#000 or drop shadows on panels.
- **Don't** convey status by color alone; pair with a label or icon.
- **Don't** use KPI card mosaics, eyebrows above headings, or decorative section numbers.
- **Don't** animate width, height or padding, and don't use `transition-all`.
- **Don't** stack page banners under the shell banner.
- **Don't** add presentational controls with no backend behavior.

## Enforcement

The rules are guarded by tests in `agentic-workflows-v2/ui/src/__tests__/`:
- `designDrift.test.ts` fails on type below 11px, inline `fontSize` below 11, hex/rgb/hsl literals in TS/TSX not backed by `var(--el-*)`, `transition-all`, and transitions on layout properties.
- `tokens.contrast.test.ts` checks WCAG AA for every ink/surface pair in both themes, focus ring at least 3:1, and a dark override for every paper colour.

## Exemptions and legacy

- `styles/prototype-lab.css` is an intentional lab page exempt from these rules (Inter, grid background, its own transitions).
- Legacy `b-*` classes and `--b-*` variables are frozen aliases: do not rename existing call sites, and do not add new uses.
