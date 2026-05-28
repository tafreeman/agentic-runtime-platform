# ADR-009: Deep Research Scoring Enhancements — Exponential Decay, Lexicographic Selection, and Immutable Contracts

---

| Field | Value |
| --- | --- |
| **ID** | ADR-009 |
| **Status** | 🟢 Accepted |
| **Date** | 2026-03-03 |
| **System** | agentic-workflows-v2 · deep-research pipeline · scoring engine |
| **Authors** | Platform Engineering |
| **Reviewers** | Multi-perspective agent team (Architect, Scoring Theory, Workflow Engine, Code Quality) |
| **Extends** | ADR-007 (Classification Matrix and Stop Policy) |

---

## 1. TL;DR

> **Four enhancements to the ADR-007 scoring engine, identified by a parallel multi-perspective agent analysis: (1) immutable module constants via `MappingProxyType`, (2) exponential recency decay replacing binary thresholds, (3) lexicographic round selection in `coalesce_best_round()`, and (4) config-driven recency windows from `evaluation.yaml`. All changes are backward-compatible; the non-compensatory gate logic is unchanged.**

---

## 2. Status History

| Date | Status | Note |
| ------ | -------- | ------ |
| 2026-03-03 | 🟢 Accepted | Implemented and verified: 1,333 tests passing, 28 new tests added |

---

## 3. Context & Problem Statement

During Sprint 9 (Deep Research) implementation review, a four-agent specialist team independently analyzed the scoring system from orthogonal perspectives:

- **Architect agent**: System design and contract safety
- **Scoring theory agent**: Mathematical correctness of recency modeling
- **Workflow engine agent**: YAML execution and round selection semantics
- **Code quality agent**: Immutability, testability, configuration hygiene

### 3.1 Convergent Findings

The team converged on four issues:

1. **Mutable module constants** — `DEFAULT_WEIGHTS` and `DOMAIN_RECENCY_DAYS` are plain `dict` objects. Any caller can accidentally mutate them (e.g., `DEFAULT_WEIGHTS["coverage"] = 0.99`), corrupting all subsequent scoring calls in the same process.

2. **Binary recency threshold** — The existing `get_recency_window()` returns a day count, but the actual recency *scoring* is binary: a source is either "within window" or "outside." A 91-day-old AI/ML paper (just past the 90-day window) receives the same zero-freshness treatment as a 5-year-old paper.

3. **Coalesce picks latest round on CI ties** — When two rounds both pass the gate with identical CI scores, Python's `max()` picks the last one found (latest round). This wastes compute: if R2 and R4 both pass with CI=0.80, we should prefer R2 (converged earlier).

4. **Hardcoded recency windows** — `DOMAIN_RECENCY_DAYS` is defined at the Python module level. Operators cannot tune recency windows without code changes and redeployment.

---

## 4. Decision

### 4.1 Immutable Constants (Enhancement 1)

**Change**: Wrap `DEFAULT_WEIGHTS` and `DOMAIN_RECENCY_DAYS` in `MappingProxyType`.

**Type annotation change**: `dict[str, float]` → `Mapping[str, float]`; `dict[str, int]` → `Mapping[str, int]`.

**Behavioral impact**: Read-only at runtime. `TypeError` raised on attempted mutation. All existing `.get()`, iteration, and `in` checks work identically.

**Rationale**: Aligns with the project's immutability-first style for shared constants. The `_TIEBREAKER_WEIGHTS` in `multidimensional_scoring.py` already used `MappingProxyType` — this makes the pattern consistent.

### 4.2 Exponential Recency Decay (Enhancement 2)

**New function**: `recency_decay(age_days, *, half_life_days, domain, config_windows) → float`

**Formula**:

``` math
score = exp(-λ × age_days)
λ = ln(2) / half_life_days
```

**Properties**:

- `age_days = 0` → score = 1.0 (brand new)
- `age_days = half_life_days` → score = 0.5 (definition of half-life)
- `age_days = 2 × half_life_days` → score = 0.25
- Monotonically decreasing, asymptotically approaching 0.0

