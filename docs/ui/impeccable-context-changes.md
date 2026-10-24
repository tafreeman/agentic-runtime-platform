# Impeccable context changes

Applied. The Impeccable context is now tracked at the repository root:
[`PRODUCT.md`](https://github.com/tafreeman/agentic-runtime-platform/blob/main/PRODUCT.md), [`DESIGN.md`](https://github.com/tafreeman/agentic-runtime-platform/blob/main/DESIGN.md) and
[`.impeccable/design.json`](https://github.com/tafreeman/agentic-runtime-platform/blob/main/.impeccable/design.json).

The sources of truth remain `agentic-workflows-v2/ui/src/styles/tokens.css`
(values and the verified contrast table) and
[the Evidence Ledger design system](evidence-ledger-design-system.md) (rules).
Where a context file and `tokens.css` disagree, `tokens.css` wins.

`.impeccable/hook.cache.json` and `.impeccable/live/` are local tool state and
are not tracked.
