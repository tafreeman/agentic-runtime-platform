# ADR-024: Expression Evaluation via AST Interpreter (Eliminate eval())

**Status:** Accepted
**Date:** 2026-06-13
**Related:** [ADR-001](ADR-001-002-003-architecture-decisions.md) (native DAG engine), [ADR-018](ADR-018-api-rate-limiting-and-auth-throttle.md) / [ADR-021](ADR-021-jwt-oidc-authentication.md) / [ADR-022](ADR-022-tenant-isolation.md) (security & reliability domain)

---

## Context

Workflow conditional edges and `${...}` substitutions are resolved by expression evaluators. There were **two** of them, with divergent security postures:

1. The **engine** evaluator (`agentic_v2/engine/expressions.py`), used by the native DAG engine. It previously compiled each expression to a Python code object and executed it with `eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, env)` — an AST-validated, empty-builtins sandbox.
2. The **LangChain-adapter** evaluator (`agentic_v2/langchain/expressions.py`), used by the *default* server workflow-execution path (`graph_wiring.py` condition wiring → `runner.py` → `server/execution.py`). This one substituted each `${...}` reference with `repr(resolved_value)` against the run state and then called `eval(compile(tree, "<expr>", "eval"))` with **no restricted globals** — inheriting the full `__builtins__` — wrapped in a bare `except Exception: return False` that failed *open* (a malformed or adversarial condition silently became `False`, silently skipping a step or looping forever).

Even with an empty `__builtins__` map and a node allowlist, `eval()`-based sandboxes carry residual risk:

- **Dunder-traversal escape:** expressions such as `().__class__.__mro__[-1].__subclasses__()` can reach arbitrary types unless dunder access is blocked at every layer.
- **`str.format` / `format_map` bypass:** the format-string machinery can be coerced into attribute traversal.
- **Engine-trust dependency:** the sandbox's safety depends on the CPython `eval`/`compile` machinery remaining escape-free across interpreter versions.

Workflow condition strings originate from authored YAML and, in multi-tenant deployments (ADR-022), potentially from less-trusted sources. An `eval()` call on that path — especially the LangChain one with full builtins and a fail-open `except` — is the kind of construct a security reviewer flags on sight.

---

## Decision

Replace `eval()`/`compile()` in **both** expression evaluators with a **single, shared pure-Python AST interpreter**. There is now exactly one expression security boundary in the codebase.

The engine evaluator now:

1. Parses the expression to an AST (`ast.parse(..., mode="eval")`).
2. Validates the tree against a node allowlist via `_validate_ast`, rejecting dunder attribute and name access at validation time.
3. Walks the validated tree node-by-node in `_eval_node`, dispatching binary, unary, and comparison operators through the `operator` module. **No `eval()` or `compile()` is invoked.**

Two abuse bounds are enforced in the interpreter:

- **Call allowlist by identity:** only the built-in `coalesce` helper is callable (checked by object identity, not name), so no arbitrary method invocation is reachable.
- **Sequence-multiply DoS cap:** `_MAX_SEQUENCE_MULTIPLY` bounds `seq * n` expansions to prevent memory exhaustion via large multiplications.

The public `ExpressionEvaluator` API (`evaluate`, `resolve_variable`) is unchanged; this is an internal, behavior-compatible substitution.

### LangChain condition path (default server path)

The LangChain-adapter evaluator keeps its `${...}` → `repr(resolved_value)` substitution layer (it resolves references against the LangGraph run-state dict, not an `ExecutionContext`), but the final evaluation is now routed through the engine's interpreter via the shared helper `engine.expressions.evaluate_safe_expression(...)`. After substitution the expression is literal-only, so it runs through the *same* `_validate_ast` + `_eval_node` machinery — the dunder block, the `coalesce`-only callable allowlist, and the sequence-multiply DoS cap all apply. **No `eval()` / `compile()` of expressions remains on this path.** (`re.compile` for the `${...}` token regex is unrelated to code execution.)

The fail-**open** `except Exception: return False` is replaced with **fail-closed** behavior: only the expected error classes (`ExpressionError` — the engine helper's own `ValueError` subclass — plus `ValueError` / `NameError` / `TypeError`) are caught; the failure is logged with the raw expression **redacted** and re-raised as `ConditionEvaluationError`. A malformed or adversarial condition therefore surfaces to the run instead of silently skipping a step or looping forever. Legitimate "missing reference → benign comparison" cases (e.g. `None == 'value'`) still evaluate cleanly to a bool and do **not** raise.

---

## Consequences

### Positive

- Eliminates the `eval()`/`compile()` escape class entirely — there is no interpreter-level code execution left to sandbox on **either** the native-engine path or the default LangChain server path.
- A single shared security boundary: the LangChain condition path and the engine path validate and walk expressions through the same code, so a hardening change applies to both at once and the two can no longer drift.
- Evaluation is explicit and auditable: only allowlisted node types and a single allowlisted callable execute.
- The default condition path now fails **closed** and logged: a malformed / adversarial `when` / `loop_until` raises `ConditionEvaluationError` instead of silently returning `False`.
- Adversarial coverage in `tests/test_expressions.py` (engine) and `tests/test_langchain_expressions.py` (condition-path parity): dunder-traversal vectors, `str.format`/`format_map` bypass attempts, the sequence-multiply DoS cap, and a fail-closed + redacted-logging assertion. Every prior evaluator test is retained and passing.

### Negative

- New operators or node types must be added to the interpreter explicitly rather than inherited for free from Python — a deliberate, security-positive constraint.
- Marginally more code than a single `eval()` call.
- Callers of `evaluate_condition` must tolerate `ConditionEvaluationError` for unevaluable input (the prior contract silently returned `False`). This is the intended fail-closed behavior; legitimate conditions are unaffected.

### Provenance

The AST-interpreter design was prototyped in the sibling `agentic-systems-lab` repository and upstreamed here. This ADR records the decision as adopted by `agentic-runtime-platform`; it does **not** import any execution-engine decision from that repository — ARP retains the dual-engine architecture of [ADR-001](ADR-001-002-003-architecture-decisions.md) and the LangChain adapter of [ADR-020](ADR-020-langchain-adapter-eager-validation.md).

---

## Implementation

- `agentic_v2/engine/expressions.py` — `_safe_eval` (parse + validate + interpret), `_eval_node`, `_validate_ast`, `_BINOP_OPS` / `_UNARYOP_OPS` / `_CMPOP_OPS`, `_MAX_SEQUENCE_MULTIPLY`; plus the shared `evaluate_safe_expression(...)` entry point and the `ExpressionError` type reused by the LangChain path.
- `agentic_v2/langchain/expressions.py` — `evaluate_condition` keeps the `${...}` → `repr(value)` substitution layer and delegates the final evaluation to `evaluate_safe_expression`; the fail-open `except` is replaced with fail-closed `ConditionEvaluationError` + redacted logging. `resolve_expression` (pure path / `coalesce` resolution, never `eval`) is unchanged.
- `tests/test_expressions.py` — engine security corpus (dunder-traversal, `str.format`/`format_map` bypass, sequence-multiply DoS).
- `tests/test_langchain_expressions.py` — condition-path adversarial parity (`_ADVERSARIAL_CONDITION_VECTORS`) plus a fail-closed + redacted-logging test.
