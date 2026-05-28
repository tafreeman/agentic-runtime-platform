# ADR-010: Commit-Driven A/B Agent Evaluation Harness — Methodology & Design

---

| Field          | Value |
|----------------|-------|
| **ID**         | ADR-010 |
| **Status**     | 🟡 Proposed |
| **Date**       | 2026-03-06 |
| **System**     | tools/commit_eval · agentic-workflows-v2 · agentic-v2-eval |
| **Authors**    | Platform Engineering |
| **Reviewers**  | Research Infra, ML Platform, Security |
| **Supersedes** | _(none)_ |

---

## 1. TL;DR

> **We adopt a SWE-bench–inspired evaluation pattern pointed at our own commits: extract
> requirements from `git show`, create one git worktree at `<commit>~1` (pre-task state),
> run two contestant strategies sequentially (A → reset → B), extract git patches, and
> score both using a two-layer system — LLM-as-judge for semantic quality plus rubric-driven
> static analysis for structural standards. No Docker. One worktree, sequential execution,
> real commits as ground truth.**

---

## 2. Status History

| Date | Status | Note |
|------|--------|------|
| 2026-03-06 | 🟡 Proposed | Initial design — commit-driven A/B harness |

---

## 3. Context & Problem Statement

The platform team has built a multi-agent workflow runtime capable of generating code.
The pressing question is: **how do we objectively measure whether one agent, workflow, or
prompt strategy produces better code than another?**

```
┌──────────────────────────────────────────────────────────────────┐
│       THREE QUESTIONS THE EVAL HARNESS MUST ANSWER               │
├──────────────────────────────────────────────────────────────────┤
│  Q1 │ What is ground-truth "correct" output for a code task?     │
│  Q2 │ How do we isolate two strategies to compare them fairly?   │
│  Q3 │ How do we score a generated patch vs. the gold standard?   │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 Existing Approaches and Their Limits

| Approach | Problem |
|----------|---------|
| Manual code review | Expert judgment; not repeatable; introduces reviewer bias; doesn't scale |
| Synthetic benchmarks (HumanEval, MBPP) | Toy problems; doesn't reflect real production code patterns or domain conventions |
| Hold-out test sets | Requires pre-labeling; quickly goes stale; task diversity is narrow |
| Arbitrary prompts with LLM judge | No ground truth; "good" is undefined without a reference implementation |
| SWE-bench (public) | Docker-based; public repos only; fixed 2,294 pre-labeled issues; cannot evaluate own repo commits |

### 3.2 The SWE-bench Insight — Commits as Ground Truth

Jimenez, Yang, Wettig, Yao, Pei, Press, and Narasimhan introduced SWE-bench at ICLR 2024
(arXiv:2310.06770), building a benchmark of 2,294 real GitHub issues from 12 popular Python
repositories. Every instance is a pull request that:
- Is associated with an issue (the task specification)
- Modified one or more test files (the test oracle)
- Has an implementation diff (the gold standard)

Gold solutions edit an average of **1.7 files, 3.0 functions, and 32.8 lines**. The initial
RAG-only baseline solved just **1.96%** of instances; even the "oracle" condition (given the
exact files to edit) reached only **4.80%**. This intentionally high bar forced the field
toward proper agent scaffolding and validated the commit-as-ground-truth structure as a
rigorous, non-trivial evaluation surface.

```
┌───────────────────────────────────────────────────────┐
│  COMMIT AS GROUND TRUTH (the SWE-bench insight)       │
│                                                       │
│  git show <sha>:                                      │
│    commit message   →  task specification             │
│    diff             →  gold standard implementation   │
│    test changes     →  test oracle                    │
│    <sha>~1 state    →  pre-task baseline              │
└───────────────────────────────────────────────────────┘
```

### 3.3 Extension to Own Repos — The Automation Gap

SWE-rebench (Badertdinov et al., NeurIPS 2025, arXiv:2505.20411) demonstrated that the
SWE-bench pattern can be fully automated and extended to arbitrary repositories. The pipeline
filters approximately 450,000 pull requests across 30,000+ repositories and uses LLM-driven
extraction to produce 21,000+ verified interactive tasks. A key finding: models like GPT-4.1
show a measurable performance drop on March–April 2025 tasks compared to earlier dates,
suggesting contamination in fixed benchmarks. This validates the need for continuously
updated, private-commit evaluation.

SWE-Bench++ (Wang et al., arXiv:2512.17419, 2025) further demonstrated scalable benchmark generation across
11 languages and 3,971 repositories, achieving 137% higher environment yield than the
SetUpAgent baseline on Python repos by using template-guided Dockerfile synthesis and
adaptive test log parsing.

**The gap**: no existing tool combines (1) own private repo, (2) arbitrary commit SHA,
(3) own workflow/prompt/agent strategies as contestants, (4) own domain rubrics, and
(5) real-time streaming results to a web UI.

---

## 4. Decision

### 4.1 Commit Extraction via `git show`

**`CommitExtractor`** runs `git show --stat --patch <sha>` and extracts:

- Commit message body → task context
- Full unified diff → `gold_patch`
- File list from `--stat` → `affected_files`
- Test files (heuristic: `test_*.py`, `*_test.py`, paths under `tests/`) → `test_oracle_files`
- An LLM call via `LLMClient.generate_text()` synthesizes a clean `requirements_prompt`

Extraction prompt template:

```
Given the following git commit message and code diff from a production repository,
extract a concise but complete requirements specification that captures:
1. The problem being solved or feature being added
2. The constraints and acceptance criteria
3. The expected behavior changes visible in the diff

