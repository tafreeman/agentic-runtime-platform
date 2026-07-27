# Evidence Ledger Design System

**Product:** Agentic Runtime Platform (ARP)  
**Status:** Canonical UI direction for the full rewrite  
**Component foundation:** React, TypeScript, Vite, shadcn/ui  
**Reference prototype:** `/prototypes`, concept `02 Evidence ledger`

## 1. Purpose

Evidence Ledger is ARP's production design system. It translates the prototype's airy editorial character into a complete operational interface for workflows, runs, live execution, datasets, evaluations, providers, models, and routing configuration.

This document is the visual and interaction authority for the rewrite. Page specifications may determine what information appears, but they must not override this system's composition, density, color, typography, accessibility, or component rules.

The system must feel:

- light, calm, and spacious;
- rigorous without feeling institutional;
- editorial without becoming a marketing site;
- technical without turning every label into monospace console text;
- information-rich without exposing every control simultaneously;
- precise without surrounding every region with a box.

It must never feel:

- dark by default;
- cramped or dashboard-like;
- like unmodified shadcn/ui;
- like a terminal emulator;
- like a mosaic of interchangeable statistic cards;
- decorative at the expense of operating clarity.

## 2. Design principles

### 2.1 Evidence before decoration

Every visible element must help the user orient, inspect, compare, decide, configure, or act. Remove decorative panels, redundant labels, and charts without a decision-making purpose.

### 2.2 Air is structural

Whitespace separates levels of meaning. Use it before background fills, borders, shadows, or extra containers. Empty space is not unfinished space.

### 2.3 One dominant surface

Each viewport should have one visually dominant working surface: a ledger, graph, trace, editor, or configuration workspace. Secondary context belongs in a narrow inspector, drawer, or progressively disclosed section.

### 2.4 Quiet chrome, decisive action

Navigation and controls should recede until needed. Each page has one obvious primary action. Destructive, secondary, and overflow actions must not compete with it.

### 2.5 Progressive disclosure

Show common fields and current state first. Put expert settings, raw contracts, YAML, logs, provider options, and provenance detail behind labeled tabs, inspectors, accordions, or advanced sections.

### 2.6 Provenance is part of the interface

Scores, model choices, routing results, dataset samples, and configuration must show their source, version, freshness, or resolution path when those facts affect trust.

### 2.7 Accessibility is composition

Keyboard order, focus, semantic structure, contrast, motion reduction, screen-reader announcements, and spatial alternatives are part of the base design—not a cleanup phase.

## 3. Visual thesis

ARP is an engineering evidence desk made from warm paper, crisp ink, hairline rules, restrained safety orange, editorial headings, calm quantitative typography, and generous negative space.

The prototype's defining visual rhythm must survive production:

- broad breathing room around page headings and major evidence bands;
- warm off-white canvas instead of white or charcoal application chrome;
- long horizontal rules and aligned columns instead of nested cards;
- comfortable table rows with strong typographic hierarchy;
- one small orange signal rather than several competing accent colors;
- sparse shadows and low radii;
- large score numerals used only when the score is the page's main evidence;
- short utility copy and meaningful labels;
- visible controls limited to those needed for the current task.

## 4. Color system

### 4.1 Canonical light palette

