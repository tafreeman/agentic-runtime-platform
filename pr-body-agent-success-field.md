# PR handoff — agent `success` field fix

Prepared by the Test Improver run on 2026-07-31. **Not committed** — see
"Why this isn't done" below. Everything needed to finish is here.

---

## Step 0 — clear the stale git locks (required first)

Git writes in this repo are currently blocked by a stale lock. From PowerShell:

```powershell
cd C:\Users\tandf\source\agentic-runtime-platform
Remove-Item .git\index.lock, `
            .git\objects\maintenance.lock, `
            ".git\refs\heads\fix\agent-output-success-field.lock", `
            .git\worktrees\prwt\HEAD.lock -ErrorAction SilentlyContinue
git worktree prune          # drops the dead /tmp/prwt and arp-memoryctl-fix entries
git status                  # should work again
```

`.git\index.lock` is dated **2026-07-31 18:49**, before this run started — it is
from an earlier crashed git process, and it is what blocked the commit.

## Step 1 — branch

`fix/agent-output-success-field` already exists at `origin/main` (`e97eeef6`)
with **no commits on it**. Your working tree has ~16 unrelated modified files
(`agent_resolver.py`, `model_inventory.py`, docs, mcp tests …), so don't switch
branches with those in flight. Use a worktree:

```powershell
git worktree add ..\arp-agent-success fix/agent-output-success-field
cd ..\arp-agent-success
```

Then copy the three files over from the main checkout:

```powershell
$src = "C:\Users\tandf\source\agentic-runtime-platform"
copy "$src\agentic-workflows-v2\agentic_v2\agents\test_agent.py"  agentic-workflows-v2\agentic_v2\agents\
copy "$src\agentic-workflows-v2\agentic_v2\agents\architect.py"   agentic-workflows-v2\agentic_v2\agents\
copy "$src\agentic-workflows-v2\tests\test_test_agent_pipeline.py" agentic-workflows-v2\tests\
```

## Step 2 — two commits

```powershell
git add agentic-workflows-v2/agentic_v2/agents/test_agent.py `
        agentic-workflows-v2/agentic_v2/agents/architect.py
git commit -F commit-1.txt

git add agentic-workflows-v2/tests/test_test_agent_pipeline.py
git commit -F commit-2.txt
```

**`commit-1.txt`**

```
fix(agents): populate required success field in agent output

TaskOutput.success is declared without a default, but TestAgent and
ArchitectAgent both constructed their output model without it, so
_parse_output raised ValidationError for every input and neither
agent's run() could ever return. CoderAgent, ReviewerAgent and
OrchestratorAgent already pass the field; these two were the outliers.

Use the CoderAgent idiom (success=bool(code)): an output that no
artifact could be recovered from is not a success.

Also adds the __test__ = False marker to TestGenerationOutput, the one
class in the module missing it, which made pytest emit a
PytestCollectionWarning whenever a test module imported it.
```

**`commit-2.txt`**

```
test(agents): cover TestAgent model-call and parsing pipeline

The existing suite exercised only the private helpers, never
_parse_output or run(), which is why the missing success field went
unnoticed through 36 green tests. Adds 65 tests over the
response-handling seam: both _call_model branches (including that the
backend-less canned response must satisfy the agent's own
_is_task_complete, or a keyless run() degrades to a max-iterations
RuntimeError), the coverage_estimate heuristic's floor/slope/cap,
filename-resolution fallbacks in _parse_test_files, and the
test_types validator.

Coverage of agentic_v2/agents/test_agent.py: 75.96% -> 97.61%.

Includes a characterisation test for the empty-test_prefix quirk:
typescript and javascript set test_prefix = "", so str.startswith("")
always matches and a bare ```typescript fence becomes the filename,
making the generated.test.ts fallback unreachable. Pinned rather than
fixed, since changing it changes output filenames.
```

## Step 3 — push and open the PR

```powershell
git push -u origin fix/agent-output-success-field
gh pr create --base main --title "fix(agents): populate required success field in agent output" --body-file <this file, PR body section below>
```

---

## PR body

### What

`TaskOutput.success` is declared without a default
(`agentic_v2/contracts/schemas.py:116`). `TestAgent._parse_output` and
`ArchitectAgent._parse_output` both built their output model without passing
it, so **both agents raised `ValidationError` on every `run()`**:

```
TestAgent:      ValidationError: 1 validation error for TestGenerationOutput
ArchitectAgent: ValidationError: 1 validation error for ArchitectureOutput
```

`CoderAgent` (`success=bool(code)`), `ReviewerAgent` and `OrchestratorAgent`
all pass the field. These two were the only ones that didn't.

### Why it wasn't caught

`tests/test_new_agents.py` exercises only the private helpers —
`_format_task_message`, `_parse_test_files`, `_count_tests`,
`_generate_summary`. It never calls `_parse_output` or `run()`, which is
exactly where the output model gets constructed. 36 passing tests, agent
100% unusable.

### Changes

| File | Change |
|---|---|
| `agents/test_agent.py` | `success=bool(test_files)`; `__test__ = False` on `TestGenerationOutput` |
| `agents/architect.py` | `success=bool(tech_stack)` |
| `tests/test_test_agent_pipeline.py` | new, 65 tests |

11 lines of production change.

### Verification

| Gate | Result |
|---|---|
| New file standalone | 65 passed |
| With `test_new_agents` / `test_agents` / `test_agents_orchestrator` | 149 passed, 0 warnings |
| Full unit suite (`not integration and not slow`, `--ignore=tests/e2e`) | **4,267 passed**, 13 skipped, 2 xfailed, 0 failed |
| `ruff check` (incl. `--fix` no-op) | clean |
| `black --check` | clean |
| `mypy agentic_v2/engine agentic_v2/contracts` (strict CI form) | no issues, 26 files |

Coverage `agents/test_agent.py`: **75.96% → 97.61%**. Not run locally: UI
vitest, `agentic-v2-eval` (untouched), `just docs`.

### Follow-ups not in this PR

- `_parse_test_files` empty-`test_prefix` quirk — pinned as a characterisation
  test, needs a maintainer call (changes output filenames).
- Dead branches in the same module: `if i >= len(parts): break` cannot fire
  given `range(1, len(parts), 2)`; `convert_test_types`' non-`str` branch is
  unreachable because `TestType` subclasses `str`.
- `MockBackend.call_history` drops `temperature`/`max_tokens` (they bind to
  named params, not `**kwargs`), so no test can assert sampling params through
  it.
- `agents/implementations/` is in `[tool.coverage.run] omit` and was not swept
  for the same missing-`success` defect.

---

## Why this isn't done

Three independent blockers, none of them fixable from the agent sandbox:

1. **Stale `.git/index.lock`** (from 18:49, before this run) blocks every git
   write. The sandbox mount denies `unlink` inside `.git/` —
   `rm .git/index.lock` returns `Operation not permitted` — so I could not
   clear it. The commit failed with "Another git process seems to be running".
2. **No GitHub CLI or credentials** — `gh` is not installed, there is no
   credential helper, no `~/.git-credentials`, and no `GH_TOKEN`/`GITHUB_TOKEN`.
3. **GitHub connector not authorized.** It needs an OAuth flow, which can't run
   in a non-interactive scheduled task. Authorize it in your claude.ai connector
   settings, or via `/mcp` in an interactive session, and I can open PRs
   directly next time.

Creating the worktree also left two lock files I can't delete —
`.git/refs/heads/fix/agent-output-success-field.lock` and
`.git/worktrees/prwt/HEAD.lock`. Step 0 clears them.
