# Architecture: package ownership and shared helpers

Status: proposed architecture. The changes below are not yet implemented.
Delivery steps: [G6 and G7](../2026-09-10-tech-debt-workflow.md).

## Problem

Some runtime packages import server code, and the `core` package presents
itself as a foundation while re-exporting engine implementations. These mixed
responsibilities make changes harder to isolate. Several small helpers also
repeat the same behavior in multiple places.

## Decision

Describe `core` as a convenient public import location. Keep workflow graph
and execution-context implementations in the engine package.

Enforce these dependency rules with source-level import tests, including
relative imports:

| Package | Must not import |
| --- | --- |
| Contracts | Server, CLI, engine or integrations |
| Engine | Server or CLI |
| Scoring | Server, CLI or the retired evaluation package |
| Workflows | Server or CLI |

Move existing violations to the package that owns the behavior. Do not add
broad test exceptions to preserve the current dependency problems.

## Interface changes

Add `get_tool_registry()` and `get_adapter_registry()` to the relevant public
modules. Each returns the existing singleton. Keep the old `get_registry()`
names working, and use the clearer names in internal imports.

Place score normalization under scoring. Keep the old import path as a thin
forwarding module so existing callers continue to work. Tests must confirm
both paths produce the same result.

Update tests that import another module's private helper to import its owning
module. Remove a forwarding name only after all internal callers have moved;
retain public compatibility names until a documented removal is appropriate.

## Small changes

These changes can be implemented directly without additional design records.

| Area | Change | Behavior to preserve |
| --- | --- | --- |
| Local model discovery | Share the three repeated classification blocks in a private helper | Provider identity, local/remote URL handling, cost classification and probe time |
| Adapter errors | Reuse the existing unknown-adapter error | Unknown names remain distinct from construction failures |
| Timeouts | Share defaults only where operations have the same purpose and units | Separate health, discovery, tool execution and heartbeat settings |

The shared discovery helper accepts the provider ID, environment variable,
default URL, discovery function and probe timestamp. Tests use fake providers.
Timeout consolidation starts with an inventory of defaults, units and override
rules; equal numeric values alone do not justify combining settings.

The MCP timeout duplication and explicit step-event setter are already fixed.
Leave the expression evaluator unchanged until its supported grammar needs a
real change.

## Migration and verification

Complete scoring-package removal and server decomposition before enforcing the
new package rules. Small changes can run in parallel when they edit different
files.

Reduce coverage exclusions one subsystem at a time. Add tests for its behavior
and failures, then remove its exclusion. Keep the current coverage floor and
report exclusions that remain. Do not weaken checks to make the new structure
pass.

Verify forbidden imports fail the contract tests, old public imports still
work, normalization results match, discovery uses no real network calls, and
configured timeout values and override precedence remain unchanged.