| Token | Value | Use |
|---|---:|---|
| `--el-canvas` | `#F2EFE8` | Application background; warm paper |
| `--el-surface` | `#F8F5EF` | Primary work surfaces and inspectors |
| `--el-surface-raised` | `#FFFDFA` | Menus, dialogs, sheets, popovers |
| `--el-surface-subtle` | `#EDE9E0` | Selected rows, quiet grouped regions |
| `--el-surface-hover` | `#E8E3D9` | Row/control hover |
| `--el-ink` | `#1B1B18` | Primary text and high-emphasis icons |
| `--el-ink-secondary` | `#514D46` | Secondary labels and values |
| `--el-ink-muted` | `#736E64` | Helper text and inactive navigation |
| `--el-ink-faint` | `#918B80` | Decorative metadata only; not body copy |
| `--el-divider` | `#BDB7AA` | Strong section rules and table boundaries |
| `--el-divider-soft` | `#D3CEC4` | Row rules and subtle separation |
| `--el-divider-faint` | `#E2DDD4` | Internal separators |
| `--el-action` | `#1C1D19` | Primary button background |
| `--el-action-ink` | `#F8F5EF` | Text/icon on primary action |
| `--el-accent` | `#EF5A36` | Selected tab rail, key chart mark, emphasis |
| `--el-accent-strong` | `#B83A20` | Accessible accent text and focus details |
| `--el-accent-soft` | `#F6DDD4` | Selected/attention tint |
| `--el-focus` | `#9E321C` | Keyboard focus ring |
| `--el-success` | `#236C4B` | Passing/healthy text and icons |
| `--el-success-soft` | `#DCE8DF` | Passing/healthy background |
| `--el-warning` | `#7A5317` | Warning/review text and icons |
| `--el-warning-soft` | `#F0DFBD` | Warning/review background |
| `--el-danger` | `#A33228` | Failure/destructive text and icons |
| `--el-danger-soft` | `#F1D9D5` | Failure/destructive background |
| `--el-info` | `#2F6788` | Informational and running states |
| `--el-info-soft` | `#D9E5ED` | Informational background |

### 4.2 Color rules

- The canvas is warm paper, not pure white.
- Pure black is reserved for rare high-contrast needs; primary ink uses `--el-ink`.
- Orange is never a page background or large decorative wash.
- Use `--el-accent` for non-text emphasis, large text, or marks. Use `--el-accent-strong` for normal-size accent text.
- Status colors supplement a text label or icon; color never carries status alone.
- Charts begin with ink, soft neutral, and orange. Add semantic colors only when the series encodes a semantic status.
- Avoid gradients in routine product UI.
- Avoid translucent glass effects, neon glow, and dark panels.

### 4.3 Dark mode

Dark mode is optional and secondary. The rewrite is complete when the light system is complete and accessible. If dark mode is retained:

- it must use a warm charcoal, not blue-black;
- it must preserve the same low-chrome hierarchy;
- it must not become the default theme;
- it must have independently verified contrast;
- it must not delay required light-mode work.

## 5. shadcn/ui token mapping

Map shadcn semantic variables to Evidence Ledger tokens. Exact syntax may change with the installed shadcn version, but the semantic result is required.

```css
:root {
  --background: 43 28% 93%;
  --foreground: 60 5% 10%;
  --card: 40 33% 98%;
  --card-foreground: 60 5% 10%;
  --popover: 40 100% 99%;
  --popover-foreground: 60 5% 10%;
  --primary: 75 7% 11%;
  --primary-foreground: 40 33% 95%;
  --secondary: 41 25% 90%;
  --secondary-foreground: 38 7% 30%;
  --muted: 40 18% 89%;
  --muted-foreground: 38 6% 42%;
  --accent: 12 85% 57%;
  --accent-foreground: 60 5% 10%;
  --destructive: 5 61% 40%;
  --destructive-foreground: 40 33% 98%;
  --border: 39 12% 76%;
  --input: 39 12% 76%;
  --ring: 11 70% 36%;
  --radius: 0.25rem;
}
```

Do not rely on this sample as the contrast test. Validate the compiled values in the browser.

shadcn components are owned source. Restyle their anatomy and spacing. Do not ship default examples, default oversized radii, pill-heavy variants, or nested `Card` compositions.

## 6. Typography

### 6.1 Families

Use at most two primary families:

| Role | Preferred | Fallback |
|---|---|---|
| UI/body | `Inter`, `Source Sans 3`, or a comparable legible sans | `system-ui`, `sans-serif` |
| Editorial display | `Source Serif 4`, `Literata`, or a comparable restrained serif | `Georgia`, `serif` |

