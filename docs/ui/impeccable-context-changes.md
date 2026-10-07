# Impeccable context changes — UI accessibility pass (2026-10)

`DESIGN.md`, `PRODUCT.md` and `.impeccable/` are maintained locally and are not
tracked in this repository. This page lists the changes to apply to them so the
Impeccable context matches what the accessibility pass shipped. The tracked
sources of truth are `agentic-workflows-v2/ui/src/styles/tokens.css` (values and
the verified contrast table) and
[the Evidence Ledger design system](evidence-ledger-design-system.md) (rules).

## DESIGN.md frontmatter

Paper (default) theme. Changed values are marked; the rest are additions.

```yaml
colors:
  ink-secondary: "#49453f"     # was #514d46
  ink-muted: "#5a554c"         # was #736e64 (4.41:1 on canvas, failed AA)
  ink-faint: "#6a645a"         # was #918b80 (2.95:1 on canvas, failed AA)
  accent-strong: "#b6381e"     # was #b83a20 (4.42:1 on accent-soft)
  control-border: "#857f73"    # new: >=3:1 boundary for inputs, selects, graph nodes
  plum: "#695385"              # new: the one categorical secondary hue; never a status
  plum-soft: "#e6dff1"         # new
typography:
  micro:                       # new: the 11px floor for labels and metadata
    fontFamily: "Geist Variable, Inter, system-ui, sans-serif"
    fontSize: "11px"
    lineHeight: "15px"
  metadata:
    fontSize: "11px"           # was 10px
rounded:
  sm: "2px"                    # badges, tags
  md: "4px"                    # buttons, inputs, menus
  lg: "8px"                    # dialogs, sheets
components:
  badge:
    rounded: "{rounded.sm}"    # was a full pill
  button-primary:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-ink}"
    rounded: "{rounded.md}"
    height: "36px"             # >=36px target; compact sizes keep a 36px hit area
  input:
    rounded: "{rounded.md}"
    height: "40px"
```

Dark theme values (`[data-theme="dark"]`), for the sidecar or a dark section:
ink-muted `#c4baad`, ink-faint `#b2aa9f`, success `#6ec497`, danger `#fa8c7e`,
plum `#b8a1d8`, plum-soft `#3f354e`, control-border `#8a8276`. The dark theme is
selected with `data-theme`, and Tailwind's `dark:` variant is bound to it.

## DESIGN.md body

- **Colors.** Every ink tier is at least 4.5:1 on every surface in both themes.
  `accent` (`#ef5a36`) is for marks and fills only and is below 3:1 on light
  canvas; accent text and state-bearing rails use `accent-strong`. Dividers are
  decorative hairlines; interactive control boundaries use `control-border`.
  Graph code uses the `--el-graph-*` set and never `rgb()` or hex literals.
- **Typography.** Nothing essential below 11px (`text-micro`); `text-xs` (12px)
  is secondary copy. Monospace only for IDs, code, CLI commands, logs and aligned
  numbers. No eyebrow labels above headings.
- **Layout.** Metrics use the ruled **Scoreline** (aligned columns between
  hairline rules), not KPI cards. At most one notice above a page's data.
- **Shapes.** Radii are 2/4/8 only; pills only for tiny status dots.
- **Components.**
  - *Status marker* (`StatusBadge`): icon, sentence-case word and semantic
    color. It is the one vocabulary for runs, steps, DAG nodes, evaluations and
    gates, and replaces the `[ ok ]` / `[fail]` labels.
  - *Tier mark* (`TierMark`): `T0`–`T5` with an accessible "Tier N — capability
    tier" description.
  - *Focus*: `focus-ring` (a 2px `#9e321c` outline with 2px offset on
    `:focus-visible`) and `focus-ring-inset` for rows, tabs and anything inside
    `overflow-hidden`.
  - *Navigation*: seven destinations, each an icon plus a sentence-case label,
    with no section numbers. On mobile, four destinations plus a labeled
    **More** sheet; the palette hint reads ⌘K on Apple platforms and Ctrl K
    elsewhere.
  - *Offline banner*: one shell-level notice with the `just dev` remedy and a
    Retry. API-backed actions are disabled with a visible reason.
- **Do's and Don'ts.**
  - Do show an em dash with a "no data" label instead of 0, 0.0% or NaN.
  - Do show a CLI equivalent only when a real `agentic` command exists.
  - Don't animate width, height or padding, and don't use `transition-all`.
  - Don't stack page banners under the shell banner.
  - Don't add presentational controls with no backend behavior.

## .impeccable/design.json (schemaVersion 2) — merge into `extensions` and `narrative`

