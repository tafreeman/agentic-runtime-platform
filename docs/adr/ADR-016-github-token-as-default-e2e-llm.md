# ADR-016: GitHub Models via `GITHUB_TOKEN` as Default E2E LLM Provider

**Status:** Accepted
**Date:** 2026-04-22
**Related:** Epic 2 (Observable Execution), Epic 6 (Evaluation & Data Depth)

---

## Context

Every CI job that exercises the platform end-to-end — Playwright streaming 5×, nightly reliability 50×, evaluation runs in `eval-package-ci.yml`, prompt quality gates, performance benchmarks — needs a working LLM provider. Without one, the workflows either skip the interesting code path or fail at the model call.

The candidate providers we consider in CI:

| Provider | Credential shape | Cost model | Rate limit |
|----------|-----------------|-----------|------------|
| OpenAI | `OPENAI_API_KEY` | Paid per token | Tier-based per account |
| Anthropic | `ANTHROPIC_API_KEY` | Paid per token | Tier-based per account |
| Google Gemini | `GEMINI_API_KEY` | Free tier + paid | Aggressive rate limits on free tier |
| Azure OpenAI | `AZURE_OPENAI_API_KEY_*` | Paid | Per-deployment |
| GitHub Models | `GITHUB_TOKEN` | Free for GitHub users, with daily cap | Daily quota |
| Ollama / local ONNX | none | CPU/RAM only | None |

For open-source CI — where every contributor PR must run against the same gates — we need a provider that:

1. **Requires no secret management for contributors.** Maintainer-owned secrets are fine; forks cannot read them.
2. **Costs nothing to operate.** Real LLM costs on a CI pipeline that runs 50× nightly plus every PR would accumulate fast.
3. **Covers enough model variety** that tier-routing code paths actually exercise.

Ollama and local ONNX satisfy 1 and 2 but not 3 on GitHub-hosted runners — the runner CPU budget is insufficient for tier-2+ model latency expectations without aggressive timeouts that themselves become a flake source.

---

## Decision

Use **GitHub Models via `GITHUB_TOKEN`** as the **default LLM provider for all CI-executed end-to-end paths.**

- `GITHUB_TOKEN` is automatically available on GitHub-hosted runners in workflows checked out from any branch on this repo.
- The SmartModelRouter is configured to prefer `gh:*` model identifiers when a live `GITHUB_TOKEN` is present.
- Tier-3 workflows route to `gh:gpt-4o`; tier-1 / tier-2 route to `gh:gpt-4o-mini`. Both are in the GitHub Models catalogue as of 2026-04.
- Local developers who want to run the same gates locally can set a personal-access token with `read:org` and export it as `GITHUB_TOKEN`.

Forks that do not receive `GITHUB_TOKEN` fall back to deterministic (tier-0) workflows plus a skip-set for the LLM-dependent jobs. PRs from forks that touch LLM-dependent code cannot fully validate in fork CI — maintainers re-run the job against the base branch after review.

---

## Consequences

### Positive

- Zero out-of-pocket LLM cost for the repo maintainer.
- No contributor needs an OpenAI or Anthropic key to land a PR.
- GitHub Models covers `gpt-4o`, `gpt-4o-mini`, and Phi / Llama variants — enough model surface that router fallback paths are genuinely tested.
- `GITHUB_TOKEN` is scoped to the workflow run — no long-lived credential to rotate.

### Negative

- **Provider outages break CI.** GitHub Models rate-limit events, maintenance windows, and model retirements cascade into "CI is red" with no code change. Has happened. See [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §3.1.
- **Daily quota ceiling.** Running the platform end-to-end ~100× per day (every PR push + nightly 50×) approaches the daily cap. We rely on the cap being generous; a tightening would force us to revisit.
- **Fork CI is asymmetric.** A contributor's PR in their fork runs a subset of gates; maintainers re-run against the base branch. This is a workflow cost, not a technical blocker.
- **Vendor coupling.** The platform officially supports 8+ providers; CI validates only one. Regressions in Anthropic or Gemini backends are caught only by local dev testing or by a paying customer.
- **Not suitable for restricted or offline deployments.** Regulated deployments can use Azure OpenAI, on-prem providers, or other approved backends; the CI choice is an open-source pragma, not a statement of intended production posture.

### Mitigations in place

- Provider-specific unit tests run with mocked backends — a Gemini-specific bug caught by unit tests does not need GitHub Models to validate.
- Tier-0 (`test_deterministic`) is the only guaranteed-green workflow — used for smoke tests where LLM availability cannot be assumed.
- The router's circuit-breaker pattern means a GitHub Models outage degrades gracefully rather than crashing — though CI still fails because the gate expects a successful run.

---

## Alternatives considered

- **Paid OpenAI + maintainer secret.** Rejected because cost is non-trivial at nightly 50× cadence and forks still cannot access the secret.
- **Mocked LLM with recorded responses.** Considered for the deterministic fixture work (see `test(golden): add deterministic golden-output regression test`, commit `a6ffeba`). Used for specific regression tests but not extensible to the full streaming surface.
- **Self-hosted Ollama runner.** Viable but introduces runner-fleet maintenance burden.
- **Azure OpenAI via maintainer secret.** Works for maintainer runs; does not solve the fork asymmetry.

---

## Review cadence

Re-evaluate when:

- GitHub Models tightens the daily quota in a way that breaks nightly cadence.
- GitHub Models is deprecated or materially re-priced.
- A separate hermetic-mock provider is built (Sprint B candidate — see ROADMAP).
- The platform gets a paying production deployment that is willing to fund a proper provider for CI.

---

## Implementation references

- Token provisioning: `.github/workflows/*.yml` — every job that references `GITHUB_TOKEN` in `env:`.
- Router configuration: `agentic-workflows-v2/agentic_v2/models/smart_router.py` and `backends.py` (the `gh:*` provider prefix).
- Fork-skip logic: job-level `if: secrets.GITHUB_TOKEN != ''` guards in relevant workflows.