Monospace is a utility face, not a third brand face. Use `ui-monospace` only for IDs, code, YAML, JSON, CLI commands, event logs, timestamps when alignment matters, and technical provenance.

### 6.2 Type scale

| Token | Size / line | Weight | Use |
|---|---|---:|---|
| `display-score` | `56 / 56` | 500 | One dominant score only |
| `page-title` | `40 / 44` | 500 | Main page title on spacious pages |
| `page-title-compact` | `30 / 34` | 550 | Canvas/editor/live pages |
| `section-title` | `20 / 26` | 600 | Major working sections |
| `subsection-title` | `15 / 21` | 600 | Inspectors and grouped content |
| `body` | `14 / 22` | 400 | Default copy and values |
| `body-small` | `12 / 18` | 400 | Secondary utility copy |
| `label` | `11 / 15` | 600 | Form/table labels |
| `metadata` | `10 / 15` | 500 | IDs, timestamps, provenance |

### 6.3 Typography rules

- Page titles may use the editorial serif. Working section titles usually use the sans.
- Do not use the serif for buttons, tabs, filters, forms, navigation, or dense tables.
- Do not set all labels in uppercase. Reserve uppercase with tracking for small overlines and table headers.
- Use sentence case for controls and navigation.
- Keep explanatory lines below roughly 70 characters where practical.
- Use tabular numerals for scores, duration, latency, tokens, cost, percentages, and counts.
- Never reduce essential interface text below 11 px.

## 7. Spacing and geometry

### 7.1 Base scale

Use a 4 px base:

`4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80`

### 7.2 Composition spacing

| Context | Default |
|---|---:|
| Desktop page gutter | `40 px` |
| Laptop page gutter | `24–32 px` |
| Mobile page gutter | `16–20 px` |
| Major section gap | `32–48 px` |
| Related group gap | `16–24 px` |
| Field group gap | `16 px` |
| Label-to-control gap | `8 px` |
| Interactive row vertical padding | `14–18 px` |
| Inspector padding | `24 px` |
| Dialog/sheet padding | `24–32 px` |

Whitespace is allowed to grow with viewport width, but content width must remain usable. Standard content pages use a maximum readable width of approximately `1180–1280 px`. Canvas pages may use the full viewport.

### 7.3 Radius

| Token | Value | Use |
|---|---:|---|
| `radius-none` | `0` | Tables and full-width ledger bands |
| `radius-sm` | `2 px` | Small controls and tags |
| `radius-md` | `4 px` | Inputs, buttons, menus |
| `radius-lg` | `8 px` | Dialogs, sheets, discrete interactive objects |

Avoid fully rounded pills except compact status indicators where shape improves recognition.

### 7.4 Borders and shadows

- Default dividers are 1 px hairlines.
- Prefer one divider between regions over borders around both regions.
- Raised menus/dialogs may use `0 16px 40px rgba(27, 27, 24, 0.12)`.
- Cards and table rows should not use drop shadows.
- Selected rows use a subtle surface tint and 2 px orange left rail or bottom tab rail.
- Focus uses a visible 2 px ring with 2 px offset.

## 8. Application shell

### 8.1 Global navigation

Organize the product into:

- **Observe:** Overview, Runs, Live execution;
- **Build:** Workflows, Datasets;
- **Evaluate:** Evaluations;
- **Configure:** Model Router.

The shell should be quiet, light, and persistent without framing the application in dark chrome.

Desktop shell targets:

- header height: `56–64 px`;
- expanded navigation width: no more than `220 px` when a side rail is used;
- icon-only navigation width: `52–64 px`;
- active state: ink or orange rule, not a large colored capsule.

Mobile uses a compact header and a Sheet/Drawer navigation. Do not compress the full desktop navigation into unreadable icons.

### 8.2 Page header

A page header contains:

