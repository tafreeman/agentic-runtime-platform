# No-LLM Mode

## What it does

Set `AGENTIC_NO_LLM=1` to run the native and LangChain engines without provider credentials. Both execution paths short-circuit every LLM call and return a deterministic placeholder string: `[AGENTIC_NO_LLM placeholder] Set AGENTIC_NO_LLM=0 and a provider key to get real output.` Provider probing is skipped entirely — no spurious errors from missing API keys.

## How to enable

**Bash / PowerShell:**

```bash
export AGENTIC_NO_LLM=1
agentic run test_deterministic
```

**Windows PowerShell:**

```powershell
$env:AGENTIC_NO_LLM = "1"
agentic run test_deterministic
```

Expected output: the workflow runs to completion, all steps emit placeholder text, and the process exits with status 0. No provider credentials required.

> **LangChain engine requires an extra.** The native DAG executor works with just the base `pip install -e .` — that's the common case. If you want to exercise the LangChain adapter under this flag (`--engine langchain`), install with the extra: `pip install -e .[langchain]`. Without it, `get_chat_model()` raises `ImportError: langchain-core is required...` even when the flag is set. Accepted values for the env var (case-insensitive): `1`/`true`/`yes`/`on` are true; empty/`0`/`false`/`no`/`off` are false; anything else is coerced to false with a logged warning.

The UI also works: run `agentic serve` + `npm run dev` under this flag. DAG streaming shows placeholder content at each node.

## What works

- **Native DAG executor** (both YAML workflow execution and agent-step paths)
- **LangChain adapter** (`--engine langchain` in CLI or config)
- **DAG streaming over WebSocket/SSE** (one chunk per message; the entire placeholder is a single chunk)
- **UI demos end-to-end**
- **CLI validation commands** (`agentic list` and `agentic validate` don't invoke an LLM regardless of this flag; `agentic compare` exercises workflows and honors the flag)
- **RAG pipeline** (embeddings already deterministic via SHA-256 hashing)

## Scope limits — read this before you report a bug

**Not a simulator.** The placeholder is a fixed string. Any downstream consumer that parses structured output — `PydanticOutputParser`, JSON-extraction steps, evaluation rubrics that score against a reference — will fail or score zero. This is by design. Use this mode for shape and flow testing only, not for semantics or behavior validation.

**Evaluation runs need real keys.** `agentic-v2-eval` is untouched; scoring rubrics against the placeholder will score zero. Run evaluation workflows with actual provider credentials.

**Streaming is not token-by-token.** Both `complete_stream` (native) and `astream` (LangChain) yield the entire placeholder as one chunk. Useful for testing UI plumbing, not for testing per-token streaming UX.

**Tool-calling is a no-op.** `bind_tools(...)` is accepted but ignored. The placeholder is returned regardless of what tools were bound. Workflows that branch on tool calls will always take the no-tool path.

## When NOT to use

- Production deployments
- Evaluation and rubric-scoring runs
- Capacity planning or load tests
- Anything asserting on real model content or behavior

## Troubleshooting

**I set the var but got "GITHUB_TOKEN environment variable is required"**

The `get_settings` function uses `@lru_cache`. The flag must be set before the first call to `get_settings()` in a process. For CLI users, this is automatic (fresh process). For long-running sessions (e.g., interactive notebooks), call:

```python
from agentic_v2.settings import get_settings
from agentic_v2.models.client import reset_client

get_settings.cache_clear()
reset_client()
```

Then set your env var and proceed.

**The placeholder isn't showing in the UI**

Check your browser's Network tab or console for `/api/runs/{run_id}/stream` and `/ws/execution/{run_id}` events. The string `[AGENTIC_NO_LLM placeholder]` will appear in each node's output field in the DAG.

**Can I make it fail instead of returning a placeholder?**

No. The flag is for graceful no-op, not for hard errors. If you want to enforce a provider key, unset the flag and let the provider's missing-credential `ValueError` surface.
