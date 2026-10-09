# Impeccable context changes

Applied. The Impeccable context is now tracked at the repository root:
[`PRODUCT.md`](../../PRODUCT.md), [`DESIGN.md`](../../DESIGN.md) and
[`.impeccable/design.json`](../../.impeccable/design.json).

The sources of truth remain `agentic-workflows-v2/ui/src/styles/tokens.css`
(values and the verified contrast table) and
[the Evidence Ledger design system](evidence-ledger-design-system.md) (rules).
Where a context file and `tokens.css` disagree, `tokens.css` wins.

`.impeccable/hook.cache.json` and `.impeccable/live/` are local tool state and
are not tracked.
