# ADR-023 Working Notes — Superseded Drafts

These files are **superseded working notes** retained for historical reference only.
They are not Architecture Decision Records; do not cite them as authoritative.

The files here were produced during the ADR-023 (ExecutionKit ↔ Runtime
Execution-Contract Relationship) migration effort and accumulated a naming
collision when all were placed in `docs/adr/` under the `ADR-023-` prefix.
The collision was resolved on 2026-06-17:

- The canonical decision record remains at
  [`../ADR-023-executionkit-runtime-contract-relationship.md`](../ADR-023-executionkit-runtime-contract-relationship.md).
- A second genuine architectural decision that was incorrectly filed under
  `ADR-023` was promoted to its own number:
  [`../ADR-034-path-first-workflow-io-contracts.md`](../ADR-034-path-first-workflow-io-contracts.md).
- The five files below are purely operational / investigative documents. They
  were moved here to keep the ADR directory clean while preserving the
  full migration history.

## Files in this directory

| File | What it is |
|------|-----------|
| `ADR-023-migration-plan.md` | Original P0–P7 phased migration plan for Option A |
| `ADR-023-migration-notes.md` | Operational phase tracker, freeze rules, and decision log |
| `ADR-023-finish-plan.md` | Option A′ finishing plan (F0–F7 phases, risks, test strategy) |
| `ADR-023-lab-canonical-divergence-audit.md` | Adversarial audit comparing the `agentic-systems-lab` fork to canonical |
| `ADR-023-preservation-matrix.md` | Capability preservation matrix tracking every runtime feature |

All ADR-023 implementation decisions are captured in the canonical decision
record and its Amendment section (Option A′). These drafts are not updated
going forward.
