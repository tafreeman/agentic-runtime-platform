# Providers and compute options explored

[Kit](../README.md) · [Docs](README.md) — **reference**, not campaign-specific. Everything found while
looking for a model-serving backend that isn't Ollama Cloud's quota, written so the next session
doesn't re-discover the same dead ends.

This grew out of the SWE-bench A/B campaign hitting Ollama Cloud's weekly/session caps repeatedly.
None of the code here (the `build_*_model` functions in `agentic_v2/langchain/model_builders.py`,
the `_OWN_CREDENTIALS_BY_PREFIX` exemption in `run_ab.py`) is swe_ab-specific — it's now real ARP
infrastructure any future eval effort can reuse, regardless of which benchmark it targets.

---

## 1. Ollama Cloud — the original SUT provider

**What it is:** `ollama:<model>:cloud` (or a date-suffixed cloud tag like `:0731-cloud`) routes to
Ollama's hosted cloud models, distinct from a locally-pulled model of the same base name.

**Quotas, confirmed from the account's own dashboard (`ollama.com` → Cloud usage):**
- **Session usage** — short window, observed reset ~hourly-ish (dashboard showed "resets in 1-2
  hours" at different checks).
- **Weekly usage** — resets on a ~7-day cycle ("resets in N days" / "resets in 12 hours" near the
  boundary).
- Usage is **token-metered per model, not request-counted** — confirmed via `ollama.com/pricing`.
  Each model has its own $/1M-token input/output rate; a bigger model burns the same quota faster
  per call, not just per token, since it also generates more tokens per response.
- **Measured per-token rates** (input / output, $ per 1M tokens): `deepseek-v4-flash` $0.44/$1.32
  (this campaign's baseline SUT model) · `glm-5.3` $1.40/$4.40 (~3.2-3.3x baseline) ·
  `glm-5.3-flash` $0.15/$0.50 (~0.34-0.38x baseline, *cheaper* than the SUT model) · `minimax-m3`
  $0.60/$2.40 · `nemotron-3-ultra` $0.10/$3.00 (cheap input, expensive output) · `kimi-k2.7-code`
  $0.95/$4.00.
- **Exact cloud tags are not the bare model name.** `ollama:glm-5.3` 404s outright; the real tag
  (`glm-5.3:cloud`) has to be found via `ollama.com/library/<model>/tags` (scraped with
  `curl ... | grep -oE 'modelname:[a-zA-Z0-9._-]+'`) — there's no API that resolves this cleanly.
- **Per-model concurrent-slot limits are real and independent of account quota.** `glm-5.3:cloud`
  at `--concurrency 4` returned `429: timed out waiting for a concurrent request slot` on 122/204
  arm-A samples and 204/204 on arm B (3x the calls per sample at the same concurrency compounded
  it) — `deepseek-v4-flash:0731-cloud` ran concurrency 4 the entire campaign with no such failure.
  Dropping to `--concurrency 1` avoided the 429 but then hit the **session** usage cap on the very
  first batch instead (bigger model, same call volume, faster quota burn per the pricing above).
- **Throttling can happen with quota still available.** `glm-5.3-flash:cloud` ran ~23 hours at
  concurrency 4 with zero errors, but the account's own usage dashboard showed only **39 requests**
  logged in that entire window — session usage sitting at 21.8%, nowhere near exhausted. Verified
  via `py-spy dump --pid <pid> --locals` that this wasn't a hung process (fresh `bridge.py`
  subprocesses were spawning every few minutes, non-zero CPU) — requests were genuinely being
  served, just paced extremely slowly server-side. Stopped; no usable data produced.
- **A fingerprint change mid-campaign was first read as a live model update.** It was the
  campaign's own `bridge.py` changing between two waves (EVIDENCE.md §2.21, corrected
  2026-09-02) — `target_fingerprint` hashes the harness and the model id, not the served
  weights. Whether Ollama updates the weights behind a cloud tag is unverified and, so far,
  unrecordable by the kit.

**Verdict:** fine for the SUT model specifically (which is genuinely cheap and was never
concurrent-slot-limited), unreliable for anything else tried — every other Ollama Cloud model
attempted this session hit either the concurrent-slot limit, the session cap, or silent
throttling.

---

## 2. NVIDIA NIM

**What it is:** `nvidia:<publisher>/<model>` via `integrate.api.nvidia.com`, OpenAI-compatible.
Free tier for several models including `deepseek-ai/deepseek-v4-flash-0731` and
`nvidia/nemotron-3-super-120b-a12b`.

**Findings:**
- Small-scale (16-instance) test: clean, tied result (A 50.0%, B 50.0%).
- Large-scale (204-instance backfill) attempt: **103/204 (50.5%) timed out** after 8+ hours on arm
  A alone. Verified genuinely still working (not hung) the same way as the glm-5.3-flash case
  above — the free endpoint was severely degraded under real load, not the small-scale test's
  behavior at scale.