Focus on what, not how — describe the task as it would be given to a developer
who has not seen the solution.

Commit message: {commit_message}

Diff (truncated to {max_tokens} tokens):
{diff}
```

Supports both local paths and GitHub URLs. For URLs: `git clone --bare <url>
/tmp/eval-repo-{uuid}` then proceeds as local.

### 4.2 Sandbox Isolation via git worktree (not Docker)

**`SandboxManager`** creates one git worktree at the pre-commit state:

```
git worktree add /tmp/eval-{uuid} <sha>~1   # isolate at pre-task state
  [run Contestant A — agent writes files]
git -C /tmp/eval-{uuid} checkout -f HEAD     # wipe A's changes (index op only)
  [run Contestant B — agent writes files]
git worktree remove /tmp/eval-{uuid} --force # cleanup
```

Used as a context manager:

```python
with SandboxManager(repo_path, pre_commit_sha) as worktree_path:
    trial_a = await runner.run(contestant_a, task, worktree_path)
    sandbox.reset()
    trial_b = await runner.run(contestant_b, task, worktree_path)
```

### 4.3 Sequential Contestant Execution (one worktree, not two)

```
┌────────────────────────────────────────────────────────────┐
│  SEQUENTIAL EVALUATION FLOW                                │
│                                                            │
│  worktree @ sha~1                                          │
│      │                                                     │
│      ├── [Run Contestant A]                                │
│      │       agent / workflow / prompt writes files        │
│      │       git diff HEAD  →  patch_a                    │
│      │       pytest oracle  →  test_results_a             │
│      │                                                     │
│      ├── git checkout -f HEAD  (reset — microseconds)      │
│      │                                                     │
│      ├── [Run Contestant B]                                │
│      │       agent / workflow / prompt writes files        │
│      │       git diff HEAD  →  patch_b                    │
│      │       pytest oracle  →  test_results_b             │
│      │                                                     │
│      └── git worktree remove --force                       │
└────────────────────────────────────────────────────────────┘
```

### 4.4 Two-Layer Scoring

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: LLM-as-Judge (semantic quality)                   │
│                                                             │
│  tools/agents/benchmarks/llm_evaluator.py:evaluate_with_llm │
│                                                             │
│  Input:  requirements_prompt + generated patch + gold patch │
│  Output: EvaluationResult, 0–10 per dimension              │
│                                                             │
│  Dimension       Weight  What it catches                    │
│  ─────────────── ──────  ──────────────────────────────     │
│  completeness     25%    Task fully addressed?              │
│  correctness      25%    Code correct vs. gold standard?    │
│  quality          20%    Clean, readable, idiomatic?        │
│  specificity      15%    Concrete, not boilerplate?         │
│  alignment        15%    Matches original intent?           │
│                                                             │
│  LAYER 2: Rubric-Driven Static Analysis (structural std.)   │
│                                                             │
│  agentic-v2-eval/src/agentic_v2_eval/scorer.py:Scorer       │
│                                                             │
│  Input:  patch text (raw diff)                             │
│  Output: ScoringResult, 0.0–1.0 weighted rubric score      │
│  Rubric: coding_standards.yaml (Style & Formatting,         │
│          Type Safety, Naming & Structure, Error Handling,    │
│          Testing, Security & Privacy, ML Reproducibility,   │
│          Deployment Readiness)                               │
└─────────────────────────────────────────────────────────────┘
```