1. optional overline or breadcrumb;
2. page title;
3. one short scope/freshness sentence where needed;
4. one primary action;
5. secondary actions in a menu or quiet button group.

Standard pages use `72–112 px` depending on whether the editorial title treatment is appropriate. Live execution and editor pages use a compact header no taller than `64 px`.

### 8.3 Workspace model

Use:

```text
global navigation
└── page header
    └── contextual tabs/filters
        └── primary workspace
            ├── dominant surface
            └── optional inspector
```

Avoid placing a card around every level of this hierarchy.

## 9. Core interaction patterns

### 9.1 Master-detail

- Selection occurs in a table, ledger, graph, or list.
- The selected item remains visible.
- Desktop detail opens in a `320–420 px` inspector where practical.
- The inspector may be resizable on data-heavy pages.
- Tablet/mobile detail opens in a Sheet or Drawer.
- Escape closes the inspector and returns focus to the selected trigger.
- URLs should encode selection when shareability or browser history matters.

### 9.2 Progressive disclosure

- Common settings remain visible.
- Advanced settings use Collapsible, Accordion, tabs, or a dedicated editor route.
- Do not place more than one nested disclosure inside another.
- Preserve user-entered state when opening or closing advanced sections.
- Labels such as “Advanced” must summarize what is inside.

### 9.3 Filters

- Filters live immediately above or beside the affected data.
- The highest-use two or three filters remain visible.
- Remaining filters open in a Popover/Sheet.
- Active filters are summarized textually and can be cleared individually.
- Shareable filters belong in the URL.
- Do not create a row of colored pills for every possible filter.

### 9.4 Destructive actions

- Use Alert Dialog for destructive or provenance-affecting changes.
- State the object, consequence, and recovery path.
- Never place destructive action beside the primary action without separation.
- Require stronger confirmation only when recovery is impossible.

### 9.5 Feedback

- Inline validation appears near the affected control.
- Toasts confirm completed background mutations or recoverable failures.
- Persistent errors stay in the relevant surface.
- Loading states preserve layout.
- Stale data remains visible with a freshness/error notice when safe.
- Never replace an entire populated page with a spinner during background refresh.

## 10. shadcn component standards

### 10.1 Button

Variants:

- `primary`: near-black fill, warm-paper text;
- `secondary`: transparent or surface fill with divider border;
- `ghost`: no border until hover/focus;
- `destructive`: danger text or danger fill only after confirmation context;
- `link`: textual navigation, underline on hover/focus.

Default height is `40 px`; compact canvas controls may use `32–36 px`. Icon-only buttons require accessible labels and at least a `36×36 px` target.

One filled primary button per local action group.

### 10.2 Input, Select, Textarea

- Minimum control height: `40 px`.
- Background: surface or raised surface, never dark.
- Border: divider; focus ring: `--el-focus`.
- Labels sit above controls with 8 px gap.
- Helper and error text reserve enough space to avoid layout jumps where validation is expected.
- Placeholder text is not a label.
- Dense technical editors may use monospace but retain 14 px minimum text.

### 10.3 Tabs

- Tabs use a quiet text label with a 2 px bottom rule.
- Active state uses ink plus orange rule.
- Avoid filled rounded tab pills.
- Counts are muted text, not badges unless the count is a status.
- Tabs must remain URL-addressable when they represent distinct product subviews.

### 10.4 Table and ledger rows

- Tables are the default for repeated operational records.
- Headers use small tracked labels and remain sticky when the body scrolls.
- Standard rows are `56–68 px` high.
- Use hairline row dividers and no outer card when the page boundary is clear.
- Primary identity is stronger than secondary metadata.
- Numeric columns align right with tabular numerals.
- Status uses text plus icon/marker.
- Row hover is a subtle warm neutral.
- Row selection adds a tint and orange rail.
- Row actions remain quiet and may appear on hover/focus, but must be keyboard reachable.
- Responsive tables preserve identity, state, and the primary metric first.

### 10.5 Badge