- `nemotron-3-super-120b-a12b`'s real coding/agentic benchmark score (37.7 coding / 8.8 agentic,
  from OpenRouter's benchmarks API — see §4) is weak despite looking fast on a trivial "reply OK"
  probe (0.76s) — that probe wasn't representative of real generation load, and a fast trivial
  response doesn't predict real-task capability.
- `NVIDIA_API_KEY` needed a real fix in `run_ab.py`: `PAID_CREDENTIALS` blanks it unconditionally
  (written under the assumption NVIDIA only ever appears as an unwanted fallback), which breaks
  the primary call when NVIDIA *is* the model under test. See §5's `_OWN_CREDENTIALS_BY_PREFIX`
  fix.

**Verdict:** fine for a small probe, not reliable at real campaign scale.

---

## 3. OpenRouter

**What it is:** `openrouter:<publisher>/<model>[:free]`, OpenAI-compatible, huge model catalog
including a genuinely free tier.

**Full free-tier list found** (`GET https://openrouter.ai/api/v1/models`, filtered to
`:free`-suffixed or zero-priced): `cohere/north-mini-code`, `dots-studio/dots-3-note-preview`,
`google/gemma-4-26b-a4b-it`, `google/gemma-4-31b-it`, `google/lyria-3-*` (music, not code),
`inclusionai/ling-3.0-flash-fin`, `liquid/lfm-2.5-2.6b`, `minimax/minimax-m2.7`,
`minimax/minimax-m3`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`,
`nvidia/nemotron-3-super-120b-a12b`, `nvidia/nemotron-3-ultra-550b-a55b`,
`nvidia/nemotron-3.5-content-safety`, `nvidia/nemotron-3.5-lightning`, `openrouter/free`,
`poolside/laguna-s-2.1`, `poolside/laguna-xs-2.1`, `thinkingmachines/inkling[-small]`,
`z-ai/glm-5.2`.

**Real coding/agentic benchmark scores** for these, pulled from OpenRouter's own
`GET /v1/benchmarks?task_type=coding&source=artificial-analysis` (undocumented but real and
working with any OpenRouter key) — full table is worth re-pulling fresh since scores update, but
at research time: `glm-5.2` 68.8/45.7 (coding/agentic) was the strongest free-tier score found,
ahead of `minimax-m3` 58.6/36.1, well ahead of `nemotron-3-ultra` 49.3/27.5 and
`nemotron-3.5-lightning` 26.8/13.8. `cohere/north-mini-code` — despite the name — scored weakest
of everything tested (36.5/3.1): fast (1.57s latency) but not capable.

**What actually worked vs. didn't, tried live:**
- `glm-5.2:free` — **persistently rate-limited** on OpenRouter's shared free pool (`429: ...
  temporarily rate-limited upstream`), confirmed not transient (4 retries with 8s backoff, all
  failed). The score is real; the free-pool capacity for it isn't usable at this campaign's scale.
- `thinkingmachines/inkling[-small]:free` — **403, "only available on agentic harnesses"**. Not
  reachable via plain chat completions at all, regardless of scale.
- `minimax-m3:free` and `minimax-m2.7:free` — **worked cleanly**. `minimax-m3` ran a full
  204-instance x 2-arm batch with only 5 and 8 non-verdicts respectively (mostly errors/timeouts,
  no rate-limiting at all). This is the best-proven fast+capable option found this whole session —
  see the SWE-bench campaign's own EVIDENCE.md §1.9 for the real result (A 29.7%, B 26.0%
  verdict-only, McNemar p=0.4188, n=192).
- `google/gemma-4-31b-it:free` — 429 immediately on a single sanity probe, untested at scale.
- `nvidia/nemotron-3-ultra-550b-a55b:free` — **404, "no endpoints available matching your
  guardrail restrictions"** — a different failure class again, not simple rate-limiting.

**Verdict:** the free tier is real but per-model capacity varies wildly and isn't documented
anywhere — has to be probed live before committing to a batch. `minimax-m3` is the one proven
reliable pick.

---

## 4. OpenRouter's Benchmarks API — genuinely useful, undocumented in the main API reference

`GET https://openrouter.ai/api/v1/benchmarks` (needs any valid OpenRouter key). Query params:
`source` (`artificial-analysis` / `design-arena` / `openrouter`), `task_type` (`coding` /
`intelligence` / `agentic` / `search`), `max_results`. Returns real `coding_index` /
`agentic_index` / `intelligence_index` numbers per model, sourced from Artificial Analysis's own
evaluation. This is how every "real benchmark score" cited in this document and in the SWE-bench
campaign's own EVIDENCE.md §1.9/§2.22 was actually obtained — worth reusing for any future model
comparison rather than re-deriving from scratch, and worth re-querying fresh since scores move.