Both layers are required. The LLM judge evaluates semantic intent and functional
correctness but is known to reward fluency over structure. The rubric layer
mechanically catches missing type annotations, bare `except` clauses, undocumented
functions, and other project standards that the LLM does not reliably penalize.

> **Integration note:** `evaluate_with_llm()` and `Scorer` exist independently in the
> codebase today and are not currently wired together. The two-layer scoring pipeline
> described here is **new integration work proposed by this ADR**, not reuse of an
> existing composed system.
>
> **Async note:** `evaluate_with_llm()` is a synchronous function (regular `def`, not
> `async def`). Since the `Comparator` orchestrator is async, calls to
> `evaluate_with_llm()` must be wrapped with `asyncio.to_thread()` to avoid blocking
> the event loop.

---

## 5. Files Changed

| File | Purpose |
|------|---------|
| `tools/commit_eval/__init__.py` | Package exports |
| `tools/commit_eval/models.py` | `TaskInstance`, `Contestant`, `Trial`, `ComparisonResult` |
| `tools/commit_eval/extractor.py` | `CommitExtractor` (`git show` → LLM → `TaskInstance`) |
| `tools/commit_eval/sandbox.py` | `SandboxManager` (git worktree lifecycle context manager) |
| `tools/commit_eval/runner.py` | `ContestantRunner` (workflow / prompt / agent dispatch) |
| `tools/commit_eval/patch.py` | `PatchExtractor` + `TestRunner` |
| `tools/commit_eval/evaluator.py` | `EvalHarness` (two-layer scoring) |
| `tools/commit_eval/comparator.py` | `Comparator` (main orchestrator) |
| `tools/commit_eval/reporter.py` | `ComparisonReporter` (wraps existing HTML/MD reporters) |
| `tools/commit_eval/cli.py` | typer CLI entry point |
| `tools/__init__.py` | Add `commit_eval` export |
| `pyproject.toml` (root) | Add `pytest-json-report` dependency; add `agentic-v2-eval` as cross-package dependency (required for `tools/commit_eval/` to import `agentic_v2_eval.scorer`) (note: `typer >=0.9,<1` is already declared in `agentic-workflows-v2/pyproject.toml`, so it is not a net-new dependency to the workspace) |

---

## 6. Rationale

### 6.1 Production Precedents for Commit-as-Ground-Truth Evaluation

| System | Approach | Relevance to This ADR |
|--------|----------|-----------------------|
| **SWE-bench** (Jimenez et al., ICLR 2024) | 2,294 real GitHub PRs; Docker sandbox; patch vs. test oracle | Direct methodology inspiration; validates commit as verifiable task source |
| **SWE-rebench** (NeurIPS 2025) | Automated LLM extraction from 450K+ PRs; 21K+ tasks; decontamination-aware | Proves that LLM can reliably extract requirements from `git show` output at scale |
| **SWE-Bench++** (Wang et al., arXiv:2512.17419, 2025) | 11 languages, 3,971 repos; 137% yield improvement; template-guided env setup | Confirms the base/before/after three-snapshot model; shows test oracle generation is automatable |
| **Aider SWE-bench** (aider.chat, 2024) | 26.3% on SWE-bench Lite (SOTA); uses git repo map + AST analysis | Demonstrates that commit-driven eval is the de facto standard for code agent benchmarking |
| **SWE-bench Live** (arXiv:2505.23419) | Continuously updatable commit corpus; broader repo coverage | Validates continuously updated private-commit eval as superior to fixed benchmarks |

### 6.2 git worktree over Docker

