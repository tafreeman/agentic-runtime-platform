# ADR-045: BuildAppTool Requires Human Approval (Gated Shell Execution)

**Status:** Accepted
**Date:** 2026-07-08
**Related:** `agentic_v2/tools/builtin/build_ops.py` (`BuildAppTool`),
`agentic_v2/tools/base.py` (`BaseTool.requires_approval`),
`agentic_v2/governance/approval.py` (`evaluate_tool_approval`),
[ADR-041](ADR-041-approval-gate-timeout.md)

## Context

`BuildAppTool` (tool name `build_app`, tier 0) detects a project's stack and
executes its install / build / test / smoke phases as real shell commands —
including an `asyncio.create_subprocess_shell` path for commands that contain
shell metacharacters. It inherited `requires_approval=False` from `BaseTool`, so
unlike `ShellTool` / `ShellExecTool` (which set `requires_approval=True`) it ran
arbitrary build commands with **no human-approval gate**.

This contradicted the repository's headline claim of "fail-closed HITL for
high-impact shell tools": a caller could drive package installs and test
execution through `build_app` while bypassing the approval boundary that
`shell` / `shell_exec` enforce. Its substring denylist (`_BLOCKED_CMD_PATTERNS`)
blocks a handful of obviously destructive strings but is a bypassable denylist,
not an allowlist, and is not a substitute for the gate.

## Decision

`BuildAppTool` overrides `requires_approval` to return `True`, joining the other
high-impact builtins. Every `build_app` invocation is now routed through
`evaluate_tool_approval` at both dispatch points *before* any phase runs. The
gate's existing posture applies unchanged:

- no registered `ApprovalProvider` → **DENIED** (fail-closed);
- a hung provider → DENIED within the bounded timeout of ADR-041;
- explicit deny → DENIED; only an in-time APPROVED lets the build phases run.

No behavior of the phase pipeline itself changes; only the pre-execution gate is
added. This is a security-boundary move, so it is recorded here per the repo's
ADR policy.

## Consequences

- `build_app` no longer executes install/build/test/smoke commands without an
  approval decision. Non-interactive or trusted environments that legitimately
  need it must register an `AutoApproveProvider` (or a policy provider), or set
  the documented global / per-tool approval overrides — the same escape hatch
  the other gated builtins already use.
- The README HITL claim and the AI evidence scorecard are updated to reflect
  that `build_app` is now gated (companion truth-sync change).
- The substring denylist is retained as defense-in-depth but is no longer the
  only control on `build_app` execution.

## Alternatives considered

- **Route build commands through the `AGENTIC_SHELL_ALLOWED_COMMANDS` allowlist
  instead of gating** — rejected as insufficient on its own: an allowlist
  constrains *which programs* may run but does not add the human-in-the-loop
  decision the fail-closed-governance claim promises. Gating is the boundary the
  audit flagged as missing; an allowlist can be layered on later but does not
  replace it.
- **Fence or remove only the `create_subprocess_shell` path** — rejected: it
  narrows one execution path but still leaves `build_app` running installs and
  tests ungated. The gate is the correct, uniform control.
- **Leave ungated and rely on the denylist** — rejected: the denylist is a
  bypassable substring match, not an approval boundary, and its presence is
  exactly what made the ungated tool look safe.