- Use Badge only for compact categorical state: passed, failed, running, disabled, draft, overridden.
- Use sentence case or short lowercase labels, consistently.
- Avoid more than two badges in a single row's default view.
- Capabilities and tags should move to the inspector when they would create a badge cloud.

### 10.6 Card

Card is not the default page primitive.

Use it only for:

- a discrete selectable object;
- an object that can be moved, opened, or acted upon independently;
- a compact empty/getting-started state;
- a dialog-like raised object.

Do not use Card for ordinary sections, KPI mosaics, tables, filter bars, or page headers.

### 10.7 Sheet, Drawer, Dialog

- Sheet is the desktop/narrow-screen inspector and secondary configuration surface.
- Drawer is preferred for mobile actions that are easier to reach with a thumb.
- Dialog is reserved for short focused tasks.
- Long forms and model-pack editing use a route or full workspace, not a modal.
- Dialogs must restore focus and support Escape unless an irreversible operation is actively executing.

### 10.8 Command

- Use the shadcn Command foundation for the global command palette.
- Group results by product area.
- Show shortcut hints and CLI twins where real.
- Do not expose actions the current user cannot perform.
- Search labels, IDs, and common aliases without sending secrets or full datasets to external services.

### 10.9 Toast

- Use short outcome-oriented copy.
- Success toasts disappear automatically.
- Failure toasts remain long enough to read and link to details when needed.
- Do not use toasts for validation the user must fix in a form.
- Do not stack repeated stream/polling errors.

## 11. ARP-specific components

### 11.1 Evidence scoreline

A scoreline replaces KPI card grids. It may combine:

- one dominant metric;
- a compact time series or distribution;
- one evidence-backed change note;
- provenance/freshness metadata.

Use top and bottom rules, aligned columns, and whitespace rather than a boxed card. Limit to three conceptual regions and five primary metrics.

### 11.2 Provenance strip

Display the values that determine trust:

- source/revision;
- timestamp/freshness;
- workflow and run identity;
- dataset/sample;
- model/provider resolution;
- routing pack/version;
- rubric/judge/calibration version.

The default strip shows only the most material three to five values. Full provenance opens in the inspector.

### 11.3 Status marker

Status anatomy:

```text
[shape/icon] label [optional short qualifier]
```

Use stable mappings:

- success/passed: check or filled circle + success color;
- running: pulse only when motion is allowed + info color;
- warning/review: triangle or half-filled marker + warning color;
- failed/error: x or diamond + danger color;
- neutral/pending: outline circle + muted ink.

### 11.4 Inspector

Inspector order:

1. object type/overline;
2. object identity and state;
3. primary action if appropriate;
4. contextual tabs;
5. common details/configuration;
6. advanced/provenance/raw data.

Use 24 px padding and 24–32 px between major inspector groups. Do not turn the inspector into a stack of cards.

### 11.5 DAG canvas

The graph canvas is a specialized full workspace but still uses Evidence Ledger:

- warm neutral canvas with a very subtle dot grid;
- light nodes with hairline borders;
- ink labels and muted metadata;
- orange selection outline;
- semantic status edge/node marks;
- quiet icon tool rail;
- right inspector for configuration/detail;
- list/table equivalent for accessibility;
- minimap only when the graph exceeds the viewport.

Do not import the prototype Flow Canvas's dark/violet visual language.

### 11.6 Event trace

- Use a vertical timeline or ledger list.
- Timestamp and event type align consistently.
- Routine events are quiet; failures and approvals receive semantic emphasis.
- Long payloads collapse with explicit Show details.
- Event history must be bounded or virtualized.
- Auto-follow is an explicit state and pauses when the user scrolls away.

### 11.7 Code, YAML, and JSON viewer

- Use a pale neutral code surface, not a dark editor by default.
- Provide copy, wrap, expand, and search where useful.
- Preserve whitespace and accessible text selection.
- Collapse deeply nested data.
- Never render untrusted HTML.
- Large values must be bounded or virtualized.