| Factor | git worktree | Docker container |
|--------|-------------|------------------|
| Startup time | ~100 ms (index checkout) | 5+ seconds additional per launch per published benchmarks |
| Context switch in CI | ~30 seconds (worktree-based) | 10+ minutes (container provision + image pull) |
| Windows support | Native — no daemon required | Requires Docker Desktop; problematic in non-admin environments |
| Reset cost | `git checkout -f HEAD` — index ops only, microseconds | Destroy + recreate container (seconds) |
| Disk footprint | One shallow copy of tracked files | Full container image layer stack |
| Isolation depth | File system only | OS-level (separate namespaces, network stack) |
| Sufficient for single-repo eval | Yes — no cross-repo contamination possible | Overkill — cross-process isolation not needed |
| Required for multi-repo at scale | Not ideal | Yes |

For a single-repo, single-commit evaluation (the targeted use case), file system
isolation via git worktree is sufficient. Docker's OS-level isolation guarantees are
unnecessary when both contestants run against the same repository with no external
service dependencies.

### 6.3 Sequential over Parallel (one worktree, not two)

| Factor | Sequential (one worktree) | Parallel (two worktrees) |
|--------|--------------------------|--------------------------|
| Implementation complexity | Simple: reset between runs | Two independent lifecycle objects |
| Disk usage | One repo copy | Two repo copies |
| Environmental drift risk | None — identical binary, env vars | Possible if process spawns diverge |
| Test oracle port conflicts | None — sequential execution | Possible if tests bind to fixed ports |
| Wall-clock time | A time + B time | max(A time, B time) |

**Chosen: sequential.** Evaluation fidelity — identical environment for both contestants
— is more important than wall-clock speed for a tool used interactively or in CI. The time
saving from parallel execution does not justify the added implementation complexity or the
risk of environmental bias between the two sandboxes.

### 6.4 Two-Layer Scoring vs. Single LLM Judge

A pure LLM judge has a documented blind spot: it rewards fluency and apparent confidence,
not structural correctness. Empirically, high-scoring LLM-reviewed outputs routinely omit
type hints, use bare `except Exception: pass`, and employ magic number constants — all
patterns the LLM judge marks as acceptable because they read naturally. The rubric layer
catches these mechanically and deterministically.

| Scoring Layer | Catches | Misses |
|---------------|---------|--------|
| LLM-as-judge | Semantic correctness, task alignment, code intent, logical completeness | Structural standards, missing annotations, bare excepts, naming violations |
| Rubric (coding_standards) | Style & Formatting, Type Safety, Naming & Structure, Error Handling, Testing, Security & Privacy, ML Reproducibility, Deployment Readiness | Semantic correctness, business logic correctness |
| **Both combined** | Full spectrum — semantic AND structural | — |

---

## 7. Consequences

### 7.1 Positive Outcomes

| Outcome | Mechanism |
|---------|-----------|
| Real, diverse task corpus | Every commit in the repo is a potential eval case with no pre-labeling |
| Version-controlled ground truth | Gold patch is in git history; immutable and auditable |
| No synthetic benchmark staleness | Each evaluation targets actual production code, not toy problems |
| Reuses existing eval infrastructure | `evaluate_with_llm()`, `Scorer`, rubrics, reporters unchanged |
| Domain-specific standards | Existing `coding_standards.yaml` rubric already calibrated for this codebase |

### 7.2 Trade-offs and Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Requirements extraction quality depends on commit message quality | Medium | Flag low-confidence extractions; allow manual `--requirements-file` override |
| git worktree incompatible with sparse checkout or certain submodule configs | Low | Detect and warn at `SandboxManager.__init__`; document known incompatibilities |
| Test oracle absent if commit doesn't include test changes | Low | Test phase is optional; LLM + rubric scoring still runs without it |
| LLM judge latency adds significant wall-clock time per eval | Low | Run scoring asynchronously after both trials complete; cache by `(sha, contestant_hash)` |
| Sequential execution means total runtime is A + B elapsed time | Low | Stream phase progress events so UI stays responsive; add per-contestant timeout |
| Gold patch contains implementation details that bias the LLM judge | Low | Strip the gold patch from the `requirements_prompt` template; pass it only to the scorer |

---