---

## 5. DigitalOcean — three distinct products, easy to conflate

DigitalOcean fronts AMD's GPU cloud program ("AMD Developer Cloud" is a white-labeled DO portal at
`devcloud.amd.com`, backed by the same DO API — `curl -H "Authorization: Bearer $DIGITALOCEAN_TOKEN"
https://api.digitalocean.com/v2/account` returns the real account, team "My AMD Team"). Three
separate products live under this one account, with **separate billing pools that don't share
credit**:

### 5a. Serverless Inference (`inference.do-ai.run`)

OpenAI-compatible, `https://inference.do-ai.run/v1/chat/completions`, `Authorization: Bearer
$DIGITALOCEAN_TOKEN`. Model catalog (`GET /v1/models`) is huge and directly relevant: includes
**`deepseek-v4-flash-0731`** (this campaign's own SUT model, served by a different infrastructure
entirely), `glm-5.3`, `glm-5.3-flash`, `glm-5.2`, `glm-5.1`, `kimi-k2.5/k2.6/k3`, `qwen3.8-max`,
`qwen3.5-397b-a17b`, `nemotron-3-ultra-550b`, `nvidia-nemotron-3-super-120b`,
`openai-gpt-oss-120b/20b`, plus commercial Anthropic/OpenAI models passed through at their own
provider rates.

**Critical finding: the $100 AMD credit does NOT fund this.** Per DigitalOcean's own pricing docs:
*"Serverless inference is prepaid only. You must maintain a positive prepaid account balance...
If your balance reaches $0, access is suspended."* This prepaid balance is a **separate pool**
from the AMD GPU credit — confirmed two ways: (1) `GET /v2/customers/my/balance` showed
`account_balance: "0.00"` even while test calls were succeeding (some small grace/trial
allowance), and (2) once that ran out, a follow-up call returned a clean
`{"id":"Payment Required","message":"You are not allowed to perform this operation"}` — failed
safely, no charge, but confirmed blocked. The GPU Droplet creation page states this explicitly:
*"AMD credit only covers GPU access. All other services would be charged to your payment
method."* **Do not assume the AMD credit applies here without adding a real prepayment first.**

Integration: added as a proper ARP provider this session — `build_digitalocean_model` in
`agentic_v2/langchain/model_builders.py`, `"digitalocean:"` prefix registered in
`agentic_v2/langchain/models.py`, credential handling in `run_ab.py` (see §5c). Verified working
end-to-end against `deepseek-v4-flash-0731` and `glm-5.3` before the balance ran out — one
transient `429 Platform overloaded`, succeeded on retry.

### 5b. GPU Droplets — where the $100 AMD credit actually applies

Real dedicated GPU VMs. **This is what the AMD credit is scoped to** — confirmed on the Create
GPU Droplet page: *"These GPU plans use your AMD GPU credits. You have $100.00 credit expiring
[Sept 30, 2026]."*

- **MI300X**: 192GB VRAM, 20 vCPU, 240GB RAM, **$1.99/GPU/hr** (this AMD-portal rate, cheaper than
  the $2.59/hr general DO public rate found earlier via web search — check current pricing before
  relying on either number).
- **Billing is genuinely per-second**, not hourly blocks: confirmed via DO's docs — "billed per
  second with a minimum charge of 60 seconds or $0.01, whichever is higher." $100 buys ~50 hours
  of *actual* usage time at the MI300X single-GPU rate, not 50 one-hour minimums.
- **Bills while powered off — only stops on destroy.** Real ongoing-cost risk if left running
  idle; needs active lifecycle management.
- **Pre-baked Quick Start images relevant to this use case**: `vLLM` 0.27.1 (high-throughput
  OpenAI-compatible serving, ROCm-ready) and `SGLang` 0.5.14 — either would let one droplet serve
  any downloaded model at real GPU speed with minimal setup. A `Kimi K3` image ships with weights
  already baked in (no download step, OpenAI-compatible API up on first boot).
- **Grading could theoretically move here too** (20 vCPU/240GB RAM is plenty for Docker), but
  there's no real driver to do so — local Docker/CPU were never the bottleneck in this campaign
  (§2.14 in the SWE-bench EVIDENCE.md measured ~18% host CPU under concurrent grading). Would only
  matter for a fully hands-off remote pipeline, not for performance.

**Status: not yet created.** Explicitly held off pending direct user confirmation (real, ongoing
per-second billing against a real credit) — see the SWE-bench campaign's own session log for the
decision point.