### 11.8 Model routing chain

Represent a tier as an ordered ledger, not a badge pile:

```text
01  provider:model        available    tools, vision       routes here
02  provider:model        degraded     tools               fallback
03  provider:model        disabled     —                   unavailable
```

Show default, override, environment pin, effective route, and actual run resolution as distinct concepts. Reordering must work with keyboard and pointer.

## 12. Data visualization

- Every chart needs a question it answers.
- Use direct labels when space allows.
- Start axes at zero when magnitude comparison requires it.
- Show sample size and time range.
- Do not imply continuity for sparse data.
- Show uncertainty when making comparison or trend claims.
- Use orange for the selected/current series, ink for the baseline, and neutral tones for context.
- Avoid rainbow palettes, 3D effects, radial gauges, and decorative area gradients.
- Provide a table or textual summary for essential chart information.

## 13. Motion

Motion is restrained and functional.

| Token | Duration | Use |
|---|---:|---|
| `motion-fast` | `120 ms` | hover, focus, button feedback |
| `motion-standard` | `180 ms` | inspector/tab/content transition |
| `motion-slow` | `240 ms` | drawer/sheet entry, graph layout settle |

Use ease-out for entry and ease-in for exit. Avoid spring/bounce motion in operational flows.

Permitted motion:

- inspector/sheet entrance;
- active tab/selection rail movement;
- row hover/focus;
- graph edge activity for a running step;
- chart entry when it clarifies a newly loaded result;
- skeleton shimmer or pulse at low intensity.

Prohibited motion:

- infinite decorative animation;
- whole-page stagger on every navigation;
- looping gradients;
- animated metrics that delay reading;
- selection motion that moves surrounding content;
- pulsing more than one or two active indicators in a viewport.

Under `prefers-reduced-motion: reduce`, remove transforms, animated graph edges, and loops; preserve immediate state changes.

## 14. Responsive system

### Desktop — `≥1280 px`

- full navigation and optional inspector;
- wide ledger tables;
- graph plus inspector;
- page gutter 32–40 px.

### Laptop/tablet — `768–1279 px`

- collapsed or compact navigation;
- inspector may overlay as Sheet;
- remove secondary table columns before reducing typography;
- page gutter 24 px.

### Mobile — `<768 px`

- compact header plus Drawer/Sheet navigation;
- page gutter 16–20 px;
- one primary column;
- inspector/detail becomes full-height Sheet or route;
- tables become prioritized rows with a detail disclosure;
- primary action remains reachable without permanent bottom-bar clutter;
- graph gets a list alternative and may open as a dedicated landscape/full-screen surface;
- forms use full-width controls and touch targets of at least 44 px where practical.

Validate at `1440×900`, `1280×720`, `1024×768`, and `390×844`.

## 15. Content and naming

Use product language, not design commentary.

Good:

- Recent runs
- Provider health
- Routing order
- Selected rubric
- Last evaluation
- Resolved model
- Source revision
- Judge skipped

Avoid:

- Supercharge your agents
- Intelligent insights
- Next-generation orchestration
- Seamless AI workflows
- Mission control
- Command center

Rules:

- Buttons use verb + object where space allows: `Start run`, `Save provider`, `Compare runs`.
- Empty states say what is absent and the safest next action.
- Errors state what failed, whether existing data is still valid, and how to retry.
- Do not expose raw endpoint names in visible headings unless the page is specifically API documentation.
- Do not repeat the page title in every section.

## 16. Accessibility requirements