## 8. Alternatives Considered

| Alternative | Rejected Because |
|-------------|-----------------|
| **Docker containers for sandbox isolation** | 5+ second startup per run; requires Docker Desktop on Windows; OS-level isolation exceeds requirements for single-repo eval |
| **Two worktrees in parallel** | Added implementation complexity; environmental drift risk between sandboxes undermines evaluation parity |
| **GitHub Actions runners as sandboxes** | Minutes to provision; no offline support; incompatible with local iterative use |
| **`difflib` similarity score as evaluation** | Token-level similarity does not capture semantic correctness; brittle to formatting changes; rewards verbosity |
| **Human review board** | Not scalable; introduces reviewer bias; incompatible with automated CI evaluation |
| **Single LLM judge (no rubric)** | Misses structural violations; documented blind spot for annotation and error-handling standards |
| **Single rubric (no LLM judge)** | Cannot assess semantic correctness, task alignment, or logical completeness |
| **promptfoo as the orchestration layer** | Node.js dependency; no git worktree integration; no patch-level comparison; no private-commit support |

---

## 9. References

| Citation | Relevance |
|----------|-----------|
| Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan — **SWE-bench: Can Language Models Resolve Real-World GitHub Issues?** (ICLR 2024, arXiv:2310.06770) | Original commit-as-ground-truth benchmark; establishes 1.96% RAG baseline, test oracle methodology |
| Badertdinov et al. — **SWE-rebench: An Automated Pipeline for Task Collection and Decontaminated Evaluation of Software Engineering Agents** (NeurIPS 2025, arXiv:2505.20411) | Automated LLM extraction from 450K+ PRs; 21K+ tasks; decontamination evidence |
| Wang et al. — **SWE-Bench++: A Framework for the Scalable Generation of Software Engineering Benchmarks** (arXiv:2512.17419, 2025) | Multi-language scalable commit extraction; base/before/after snapshot model |
| Zhang et al. — **SWE-bench Live** (arXiv:2505.23419) | Continuously updatable commit corpus; broader repo coverage than fixed benchmarks |
| Aider Team — **SWE-bench technical results** (aider.chat, 2024) | 26.3% on SWE-bench Lite using git repo map + AST; validates commit-driven eval as de facto standard |
| `tools/agents/benchmarks/llm_evaluator.py` | Existing `evaluate_with_llm()` function (5 dimensions, 0–10 scale, weighted) |
| `agentic-v2-eval/src/agentic_v2_eval/scorer.py` | Existing `Scorer` class (rubric-driven, weighted 0.0–1.0) |
| `agentic-v2-eval/src/agentic_v2_eval/rubrics/coding_standards.yaml` | Default structural rubric for Python code evaluation |
| git-scm.com — **git-worktree documentation** | Worktree semantics, `checkout -f HEAD` reset behavior, `remove --force` cleanup |

---

## 10. Decision Map

```
┌──────────────────────────────────────────────────────────────────────┐
│  ADR-010 DECISION MAP                                                │
│                                                                      │
│  Evaluation Task Source                                              │
│    ├── Synthetic benchmark (HumanEval, MBPP) ──────── REJECTED       │
│    ├── Manual task specification ──────────────────── REJECTED       │
│    └── Real git commit (git show <sha>) ────────────── CHOSEN        │
│                                                                      │
│  Sandbox Isolation                                                   │
│    ├── Docker container ────────────────────────────── REJECTED       │
│    ├── Two worktrees in parallel ───────────────────── REJECTED       │
│    └── One git worktree, sequential ────────────────── CHOSEN        │
│                                                                      │
│  Scoring                                                             │
│    ├── difflib similarity score ────────────────────── REJECTED       │
│    ├── LLM-as-judge only ───────────────────────────── REJECTED       │
│    ├── Rubric only ─────────────────────────────────── REJECTED       │
│    └── LLM-as-judge + rubric (two layers) ──────────── CHOSEN        │
│                                                                      │
│  Scope                                                               │
│    ├── Public repos only (SWE-bench) ───────────────── INSUFFICIENT  │
│    └── Own private repo + arbitrary commit SHA ─────── CHOSEN        │
└──────────────────────────────────────────────────────────────────────┘
```