### 5c. Account plumbing that matters for any future provider integration

- `DIGITALOCEAN_TOKEN` — Personal Access Token, `read`+`write` scope, named "amd" in this account.
  DigitalOcean's own docs use exactly this variable name in their auth examples, so it was adopted
  verbatim rather than inventing a new convention.
- Added to `PAID_CREDENTIALS` in `run_ab.py` (real billing exposure, same reasoning as NVIDIA/
  OpenRouter) with a matching `_OWN_CREDENTIALS_BY_PREFIX` exemption so it isn't blanked when
  DigitalOcean is the pinned model under test — see that file's own comments for why this pairing
  is only safe in combination with `bridge.py`'s fallback-exclusivity patch (no other model can
  ever be reached in the same run regardless of which credentials are present).
- **No backup payment method on file** (confirmed on the billing page) — reduces risk of an
  unexpected real charge beyond whatever primary method/credit is configured, since there's no
  fallback for DigitalOcean to charge if the primary fails.

---

## 6. Local compute (this machine)

**Hardware:** AMD Ryzen AI 9 HX 370, integrated Radeon 890M, 88GB shared system RAM (no discrete
GPU). Ollama reports the full model size as `size_vram` when loaded, confirming the iGPU's shared
memory pool is actually engaged, not silently falling back to pure CPU.

**Ollama, locally pulled models:** `nemotron-3.5-lightning:latest` (25.4GB, 30B MoE / 3B active)
was the one real, non-embedding, usefully-sized model already on disk. Cold load: ~50s (mostly
disk I/O, one-time). **Warm** inference: 0.55s total for a trivial prompt, ~0.13s of that actual
generation — genuinely fast once resident, because MoE architecture only computes through the
active 3B slice per token regardless of the 33B total size. Real coding benchmark score is weak
(26.8/13.8, matches the OpenRouter-hosted version of the same model), but it has **zero external
quota risk** — pure local compute, no rate limits, no billing.

**LM Studio:** also installed and running (`lms.exe` CLI at `~/.lmstudio/bin/`), server on port
**12340** (not the commonly-assumed default 1234). Has its own separate local model library —
`qwen/qwen3.8-27b` (17.7GB, dense not MoE) was tested: loaded in 44s, but generation speed was
**~5 tokens/sec steady-state** — far too slow for a real campaign (a real SWE-bench-style
repair generating 500-3000+ tokens would take minutes per sample, ~20+ hours for arm A alone at
204 instances). The gap vs. nemotron-3.5-lightning isn't about LM Studio vs. Ollama as tools —
it's dense-vs-MoE architecture: qwen3.8-27b fires all 27B parameters every token; nemotron only
fires its active 3B. **Architecture matters more than benchmark score for local viability without
a discrete GPU.**

**LM Link** (LM Studio's remote-device feature, `lms link status`/`enable`): enabled on this
device, account shows "Online," but **0 remote devices connected** at research time — the user
mentioned a second physical machine (backup laptop, Snapdragon X Elite chip, less RAM) that could
theoretically pair via this same feature, but it wasn't online/linked during this session. Would
need LM Studio running there too, signed into the same account, before it's usable.

**Verdict:** local is a legitimate zero-quota fallback, but only for MoE-architecture models with
a small active-parameter count. Dense models of any real size are impractical on this hardware.

---

## 7. Net assessment — what to actually use

Ranked by proven fast + capable + reliable, based on real completed runs (not probes) this
session:

1. **`minimax-m3` via OpenRouter** — the only model tried at full 204-instance scale that produced
   a clean result with no rate-limiting, no throttling, no timeouts pile-up. Weaker real
   capability than the SUT model (29.7% vs. 51-58% verdict-only pass rate), but the infrastructure
   is genuinely trustworthy.
2. **`deepseek-v4-flash:0731-cloud` via Ollama** — the original SUT model, reliable specifically
   because it's cheap ($0.44/$1.32 per 1M tokens) and was never concurrent-slot-limited, but
   shares Ollama's account-wide weekly/session quota with whatever else the account is doing.
3. **Local `nemotron-3.5-lightning`** — zero quota risk, works today, but weak real capability
   (26.8 coding index) and MoE-only viability on this hardware.
4. **DigitalOcean GPU Droplet + vLLM** — highest ceiling (real dedicated GPU, any model, no
   throttling), but not yet created, and burns a real, expiring ($100, Sept 30 2026), non-refundable
   credit that only applies to this specific product.
5. Everything else tried this session (NIM at scale, GLM-5.2/5.3/5.3-flash via Ollama or
   OpenRouter, DigitalOcean Serverless Inference) either failed outright or degraded too badly to
   trust — see §1-3 above for the specific failure mode of each before retrying any of them.