- WCAG 2.2 AA contrast for essential text, controls, focus, and status.
- Logical landmark and heading hierarchy.
- Skip-to-content and route-change focus management.
- Visible 2 px focus indicator.
- Full keyboard operation for navigation, tables, inspectors, menus, dialogs, model chains, and graph alternatives.
- Focus restoration after Sheet/Dialog/Popover closes.
- Status is never color-only.
- Form errors connect with `aria-describedby` and invalid state.
- Streaming updates use restrained live regions; do not announce every token/event.
- Essential charts have textual/table equivalents.
- DAGs have an accessible node/edge list and configuration path.
- Hit areas are at least 36 px desktop and preferably 44 px touch.
- Reduced motion is honored.
- Zoom to 200% must not hide essential actions or require two-dimensional scrolling outside specialized canvases/tables.

## 17. Page composition templates

### Ledger page

Used by Runs, Workflows, Datasets, Evaluations, Models, Providers, and Packs.

```text
page heading                                      primary action
short scope/freshness line

optional scoreline or summary band

tabs / primary filters                            search / more filters
──────────────────────────────────────────────────────────────────────
ledger table or list
ledger table or list                              optional inspector
```

### Canvas page

Used by Workflow Builder, Live Execution, and graph-forward detail.

```text
compact breadcrumb/title        status                  actions
──────────────────────────────────────────────────────────────────────
tools  canvas / trace / graph                       inspector
```

### Configuration page

Used by Workflow Run Configuration, Provider editing, Tier editing, and Model Packs.

```text
identity / context                                  save or run
──────────────────────────────────────────────────────────────────────
primary configuration or preview                   inspector/form
secondary evidence/history                         advanced disclosure
```

## 18. Anti-patterns

Reject a design when it includes:

- dark application chrome as the default;
- four or more KPI cards across the first viewport;
- a card wrapped around a table wrapped around another card;
- more than one filled primary button in one action group;
- a toolbar containing every possible filter and action;
- rows below 48 px in the default density;
- badge clouds for models, tools, providers, or capabilities;
- rounded pill tabs;
- gradients behind normal product UI;
- shadows on every container;
- tiny gray text as the primary way to create hierarchy;
- monospace body copy;
- placeholder-only form labels;
- raw JSON as the default user experience;
- controls without real backend behavior;
- fake scores, costs, latency, health, or progress;
- animation that competes with reading;
- the dark Control Room or dark Flow Canvas prototype aesthetics applied to production.

## 19. Implementation governance

- No page-local hard-coded colors when a semantic token exists.
- No one-off spacing outside the scale without a documented canvas/data reason.
- No new component variant without at least two legitimate consumers or a specialized product requirement.
- Build shadcn components into a shared UI layer and ARP-specific patterns into a feature-aware design-system layer.
- Specialized components may bypass shadcn when shadcn is not the right abstraction; document why.
- Add Storybook or a development-only design-system route only if it is maintained and excluded from the production navigation.
- Keep real application pages backed by typed fixtures in component/visual tests, never embedded mock production data.
- Update this file when a token or canonical pattern changes.

## 20. Visual acceptance checklist

Every migrated route must pass all applicable checks:

- [ ] Light warm-paper canvas is the default.
- [ ] The page is recognizably Evidence Ledger without relying on the orange accent.
- [ ] The first viewport has one dominant working surface.
- [ ] Whitespace, typography, and alignment create hierarchy before boxes or shadows.
- [ ] No area feels like a generic shadcn demo.
- [ ] No unnecessary card grid is present.
- [ ] Only task-relevant controls are visible; advanced controls are disclosed intentionally.
- [ ] Page gutters, section spacing, and row heights meet the comfortable baseline.
- [ ] Orange is restrained and meaningful.
- [ ] All states work without color alone.
- [ ] Keyboard focus is visible and ordered.
- [ ] Loading, empty, stale, partial, offline, and error states preserve composition.
- [ ] The page works at 1440×900, 1280×720, 1024×768, and 390×844.
- [ ] Reduced-motion mode remains understandable.
- [ ] Essential actions and evidence remain visible at 200% zoom.
- [ ] Browser screenshots were inspected, not merely generated.

The system fails review if it is functional but cluttered, airy but information-poor, visually polished but dark, or consistent only on the Evaluations page.