```json
{
  "extensions": {
    "colorMeta": {
      "control-border": { "role": "neutral", "displayName": "Control Border", "canonical": "#857f73" },
      "plum": { "role": "tertiary", "displayName": "Plum (categorical)", "canonical": "#695385" }
    },
    "typographyMeta": {
      "micro": { "displayName": "Micro", "purpose": "Type floor: labels, IDs, timestamps, tags (11/15)." }
    },
    "motion": [
      { "name": "motion-fast", "value": "120ms", "purpose": "Hover, focus and button feedback; the cap for color/opacity transitions under reduced motion." },
      { "name": "motion-standard", "value": "180ms", "purpose": "Inspector, tab and content transitions." },
      { "name": "motion-slow", "value": "240ms", "purpose": "Drawer and sheet entry, graph layout settle." },
      { "name": "reduced-motion", "value": "prefers-reduced-motion: reduce", "purpose": "Stop every loop, snap transform and size changes, keep paint-only feedback capped at 120ms." }
    ]
  },
  "components": [
    {
      "name": "Status marker",
      "kind": "chip",
      "description": "The one status vocabulary: icon + sentence-case word + semantic color.",
      "html": "<span class=\"ds-status ds-status--failed\"><svg aria-hidden=\"true\" width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"m15 9-6 6M9 9l6 6\"/></svg>Failed</span>",
      "css": ".ds-status { display: inline-flex; align-items: center; gap: 6px; font: 500 12px/16px 'Geist Variable', system-ui, sans-serif; } .ds-status--failed { color: #a33228; } .ds-status--success { color: #236c4b; } .ds-status--running { color: #2f6788; }"
    },
    {
      "name": "Focus ring",
      "kind": "custom",
      "description": "2px --el-focus outline with 2px offset on :focus-visible; inset variant for rows and tabs.",
      "html": "<button class=\"ds-focus\">Inspect run</button>",
      "css": ".ds-focus { min-height: 36px; padding: 0 12px; border: 1px solid #857f73; border-radius: 4px; background: #f8f5ef; color: #1b1b18; } .ds-focus:focus-visible { outline: 2px solid #9e321c; outline-offset: 2px; }"
    },
    {
      "name": "Scoreline",
      "kind": "custom",
      "description": "Ruled metric band that replaces KPI cards; em dash for no data.",
      "html": "<dl class=\"ds-scoreline\"><div><dt>Total runs</dt><dd>42</dd></div><div><dt>Success rate</dt><dd>—</dd></div></dl>",
      "css": ".ds-scoreline { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); border-top: 1px solid #bdb7aa; border-bottom: 1px solid #bdb7aa; margin: 0; } .ds-scoreline div { padding: 16px 0; } .ds-scoreline div + div { border-left: 1px solid #d3cec4; padding-left: 16px; } .ds-scoreline dt { font: 400 12px/16px system-ui, sans-serif; color: #5a554c; } .ds-scoreline dd { margin: 4px 0 0; font: 500 28px/1 Georgia, serif; font-variant-numeric: tabular-nums; color: #1b1b18; }"
    }
  ],
  "narrative": {
    "rules": [
      { "name": "The Floor Rule", "body": "No essential text below 11px, no text tier below 4.5:1, no control boundary below 3:1, no focus indicator below a solid 2px ring.", "section": "typography" },
      { "name": "The One Signal Rule", "body": "Vermilion marks one thing per view: the selection rail, a key mark, or the primary emphasis. Accent text and state rails use accent-strong.", "section": "colors" },
      { "name": "The Honest State Rule", "body": "One shell banner for an unreachable API; em dashes for absent data; disabled actions say why; CLI equivalents only when real.", "section": "colors" }
    ],
    "dos": ["Do use the Scoreline for metrics.", "Do use StatusBadge for every status.", "Do use focus-ring on custom controls."],
    "donts": ["Don't use KPI card mosaics.", "Don't use eyebrows above headings or decorative section numbers.", "Don't use monospace as a costume.", "Don't animate layout properties or use transition-all."]
  }
}
```

## .gitignore status

- `node_modules/` is ignored, by the root `.gitignore` (`node_modules/`) and by
  `agentic-workflows-v2/.gitignore` (`ui/node_modules/`).
- `.impeccable/` is **not** ignored. If it should stay local, add `.impeccable/`
  under "Tool-installed skill/agent packs" in the root `.gitignore`. Otherwise,
  commit it deliberately together with `DESIGN.md`.
- The detector waiver for the intentional prototype-lab findings is an inline
  `impeccable-disable` directive in `ui/src/styles/prototype-lab.css`, so it
  does not depend on `.impeccable/config.json`.
