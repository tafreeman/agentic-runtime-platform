# ADR-058: Claude Subscription Backend

**Status:** Accepted
**Date:** 2026-08-19
**Related:** `agentic_v2/models/backends_claude.py`
(`ClaudeSubscriptionBackend`, `subscription_env`, `claude_sdk_available`),
`agentic_v2/models/backends.py` (`PREFIX_MAP`, `_register_cloud_backends`),
`agentic_v2/agents/implementations/claude_sdk_agent.py` (`ClaudeSDKAgent`),
`pyproject.toml` (the `claude` extra), `.github/workflows/ci.yml`
(`claude-subscription-tests`)

## Context

`_register_cloud_backends` probes each provider by **API key**:
`AnthropicBackend` is constructed only when `ANTHROPIC_API_KEY` resolves, and
its `__post_init__` raises `ValueError` without one. An operator who pays for a
**Claude subscription** rather than API credits therefore has no Claude backend
at all. `auto_configure_backend` logs "No cloud LLM provider credentials
configured" and returns an Ollama-only `MultiBackend` on a machine where the
operator is signed in to Claude and could be spending that subscription.

Subscription credentials are not an environment variable. They live in the
Claude Code CLI's own credential store, and `claude-agent-sdk` — which drives
that CLI — is the only supported way to spend them programmatically. There is no
documented wire contract for `AnthropicBackend`'s httpx client to speak instead.

The repo already declares a `claude` extra (`anthropic`, `claude-agent-sdk`) and
already ships `ClaudeSDKAgent`, a wrapper around the Agent SDK. That wrapper was
**non-functional**: it dispatched on `message.type == "result"`, but no
`claude-agent-sdk` message class carries a `.type` attribute — they are plain
dataclasses. Every call raised `AttributeError` on the first message of the run.
Its default model, `claude-opus-4-6`, was also stale.

A second defect only shows up when the two halves are combined, and it is the
one that matters most here. `agentic_v2.models.secrets` writes resolved secrets
into `os.environ`, so after `auto_configure_backend()` runs, `ANTHROPIC_API_KEY`
is set in the process. The SDK spawns the CLI with
`{**os.environ, **options.env}`. The child therefore **inherits the API key and
authenticates with it**, silently switching credential class: the call bills the
API account rather than the subscription, and fails outright when that key is
invalid or unfunded. Reproduced directly — a deliberately invalid key in
`os.environ` produced `401 API key is invalid` from a call that succeeds on the
subscription once the variable is blanked.

## Decision

**Ship `ClaudeSubscriptionBackend` behind the `claude:` prefix**, registered by
capability rather than by key.

- `claude_sdk_available()` gates registration on `claude-agent-sdk` importing,
  the same shape as `OnnxBackend`'s `_onnx_runtime_available()` probe. There is
  no credential to probe: the CLI owns resolution, and testing it here would
  mean shelling out on every registration or reading a credential store this
  module must never touch. A signed-out CLI surfaces at call time with the
  sign-in instruction.
- Registration is **additive**. `AnthropicBackend` and the `anthropic:` prefix
  are untouched, so an operator holding both a key and a subscription keeps both
  paths and chooses per call which one to spend. `claude` counts as a cloud key
  for `auto_configure_backend`'s no-cloud-provider warning, because it is one.

**Scrub the credential variables from the CLI subprocess.** `subscription_env()`
blanks `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` in `ClaudeAgentOptions.env`.
They are set to empty rather than removed because `options.env` is merged *over*
`os.environ` and so can only override, never unset; the CLI treats an empty value
as absent and falls through to the signed-in account. Caller-supplied `env`
entries are applied last, so deliberately choosing API-key billing remains
possible — it just has to be stated rather than inherited by accident.

**Fix `ClaudeSDKAgent` rather than leave a broken surface next to a working
one.** Dispatch moves to `isinstance` against the SDK dataclasses, the default
model becomes `claude-opus-5`, the same credential scrub applies, and `stream()`
is annotated and documented as yielding SDK message objects rather than the
`(type, content)` tuples its docstring claimed. Because the wrapper raised on
first use, none of this can break an existing caller.

**Surface the transport's limits instead of emulating them.**
`ClaudeAgentOptions` exposes no sampling temperature, so `temperature` is
accepted and ignored with one debug log per instance — raising would make the
backend undispatchable through `MultiBackend`, which always passes one. Tool
schemas raise instead: the Agent SDK executes its own tools rather than returning
tool calls for the runtime's registry to run, and a response with `tool_calls:
None` would read to a caller as "the model chose not to call a tool".

**Keep the extra out of the default install and close the skip blind spot.** CI
installs `dev,server,mcp,langchain,tracing`, never `claude`, so the tests
`importorskip` everywhere else — the exact failure mode that let an ADR-047
regression through on the EK side. A dedicated `claude-subscription-tests` job
installs the extra and hard-guards `import claude_agent_sdk` before running, and
`agentic_v2/models/backends_claude.py` joins the coverage `omit` list on the
same reasoning as `ek_provider.py`.

## Consequences

- An operator with only a Claude subscription gets a working cloud backend, and
  `auto_configure_backend` stops reporting no cloud provider on their machine.
- Model ids route explicitly: `claude:claude-opus-5` spends the subscription,
  `anthropic:claude-opus-5` spends the API key. The credential class is a
  property of the call, visible at the call site, not of ambient environment.
- **Sampling is not controllable on this path.** Tier routing that depends on
  temperature will not behave the same through `claude:` as through
  `anthropic:`. Use `effort` where depth matters.
- **`react_loop`-style tool dispatch is unavailable** through `claude:`. Work
  needing caller-executed tools must route to `anthropic:`.
- Subscription rate-limit windows are a new failure mode with no API-key
  analogue; a rejected window raises rather than returning empty text, so the
  router's error classification sees a failure rather than a bad answer.
- The `claude` extra carries a prerequisite pip cannot express — the Claude Code
  CLI must be installed and signed in. A missing CLI is reported with that
  instruction rather than as a transport error.
- One more CI job, and one more optional-extra surface to keep current with the
  SDK's major version.

## Alternatives considered

**Fall back to the subscription automatically under `anthropic:` when no API key
is present.** Rejected: it makes the credential class — and therefore who gets
billed — depend on ambient environment rather than on the call. A config that
worked yesterday would start spending a different account after an unrelated
`.env` edit, with nothing at the call site to show it.

**Use the `anthropic` SDK instead of `claude-agent-sdk`.** It reaches the
Messages API with full sampling and tool-schema support, which would fit
`LLMBackend` far better. But it authenticates with an API key or an
`ant auth login` profile, and neither is the subscription sign-in — it solves a
different problem. It remains the better choice if sampling parity ever matters
more than subscription reach.

**Reimplement the credential exchange over httpx, keeping one backend.**
Rejected as not possible rather than merely costly: the exchange is internal to
the CLI with no documented wire contract, so this would mean depending on a
private surface that can change without notice.

**Leave `ClaudeSDKAgent` broken and ship only the backend.** Rejected: it is the
surface an operator finds first when looking for Agent SDK support, it fails with
an `AttributeError` that suggests nothing about the cause, and it carries the
identical credential-inheritance defect.
