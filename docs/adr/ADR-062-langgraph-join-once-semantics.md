# ADR-062: The LangGraph Adapter Runs Each Step Once, After All Its Dependencies

**Status:** Accepted
**Date:** 2026-10-12
**Related:** `agentic_v2/langchain/graph_wiring.py` (`wire_graph_edges`,
`wire_dependency_edges`, `build_loop_exit_map`, `add_loop_edge`),
`agentic_v2/langchain/graph.py`, `agentic_v2/langchain/runner.py`,
`agentic_v2/engine/dag_executor.py`,
[ADR-001](ADR-001-002-003-architecture-decisions.md),
[ADR-060](ADR-060-scheduler-guarantees-lean.md)

## Context

The native executor counts in-degrees. A step runs once, after every one of its
dependencies has finished. A `loop_until` step loops inside that one
execution.

The LangGraph adapter wired one single-source edge per `depends_on` entry. That
was a plain edge, or, when any dependent of a source had a `when`, a conditional
"fan-out" edge that routed to every dependent anyway. LangGraph runs a node once
for each superstep in which any of its incoming edges fires. So a step whose
dependencies finished in different supersteps ran once per such superstep, and
each early run saw the slower dependencies' outputs as `None`.

- `fullstack_generation`: `review_code` waits on three generators at depth 2
  and on `generate_integration_tests` at depth 3. It ran in the same superstep
  as `generate_integration_tests`, with `tests` still `None`, and then ran
  again. Every step after it also ran twice. The recorded run logs show a step
  start overlapping `review_code` in every fullstack run.
- `conditional_branching` ran `assemble_report` twice.
- `bug_resolution` ran `generate_verification` before `regression_check`, with
  `regression_risks` still `None`, and then ran it again.
- A loop step fired its outgoing edges on every iteration, so its dependents
  ran once per iteration. `iterative_review` with `max_review_rounds: 2` ran
  `escalation_notice` twice and `package` three times.

## Decision

1. **One edge per step, not one per dependency.** A step with one dependency
   gets a plain edge. A step with several gets a single waiting edge,
   `graph.add_edge([dep, ...], step)`. This is LangGraph's named barrier: the
   step triggers once, after every source has written to it.
2. **Conditional steps keep self-skipping** (`wrap_with_skip_check`). A skipped
   step still completes, so it still writes to its dependents' barriers. The
   fan-out router `add_fan_out_edges` is removed, together with
   `build_outgoing_map`. It routed to every target unconditionally, so plain
   edges do the same job.
3. **Loop steps keep their self-edge.** A loop step that has dependents gets a
   synthetic pass-through node, `__loop_exit__<step>`. The loop router goes to
   that node instead of `END` when the loop exits: the condition is met,
   `loop_max` is reached, or the step skipped itself. Dependents wait on the
   exit node instead of on the loop step. A loop step with no dependents still
   exits to `END`. The exit node is needed because every run of a source node
   writes to the barriers it feeds, and a loop step cannot be made to write
   only on its last iteration.
4. **The exit node is wiring, not a step.** It writes no state, so it never
   appears in `steps` or in a `WorkflowResult`. `WorkflowRunner` drops its
   updates from `stream()`/`astream()` and its task events from
   `run(on_update=...)`. `__loop_exit__` is a reserved step-name prefix.
5. **`compile_workflow` and `build_graph` share one edge-wiring function**,
   `wire_graph_edges`, so the two compile paths cannot diverge.

## Consequences

- On the LangGraph adapter, every shipped workflow runs each step once, and
  each loop step once per iteration. That matches the native executor. Every
  join sees all of its dependencies' outputs. The fullstack rework path makes
  five fewer step runs.
- A loop step's dependents see the outputs of its final iteration and never an
  intermediate one.
- Run logs recorded before this change contain duplicate step runs. Do not
  compare their call counts or step timings with later runs.
- Callers that compile with `compile_workflow` and stream the graph directly,
  bypassing `WorkflowRunner`, see `__loop_exit__*` updates. A checkpoint's
  `next` list can name an exit node.
- A user step whose name starts with `__loop_exit__` would be hidden from
  runner events. If it matches a real exit node, compilation fails, because
  LangGraph rejects duplicate node names.
- `add_fan_out_edges` and `build_outgoing_map` are removed from
  `agentic_v2.langchain.graph`. `wire_dependency_edges` now takes
  `(graph, config, loop_exits)`. Nothing in the repo used the old forms.

**Not changed:** failure propagation. When a step fails, the native executor
skips all of its transitive dependents (ADR-060). The adapter records the
failure and still runs the dependents. That divergence predates this ADR and
is left for a separate change.

## Alternatives considered

- **Trigger on any dependency, run only when all have finished.** A guard
  inside the node would turn each early trigger into an empty task. Those
  tasks still emit events and fire outgoing edges, so the no-op runs cascade
  downstream. Rejected.
- **Run the loop inside one node**, calling the step function until
  `loop_until` holds, as the native executor does. Rejected: all iterations
  would become one LangGraph task. That loses per-iteration checkpoints, and
  an interrupt in a later iteration would replay the earlier ones on resume.
  It would also re-implement the state reducers between iterations.
- **Route the loop exit straight to the dependents.** A branch triggers its
  target immediately, not through a barrier. That is correct only for a
  dependent whose sole dependency is the loop step. `iterative_review`'s
  `package` waits on the loop step and on `escalation_notice`, so it would
  still need a barrier. Rejected as the general mechanism.
- **`defer=True` join nodes.** A deferred node runs only once the graph has
  nothing else left to run. That would hold every join until the whole graph
  drained and change the execution order. Rejected.

## Verification

`tests/test_langchain_join_wiring.py` covers an uneven-depth join, a join on a
skipped conditional step, loop dependents (including a skipped loop step), a
terminal loop, and the runner hiding exit nodes.
`tests/test_fullstack_rework_handoff.py::test_every_step_runs_once_after_all_its_dependencies`
runs `fullstack_generation` on both engines and asserts that each step makes
exactly one call. These tests fail on the previous wiring.
