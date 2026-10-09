---
paths: ["agentic-workflows-v2/ui/**"]
---

# UI design rules (Evidence Ledger)

Applies to any change under `agentic-workflows-v2/ui/`. Context lives in the repo,
so a UI task needs no restated design brief: read `PRODUCT.md` and `DESIGN.md` at
the repo root, then follow these rules. `styles/tokens.css` is the source of truth
for values; `docs/ui/evidence-ledger-design-system.md` for component rules.

## Enforced by tests (CI fails on violation)

- `src/__tests__/designDrift.test.ts`: no text below 11px (`text-[10px]`, inline
  `fontSize` < 11, CSS `font-size` < 11px); no hex, `rgb()` or `hsl()` literals in
  TS/TSX unless written as `rgb(var(--el-*))`; no `transition-all`; no transitions
  on width/height/top/left/margin/padding.
- `src/__tests__/tokens.contrast.test.ts`: every ink tier ≥ 4.5:1 on every surface
  in both themes, status ink on its own tint, focus ≥ 3:1, and a dark override
  for every literal paper colour. Changing a token? Run this test first.
- `src/__tests__/uiPrimitives.test.tsx`: shared primitives keep the compliant focus
  ring and 2px badge radius.

Fix the code, not the guard. Exempt files are listed in `designDrift.test.ts`
(`tokens.css`, the intentional `prototype-lab.css`); don't add to that list to
get a change through.

## Conventions the tests can't see

- Type: `text-micro` (11px) is the floor for labels, IDs and metadata; `text-xs`
  (12px) for secondary copy and anything on an interactive control.
- Colour: `el-*` utilities and `--el-graph-*` tokens for graph code. Raw `accent`
  is for fills and marks; accent *text* uses `accent-strong`. One vermilion
  emphasis per view.
- Focus: the global `:focus-visible` rule draws the 2px `--el-focus` ring. Don't
  add a weaker `ring-1`/`ring-*/50` on top; use `focus-ring` / `focus-ring-inset`
  on custom controls and rows inside `overflow-hidden`.
- Shape: radii 2/4/8px only (badges 2px, controls 4px, dialogs 8px).
- Legacy `b-*` classes are frozen aliases: don't rename call sites, don't add new
  uses.
- States: one shell-level offline banner; "—" for absent data, never 0 or 0.0%;
  disabled actions say why. Keep `api/client.ts`'s `API {status}:` error string
  (tests assert it); add remedies in `lib/apiErrors.ts`.
- Theme: dark is selected with `data-theme`, and Tailwind's `dark:` is bound to
  it. Check both themes for any colour change.

## Verify

`just ui-check` runs coverage (floors in `vitest.config.ts`), all unit tests
including the guards, and the build. For a visual change, also run the app
(`just dev`) and look at the affected page at 1280px and 390px in both themes.
