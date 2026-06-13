# ADR-024: Expression Evaluation via AST Interpreter (Eliminate eval())

**Status:** Accepted
**Date:** 2026-06-13
**Related:** [ADR-001](ADR-001-002-003-architecture-decisions.md) (native DAG engine), [ADR-018](ADR-018-api-rate-limiting-and-auth-throttle.md) / [ADR-021](ADR-021-jwt-oidc-authentication.md) / [ADR-022](ADR-022-tenant-isolation.md) (security & reliability domain)

---

## Context

Workflow conditional edges and `${...}` substitutions are resolved by the expression evaluator in `agentic_v2/engine/expressions.py`. The evaluator previously compiled each expression to a Python code object and executed it with `eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, env)` — an AST-validated, empty-builtins sandbox.

Even with an empty `__builtins__` map and a node allowlist, `eval()`-based sandboxes carry residual risk:

- **Dunder-traversal escape:** expressions such as `().__class__.__mro__[-1].__subclasses__()` can reach arbitrary types unless dunder access is blocked at every layer.
- **`str.format` / `format_map` bypass:** the format-string machinery can be coerced into attribute traversal.
- **Engine-trust dependency:** the sandbox's safety depends on the CPython `eval`/`compile` machinery remaining escape-free across interpreter versions.

Workflow condition strings originate from authored YAML and, in multi-tenant deployments (ADR-022), potentially from less-trusted sources. An `eval()` call on that path is the kind of construct a security reviewer flags on sight.

---

## Decision

Replace `eval()`/`compile()` in the expression evaluator with a **pure-Python AST interpreter**.

The evaluator now:

1. Parses the expression to an AST (`ast.parse(..., mode="eval")`).
2. Validates the tree against a node allowlist via `_validate_ast`, rejecting dunder attribute and name access at validation time.
3. Walks the validated tree node-by-node in `_eval_node`, dispatching binary, unary, and comparison operators through the `operator` module. **No `eval()` or `compile()` is invoked.**

Two abuse bounds are enforced in the interpreter:

- **Call allowlist by identity:** only the built-in `coalesce` helper is callable (checked by object identity, not name), so no arbitrary method invocation is reachable.
- **Sequence-multiply DoS cap:** `_MAX_SEQUENCE_MULTIPLY` bounds `seq * n` expansions to prevent memory exhaustion via large multiplications.

The public `ExpressionEvaluator` API (`evaluate`, `resolve_variable`) is unchanged; this is an internal, behavior-compatible substitution.

---

## Consequences

### Positive

- Eliminates the `eval()`/`compile()` escape class entirely — there is no interpreter-level code execution left to sandbox.
- Evaluation is explicit and auditable: only allowlisted node types and a single allowlisted callable execute.
- Adversarial coverage added to `tests/test_expressions.py`: dunder-traversal vectors, `str.format`/`format_map` bypass attempts, and the sequence-multiply DoS cap (128 cases total; every prior evaluator test retained and passing).

### Negative

- New operators or node types must be added to the interpreter explicitly rather than inherited for free from Python — a deliberate, security-positive constraint.
- Marginally more code than a single `eval()` call.

### Provenance

The AST-interpreter design was prototyped in the sibling `agentic-systems-lab` repository and upstreamed here. This ADR records the decision as adopted by `agentic-runtime-platform`; it does **not** import any execution-engine decision from that repository — ARP retains the dual-engine architecture of [ADR-001](ADR-001-002-003-architecture-decisions.md) and the LangChain adapter of [ADR-020](ADR-020-langchain-adapter-eager-validation.md).

---

## Implementation

- `agentic_v2/engine/expressions.py` — `_safe_eval` (parse + validate + interpret), `_eval_node`, `_validate_ast`, `_BINOP_OPS` / `_UNARYOP_OPS` / `_CMPOP_OPS`, `_MAX_SEQUENCE_MULTIPLY`.
- `tests/test_expressions.py` — 128 cases including the security vectors above.