**Domain half-lives** are derived from `DOMAIN_RECENCY_DAYS` (or config overrides):

| Domain | Half-life | At 1 year old |
| -------- | ----------- | --------------- |
| `ai_ml` | 90 days | 0.063 |
| `cloud_infrastructure` | 180 days | 0.234 |
| `programming_languages` | 365 days | 0.500 |
| `academic_research` | 730 days | 0.707 |

**Backward compatibility**: This is a new function. Existing binary recency scoring is unaffected. Callers can opt in to `recency_decay()` when computing recency dimension scores.

### 4.3 Lexicographic Round Selection (Enhancement 3)

**Changed function**: `coalesce_best_round(round_results) → dict | None`

**Previous behavior**: Filter passing rounds → `max(ci_score)`. If no rounds pass, `max(ci_score)` over all. On CI ties, last round wins (Python `max()` stability).

**New behavior**: Lexicographic sort key `(gate_passed, ci_score, -index)`:

1. **gate_passed** — passing rounds always beat failing rounds
2. **ci_score** — higher CI wins among same gate status
3. **-index** — earlier rounds win ties (prefer first convergence, minimize compute)

**Behavioral change**: Only observable when two rounds have identical gate status AND identical CI scores. Previously the later round won; now the earlier round wins. This is strictly better: it returns the same-quality result using less compute.

### 4.4 Config-Driven Recency Windows (Enhancement 4)

**New function**: `load_recency_windows(eval_config) → Mapping[str, int]`

**New config key** in `evaluation.yaml`:

```yaml
evaluation:
  deep_research:
    recency_windows:
      ai_ml: 90
      cloud_infrastructure: 180
      ai_software: 120
      default: 183
```

**Behavior**: Merges config values over module-level defaults. Unknown domains in config are added. Non-integer values are logged and ignored. Returns an immutable `MappingProxyType`.

**`get_recency_window()` extended**: New `config_windows` keyword argument for callers that have loaded config.

---

## 5. Files Changed

| File | Change |
| ------ | -------- |
| `workflows/lib/ci_calculator.py` | MappingProxyType constants, `recency_decay()`, `load_recency_windows()`, extended `get_recency_window()` |
| `server/multidimensional_scoring.py` | `_round_sort_key()`, lexicographic `coalesce_best_round()` |
| `config/defaults/evaluation.yaml` | Added `recency_windows` section |
| `tests/test_ci_calculator.py` | +23 tests (immutability, decay, config loading) |
| `tests/test_multidimensional_scoring.py` | +5 tests (lexicographic selection) |

---

## 6. Risks and Mitigations

| Risk | Severity | Mitigation |
| ------ | ---------- | ------------ |
| `MappingProxyType` type annotation change breaks callers expecting `dict` | Low | Type changed to `Mapping` (supertype of `dict`); all `.get()` and iteration patterns work identically |
| Exponential decay produces different recency scores than binary | Low | `recency_decay()` is opt-in; existing binary scoring path unchanged |
| Lexicographic selection changes which round wins on CI ties | Low | Only affects exact CI ties with same gate status — extremely rare in practice; change is strictly better (less compute) |
| Config-driven windows could introduce invalid values | Low | Non-integer values are logged and ignored; defaults always available as fallback |

---

## 7. Test Coverage

28 new tests added, all passing:

- **4 tests**: Immutable constant enforcement (`TypeError` on mutation, read API preserved)
- **12 tests**: Exponential decay (half-life properties, monotonicity, domain derivation, edge cases, mathematical correctness)
- **7 tests**: Config-driven windows (defaults, overrides, immutability, invalid values, integration)
- **5 tests**: Lexicographic selection (CI tie → earlier round wins, failing vs passing, 4-round scenarios)

Total test count: 1,333 passed | 3 pre-existing failures | 15 skipped.

---

## 8. Decision Outcome

All four enhancements are **accepted and implemented**. They strengthen the ADR-007 scoring engine without changing the non-compensatory gate logic or CI tiebreaker formula. The changes are fully backward-compatible — no existing callers need modification.
