"""
Model registry — all available LLM providers, models, and rate limits.

Auto-discovered May 2026. Update by running: python -m tools.llm.model_probe --discover --force

Usage:
    from tools.llm.model_registry import REGISTRY, working_models, models_by_capability

    for provider, info in working_models().items():
        print(provider, info["base_url"])

    chat_models = models_by_capability("chat")
"""

from __future__ import annotations

from typing import TypedDict

# ─────────────────────────────────────────────────────────────────────────────
# Type schema
# ─────────────────────────────────────────────────────────────────────────────

class RateLimit(TypedDict, total=False):
    rpm: int | None        # requests per minute
    tpm: int | None        # tokens per minute
    rpd: int | None        # requests per day
    tpd: int | None        # tokens per day
    note: str


class ModelEntry(TypedDict, total=False):
    id: str                # API model id (pass directly to provider)
    capability: str        # chat | embed | vision | code | tts | image | rerank | safety
    status: str            # working | billing_needed | rpm_exhausted | no_deployments | trial
    context_k: int | None  # context window in K tokens (where known)
    rate_limit: RateLimit
    note: str


class ProviderEntry(TypedDict, total=False):
    base_url: str
    auth_env: str          # env var(s) for API key (comma-sep if multiple)
    status: str            # working | billing_needed | no_deployments
    models: list[ModelEntry]
    note: str


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

REGISTRY: dict[str, ProviderEntry] = {

    # ── GitHub Models ─────────────────────────────────────────────────────────
    # Two GitHub accounts configured → double per-account quota
    # Endpoint: still on deprecated Azure domain (sunset Oct 2025, still live May 2026)
    # New domain github.models.ai not yet reachable via Python urllib (SSL SNI issue)
    "github_models": {
        "base_url": "https://models.inference.ai.azure.com",
        "auth_env": "GITHUB_TOKEN,GITHUB_TOKEN_0",
        "status": "working",
        "note": "Model inventory includes current OpenAI, reasoning, and local-provider candidates.",
        "models": [
            # ── OpenAI via GitHub ───────────────────────────────────────────────
            {"id": "openai/gpt-4o-mini",        "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 20_000, "tpm": 2_000_000,  "note": "per account"}},
            {"id": "openai/gpt-4o",             "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 60_000, "tpm": 10_000_000, "note": "per account"}},
            {"id": "openai/gpt-4.1",            "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "openai/gpt-4.1-mini",       "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "openai/gpt-4.1-nano",       "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "openai/gpt-5",              "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "openai/gpt-5-chat",         "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "openai/gpt-5-mini",         "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "openai/gpt-5-nano",         "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "openai/o1",                 "capability": "chat",  "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            {"id": "openai/o1-mini",            "capability": "chat",  "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            {"id": "openai/o1-preview",         "capability": "chat",  "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            {"id": "openai/o3",                 "capability": "chat",  "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            {"id": "openai/o3-mini",            "capability": "chat",  "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            {"id": "openai/o4-mini",            "capability": "chat",  "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            # ── Meta Llama via GitHub ───────────────────────────────────────────
            {"id": "meta/meta-llama-3.1-8b-instruct",              "capability": "chat",   "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "meta/meta-llama-3.1-405b-instruct",            "capability": "chat",   "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "meta/llama-3.3-70b-instruct",                  "capability": "chat",   "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "meta/llama-4-maverick-17b-128e-instruct-fp8",  "capability": "chat",   "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "meta/llama-4-scout-17b-16e-instruct",          "capability": "chat",   "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "meta/llama-3.2-11b-vision-instruct",           "capability": "vision", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "meta/llama-3.2-90b-vision-instruct",           "capability": "vision", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            # ── Microsoft via GitHub ────────────────────────────────────────────
            {"id": "microsoft/phi-4",                    "capability": "chat",   "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "microsoft/phi-4-mini-instruct",      "capability": "chat",   "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "microsoft/phi-4-mini-reasoning",     "capability": "chat",   "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            {"id": "microsoft/phi-4-reasoning",          "capability": "chat",   "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            {"id": "microsoft/phi-4-multimodal-instruct","capability": "vision", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "microsoft/mai-ds-r1",                "capability": "chat",   "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            # ── Mistral via GitHub ──────────────────────────────────────────────
            {"id": "mistral-ai/mistral-small-2503",   "capability": "chat", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "mistral-ai/mistral-medium-2505",  "capability": "chat", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "mistral-ai/ministral-3b",         "capability": "chat", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "mistral-ai/codestral-2501",       "capability": "code", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            # ── DeepSeek via GitHub ─────────────────────────────────────────────
            {"id": "deepseek/deepseek-r1",       "capability": "chat", "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            {"id": "deepseek/deepseek-r1-0528",  "capability": "chat", "status": "working",
             "rate_limit": {"note": "reasoning; free tier applies"}},
            {"id": "deepseek/deepseek-v3-0324",  "capability": "chat", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            # ── xAI via GitHub ──────────────────────────────────────────────────
            {"id": "xai/grok-3",      "capability": "chat", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "xai/grok-3-mini", "capability": "chat", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            # ── Cohere / AI21 via GitHub ────────────────────────────────────────
            {"id": "cohere/cohere-command-a",              "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "cohere/cohere-command-r-08-2024",      "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "cohere/cohere-command-r-plus-08-2024", "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "ai21-labs/ai21-jamba-1.5-large",       "capability": "chat",  "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            # ── Legacy embed via GitHub (from previous registry) ────────────────
            {"id": "text-embedding-3-small",          "capability": "embed", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "text-embedding-3-large",          "capability": "embed", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "Cohere-embed-v3-english",         "capability": "embed", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
            {"id": "Cohere-embed-v3-multilingual",    "capability": "embed", "status": "working",
             "rate_limit": {"note": "free tier applies"}},
        ],
    },

    # ── Gemini (Google) ───────────────────────────────────────────────────────
    # 4 keys: GEMINI_API_KEY + GEMINI_API_KEY_2 working; _0 and _1 hit RPM (reset ~1 min)
    # Free tier limits are per-key; 2 working keys = 2x capacity
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "auth_env": "GEMINI_API_KEY,GEMINI_API_KEY_0,GEMINI_API_KEY_1,GEMINI_API_KEY_2",
        "status": "working",
        "note": "2/4 keys active (KEY_0 + KEY_1 hit RPM, auto-reset ~49s). 50 models including Gemini 3.x, Veo 3.1, Imagen 4, Lyria 3.",
        "models": [
            # ── Flash (workhorse) ──────────────────────────────────────────────
            {"id": "gemini-2.5-flash",          "capability": "chat",  "status": "working", "context_k": 1048,
             "rate_limit": {"rpm": 10, "tpm": 250_000, "rpd": 500}},
            {"id": "gemini-2.5-flash-lite",     "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 30, "tpm": 1_000_000, "rpd": 1500}},
            {"id": "gemini-2.0-flash",          "capability": "chat",  "status": "working", "context_k": 1048,
             "rate_limit": {"rpm": 15, "tpm": 1_000_000, "rpd": 1500}},
            {"id": "gemini-2.0-flash-001",      "capability": "chat",  "status": "working", "context_k": 1048,
             "rate_limit": {"rpm": 15, "tpm": 1_000_000, "rpd": 1500}},
            {"id": "gemini-2.0-flash-lite",     "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 30, "tpm": 1_000_000, "rpd": 1500}},
            {"id": "gemini-2.0-flash-lite-001", "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 30, "tpm": 1_000_000, "rpd": 1500}},
            {"id": "gemini-3.1-flash-lite",     "capability": "chat",  "status": "working",
             "rate_limit": {"note": "preview; limits not published"}},
            {"id": "gemini-3.1-flash-lite-preview", "capability": "chat", "status": "working",
             "rate_limit": {"note": "preview; limits not published"}},
            {"id": "gemini-3.5-flash",          "capability": "chat",  "status": "working",
             "rate_limit": {"note": "preview; limits not published"}},
            {"id": "gemini-flash-latest",       "capability": "chat",  "status": "working",
             "rate_limit": {"note": "alias; same limits as current flash"}},
            {"id": "gemini-flash-lite-latest",  "capability": "chat",  "status": "working",
             "rate_limit": {"note": "alias; same limits as current flash-lite"}},
            # ── Pro ────────────────────────────────────────────────────────────
            {"id": "gemini-2.5-pro",            "capability": "chat",  "status": "working", "context_k": 1048,
             "rate_limit": {"rpm": 5, "tpm": 100_000, "rpd": 25}},
            {"id": "gemini-3-pro-preview",      "capability": "chat",  "status": "working",
             "rate_limit": {"note": "preview; limits not published"}},
            {"id": "gemini-3.1-pro-preview",    "capability": "chat",  "status": "working",
             "rate_limit": {"note": "preview; limits not published"}},
            {"id": "gemini-3.1-pro-preview-customtools", "capability": "chat", "status": "working",
             "rate_limit": {"note": "preview with custom tools"}},
            {"id": "gemini-pro-latest",         "capability": "chat",  "status": "working",
             "rate_limit": {"note": "alias; same limits as current pro"}},
            # ── Flash experimental / preview ────────────────────────────────────
            {"id": "gemini-3-flash-preview",    "capability": "chat",  "status": "working",
             "rate_limit": {"note": "preview; limits not published"}},
            {"id": "gemini-2.5-computer-use-preview-10-2025", "capability": "chat", "status": "working",
             "note": "computer-use capability"},
            {"id": "deep-research-preview-04-2026",     "capability": "chat", "status": "working",
             "note": "research/web-grounded"},
            {"id": "deep-research-pro-preview-12-2025", "capability": "chat", "status": "working",
             "note": "research/web-grounded"},
            {"id": "deep-research-max-preview-04-2026", "capability": "chat", "status": "working",
             "note": "research/web-grounded"},
            {"id": "antigravity-preview-05-2026", "capability": "chat", "status": "working",
             "note": "preview model May 2026"},
            {"id": "nano-banana-pro-preview",   "capability": "chat",  "status": "working",
             "note": "preview model"},
            # ── Gemma ──────────────────────────────────────────────────────────
            {"id": "gemma-4-31b-it",           "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 30, "tpm": 1_000_000, "rpd": 1500}},
            {"id": "gemma-4-26b-a4b-it",       "capability": "chat",  "status": "working",
             "rate_limit": {"note": "preview; limits not published"}},
            # ── Robotics ──────────────────────────────────────────────────────
            {"id": "gemini-robotics-er-1.5-preview", "capability": "chat", "status": "working",
             "note": "robotics/embodied reasoning"},
            {"id": "gemini-robotics-er-1.6-preview", "capability": "chat", "status": "working",
             "note": "robotics/embodied reasoning"},
            # ── Embedding ──────────────────────────────────────────────────────
            {"id": "gemini-embedding-001",           "capability": "embed", "status": "working",
             "rate_limit": {"rpm": 5, "tpm": 100_000}},
            {"id": "gemini-embedding-2-preview",     "capability": "embed", "status": "working",
             "rate_limit": {"note": "preview"}},
            {"id": "gemini-embedding-2",             "capability": "embed", "status": "working",
             "rate_limit": {"note": "latest; limits not published"}},
            {"id": "aqa",                            "capability": "embed", "status": "working",
             "note": "attributed question answering"},
            # ── Vision / Image ──────────────────────────────────────────────────
            {"id": "gemini-2.5-flash-image",         "capability": "vision", "status": "working",
             "rate_limit": {"note": "preview"}},
            {"id": "gemini-3-pro-image-preview",     "capability": "vision", "status": "working",
             "note": "image generation + understanding"},
            {"id": "gemini-3.1-flash-image-preview", "capability": "vision", "status": "working",
             "note": "image generation"},
            {"id": "imagen-4.0-generate-001",        "capability": "image",  "status": "working",
             "note": "Imagen 4"},
            {"id": "imagen-4.0-ultra-generate-001",  "capability": "image",  "status": "working",
             "note": "Imagen 4 Ultra"},
            {"id": "imagen-4.0-fast-generate-001",   "capability": "image",  "status": "working",
             "note": "Imagen 4 Fast"},
            # ── Video (Veo) ────────────────────────────────────────────────────
            {"id": "veo-2.0-generate-001",           "capability": "video",  "status": "working",
             "note": "Veo 2 video gen"},
            {"id": "veo-3.0-generate-001",           "capability": "video",  "status": "working",
             "note": "Veo 3 video gen"},
            {"id": "veo-3.0-fast-generate-001",      "capability": "video",  "status": "working",
             "note": "Veo 3 fast"},
            {"id": "veo-3.1-generate-preview",       "capability": "video",  "status": "working",
             "note": "Veo 3.1 preview"},
            {"id": "veo-3.1-fast-generate-preview",  "capability": "video",  "status": "working",
             "note": "Veo 3.1 fast preview"},
            {"id": "veo-3.1-lite-generate-preview",  "capability": "video",  "status": "working",
             "note": "Veo 3.1 lite preview"},
            # ── Audio / TTS ────────────────────────────────────────────────────
            {"id": "gemini-2.5-flash-preview-tts",             "capability": "tts", "status": "working",
             "rate_limit": {"note": "preview"}},
            {"id": "gemini-2.5-pro-preview-tts",               "capability": "tts", "status": "working",
             "rate_limit": {"note": "preview"}},
            {"id": "gemini-3.1-flash-tts-preview",             "capability": "tts", "status": "working",
             "note": "preview"},
            {"id": "gemini-2.5-flash-native-audio-latest",     "capability": "tts", "status": "working",
             "note": "native audio dialog"},
            {"id": "gemini-2.5-flash-native-audio-preview-09-2025", "capability": "tts", "status": "working",
             "note": "native audio dialog preview"},
            # ── Music (Lyria) ──────────────────────────────────────────────────
            {"id": "lyria-3-clip-preview",    "capability": "audio", "status": "working",
             "note": "Lyria 3 music clip"},
            {"id": "lyria-3-pro-preview",     "capability": "audio", "status": "working",
             "note": "Lyria 3 music pro"},
        ],
    },

    # ── NVIDIA NIM ────────────────────────────────────────────────────────────
    # 123 models; 40 RPM per account, 2 accounts = 80 RPM combined
    # No rate-limit headers returned; limits enforced server-side silently
    "nvidia_nim": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "auth_env": "NVIDIA_NIM_API_KEY,NVIDIA_NIM_API_KEY_0",
        "status": "working",
        "note": "2 accounts. 40 RPM per account = 80 RPM combined. No rate-limit headers. 123 models.",
        "models": [
            # ── Flagship chat ──────────────────────────────────────────────────
            {"id": "nvidia/llama-3.1-nemotron-ultra-253b-v1",  "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account; 2 accounts = 80 RPM combined"}},
            {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5", "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "nvidia/llama-3.1-nemotron-70b-instruct",   "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "meta/llama-3.3-70b-instruct",              "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "meta/llama-3.1-70b-instruct",              "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "meta/llama-3.1-8b-instruct",               "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "meta/llama-3.2-3b-instruct",               "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "meta/llama-4-maverick-17b-128e-instruct",  "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "mistralai/mistral-large-3-675b-instruct-2512", "capability": "chat", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "mistralai/mistral-large",                  "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "mistralai/mistral-medium-3.5-128b",        "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "mistralai/mixtral-8x22b-v0.1",             "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "mistralai/ministral-14b-instruct-2512",    "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "deepseek-ai/deepseek-v4-flash",            "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "deepseek-ai/deepseek-v4-pro",              "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "qwen/qwen3.5-397b-a17b",                   "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "qwen/qwen3.5-122b-a10b",                   "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "qwen/qwen3-next-80b-a3b-instruct",         "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "google/gemma-4-31b-it",                    "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "google/gemma-3-12b-it",                    "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "microsoft/phi-4-mini-instruct",            "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "microsoft/phi-3.5-moe-instruct",           "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "nvidia/nemotron-4-340b-instruct",          "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "moonshotai/kimi-k2.6",                     "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "openai/gpt-oss-120b",                      "capability": "chat",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            # ── Embedding ──────────────────────────────────────────────────────
            {"id": "nvidia/nv-embedqa-e5-v5",                  "capability": "embed", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "nvidia/nv-embedqa-mistral-7b-v2",          "capability": "embed", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "nvidia/llama-nemotron-embed-1b-v2",        "capability": "embed", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "nvidia/nv-embed-v1",                       "capability": "embed", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "nvidia/nv-embedcode-7b-v1",                "capability": "embed", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "snowflake/arctic-embed-l",                  "capability": "embed", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            # ── Vision ─────────────────────────────────────────────────────────
            {"id": "meta/llama-3.2-11b-vision-instruct",       "capability": "vision", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "meta/llama-3.2-90b-vision-instruct",       "capability": "vision", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "microsoft/phi-3-vision-128k-instruct",     "capability": "vision", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",  "capability": "vision", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "microsoft/phi-4-multimodal-instruct",      "capability": "vision", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            # ── Code ───────────────────────────────────────────────────────────
            {"id": "qwen/qwen3-coder-480b-a35b-instruct",      "capability": "code",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "mistralai/codestral-22b-instruct-v0.1",    "capability": "code",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "deepseek-ai/deepseek-coder-6.7b-instruct", "capability": "code",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "bigcode/starcoder2-15b",                   "capability": "code",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "ibm/granite-34b-code-instruct",            "capability": "code",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "google/codegemma-1.1-7b",                  "capability": "code",  "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            # ── Safety / guard ─────────────────────────────────────────────────
            {"id": "meta/llama-guard-4-12b",                       "capability": "safety", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
            {"id": "nvidia/llama-3.1-nemoguard-8b-content-safety", "capability": "safety", "status": "working",
             "rate_limit": {"rpm": 40, "note": "per account"}},
        ],
    },

    # ── Local ONNX (aigallery cache — ~/.cache/aigallery) ────────────────────────
    # 9 downloaded, 11 in catalog. Via OnnxRuntimeGenAI. No rate limits.
    # HuggingFace repos cloned by AI Dev Gallery app (microsoft/ai-dev-gallery).
    "local_onnx": {
        "base_url": "local://onnx",
        "auth_env": "",
        "status": "working",
        "note": "9 downloaded ONNX models in ~/.cache/aigallery. No API key required.",
        "models": [
            # ── Phi-4 Mini — DOWNLOADED ────────────────────────────────────────
            {"id": "local:phi4-cpu",        "capability": "chat",  "status": "working",
             "note": "microsoft--Phi-4-mini-instruct-onnx / cpu-int4-rtn-block-32-acc-level-4"},
            # ── Phi-4 catalog (not downloaded) ────────────────────────────────
            {"id": "local:phi4",            "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — GPU variant, needs download"},
            {"id": "local:phi4mini",        "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — generic alias, needs download"},
            {"id": "local:phi4-gpu",        "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — GPU variant, needs download"},
            # ── Phi-3.5 — DOWNLOADED ──────────────────────────────────────────
            {"id": "local:phi3.5-cpu",      "capability": "chat",   "status": "working",
             "note": "microsoft--Phi-3.5-mini-instruct-onnx / cpu-int4-awq-block-128-acc-level-4"},
            {"id": "local:phi3.5-vision",   "capability": "vision", "status": "working",
             "note": "microsoft--Phi-3.5-vision-instruct-onnx / cpu-int4-rtn-block-32-acc-level-4"},
            # ── Phi-3.5 catalog ───────────────────────────────────────────────
            {"id": "local:phi3.5",          "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — GPU variant, needs download"},
            # ── Phi-3 — DOWNLOADED ────────────────────────────────────────────
            {"id": "local:phi3-cpu",        "capability": "chat",  "status": "working",
             "note": "microsoft--Phi-3-mini-4k-instruct-onnx / cpu-int4-rtn-block-32"},
            {"id": "local:phi3-medium-cpu", "capability": "chat",  "status": "working",
             "note": "microsoft--Phi-3-medium-4k-instruct-onnx-cpu / cpu-int4-rtn-block-32-acc-level-4"},
            # ── Phi-3 catalog ─────────────────────────────────────────────────
            {"id": "local:phi3",            "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — GPU variant, needs download"},
            {"id": "local:phi3-cpu-acc1",   "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — higher acc level, needs download"},
            {"id": "local:phi3-dml",        "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — DirectML, needs download"},
            {"id": "local:phi3-medium",     "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — GPU variant, needs download"},
            # ── Mistral — DOWNLOADED ──────────────────────────────────────────
            {"id": "local:mistral-cpu",     "capability": "chat",  "status": "working",
             "note": "microsoft--mistral-7b-instruct-v0.2-ONNX / cpu-int4-rtn-block-32"},
            {"id": "local:mistral-cpu-acc1","capability": "chat",  "status": "working",
             "note": "microsoft--mistral-7b-instruct-v0.2-ONNX / cpu-int4-rtn-block-32-acc-level-4"},
            # ── Mistral catalog ───────────────────────────────────────────────
            {"id": "local:mistral",         "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — GPU variant, needs download"},
            {"id": "local:mistral-7b",      "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — generic alias, needs download"},
            {"id": "local:mistral-dml",     "capability": "chat",  "status": "trial",
             "note": "aigallery catalog — DirectML, needs download"},
            # ── Embeddings — DOWNLOADED ───────────────────────────────────────
            {"id": "local:minilm-l6",       "capability": "embed", "status": "working",
             "note": "sentence-transformers--all-MiniLM-L6-v2 / onnx/model.onnx"},
            {"id": "local:minilm-l12",      "capability": "embed", "status": "working",
             "note": "sentence-transformers--all-MiniLM-L12-v2 / onnx/model.onnx"},
        ],
    },

    # ── AI Toolkit (VS Code Extension — ONNX + QNN) ───────────────────────────
    # Served via VS Code AI Toolkit extension. Model IDs prefixed "aitk:".
    # QNN (Qualcomm NPU) acceleration available on supported hardware.
    "ai_toolkit": {
        "base_url": "local://aitk",
        "auth_env": "",
        "status": "working",
        "note": "11 models via VS Code AI Toolkit (ONNX/QNN + SD image gen). No key required.",
        "models": [
            # ── Language models ───────────────────────────────────────────────
            {"id": "aitk:phi-4-generic-cpu",         "capability": "chat", "status": "working",
             "note": "~/.aitk/models/Microsoft/Phi-4-generic-cpu-1 — phi-4-medium cpu-int4-rtn-block-32-acc-level-4 (full Phi-4, 14.7B)"},
            {"id": "aitk:phi-4-mini-instruct",       "capability": "chat", "status": "working",
             "note": "~/.aitk/models/Microsoft/Phi-4-mini-instruct-generic-cpu-5/v5"},
            {"id": "aitk:phi-4-mini-reasoning",      "capability": "chat", "status": "working",
             "note": "~/.aitk/models/Microsoft/Phi-4-mini-reasoning-generic-cpu-3/v3"},
            {"id": "aitk:phi-4-reasoning-14.7b-qnn", "capability": "chat", "status": "working",
             "note": "~/.aitk/models/Microsoft/Phi-4-reasoning-14.7b-qnn — QNN NPU shards + SD image gen bundle"},
            # ── Image generation (bundled in Phi-4-reasoning-14.7b-qnn folder) ─────
            {"id": "aitk:stable-diffusion-3.5-large", "capability": "image", "status": "working",
             "note": "~/.aitk/models/Microsoft/Phi-4-reasoning-14.7b-qnn/stable-diffusion-3.5-large_amdgpu — AMD GPU"},
            {"id": "aitk:stable-diffusion-3-medium",  "capability": "image", "status": "working",
             "note": "~/.aitk/models/Microsoft/Phi-4-reasoning-14.7b-qnn/stable-diffusion-3-medium_amdgpu — AMD GPU"},
            {"id": "aitk:realmodelbase-lcm",          "capability": "image", "status": "working",
             "note": "~/.aitk/.../Phi-4-reasoning-14.7b-qnn/RealModelBase-LCM-amuse — Amuse ControlNet"},
            {"id": "aitk:realistic-lcm",              "capability": "image", "status": "working",
             "note": "~/.aitk/.../Phi-4-reasoning-14.7b-qnn/Realistic-LCM-amuse — Amuse ControlNet"},
            {"id": "aitk:absolutereality-v181",       "capability": "image", "status": "working",
             "note": "~/.aitk/.../Phi-4-reasoning-14.7b-qnn/AbsoluteReality_v181-amuse — Amuse ControlNet"},
            {"id": "aitk:dreamshaper-lcm",            "capability": "image", "status": "trial",
             "note": "~/.aitk/.../Phi-4-reasoning-14.7b-qnn/Dreamshaper-LCM-amuse — controlnet still downloading"},
            # ── OCI registry entries (not runnable, listed by bridge) ─────────────
            {"id": "aitk:blobs",                      "capability": "registry", "status": "working",
             "note": "OCI blob registry entry"},
            {"id": "aitk:manifests",                  "capability": "registry", "status": "working",
             "note": "OCI manifest registry entry"},
        ],
    },

    # ── Windows AI (system NPU/WinML — Copilot+ PC, Windows 11 24H2+) ───────────
    # System-level models deployed via Windows Update (WindowsApps packages).
    # AMD XDNA2 NPU (Strix / Ryzen AI 300) via VitisAI EP. CPU fallback available.
    # Access via Windows.AI.* WinRT APIs or Windows ML runtime. No API key.
    "windows_ai": {
        "base_url": "local://winrt",
        "auth_env": "",
        "status": "working",
        "note": "Copilot+ PC system AI. AMD XDNA2 NPU (VitisAI). No key required.",
        "models": [
            # ── Language (Phi Silica / WinML NPU) ────────────────────────────
            {"id": "windows_ai:phi-3.6-npu",                    "capability": "chat",  "status": "working",
             "note": "WindowsWorkload.LanguageModel.Data.1 — phi3_6_transformer_wmpa16.quant, WinML NPU/CPU"},
            # ── Image generation (SD VitisAI — AMD NPU Strix) ────────────────
            {"id": "windows_ai:stable-diffusion-stx",           "capability": "image", "status": "working",
             "note": "WindowsWorkload.ImageGenerator.Data.Stx.1 — SD unet VitisAI, AMD XDNA2 NPU"},
            {"id": "windows_ai:stable-diffusion-stx-canny",     "capability": "image", "status": "working",
             "note": "WindowsWorkload.ImageGenerator.Data.Stx.1 — SD + ControlNet canny, XDNA2 NPU"},
            {"id": "windows_ai:stable-diffusion-stx-scribble",  "capability": "image", "status": "working",
             "note": "WindowsWorkload.ImageGenerator.Data.Stx.1 — SD + ControlNet scribble, XDNA2 NPU"},
            {"id": "windows_ai:stable-diffusion-stx-inpainting","capability": "image", "status": "working",
             "note": "WindowsWorkload.ImageGenerator.Data.Stx.1 — SD + ControlNet inpainting, XDNA2 NPU"},
            {"id": "windows_ai:image-generator",               "capability": "image", "status": "working",
             "note": "Microsoft.ImageGenerationExtension — sd/unet_sd.quant.onnxe, system image gen"},
        ],
    },

    # ── Windows AI Foundry (ONNX — ~/.foundry/cache/models) ─────────────────────
    # Azure ML ONNX models downloaded via AI Dev Gallery v2 / Windows AI Foundry.
    # Inference via Windows AI Foundry SDK (inference_model.json). No API key.
    "windows_foundry": {
        "base_url": "local://foundry",
        "auth_env": "",
        "status": "working",
        "note": "3 ONNX models in ~/.foundry/cache/models/Microsoft. No key required.",
        "models": [
            {"id": "foundry:Phi-4-mini-instruct-generic-cpu",  "capability": "chat", "status": "working",
             "note": "CPU int4, 4.9 GB, v5 — Phi-4-mini-instruct-generic-cpu-5/v5"},
            {"id": "foundry:phi-4-mini-instruct-vitis-npu",    "capability": "chat", "status": "working",
             "note": "VitisAI NPU, 3.7 GB, v2 — phi-4-mini-instruct-vitis-npu-2/v2"},
            {"id": "foundry:qwen3-0.6b-generic-cpu",           "capability": "chat", "status": "working",
             "note": "CPU int4, Qwen3 0.6B, v3 — qwen3-0.6b-generic-cpu-3/v3"},
        ],
    },

    # ── Ollama (local) ────────────────────────────────────────────────────────
    "ollama": {
        "base_url": "http://localhost:11434",
        "auth_env": "",
        "status": "working",
        "note": "Local inference. No rate limits. Hardware-bound throughput.",
        "models": [
            {"id": "gemma4:31b",                                         "capability": "chat",  "status": "working",
             "note": "19.9 GB"},
            {"id": "hf.co/lmstudio-community/Qwen3.6-27B-GGUF:Q8_0",   "capability": "chat",  "status": "working",
             "note": "29.5 GB Q8_0"},
            {"id": "hf.co/lmstudio-community/Qwen3.6-27B-GGUF:Q4_K_M", "capability": "chat",  "status": "working",
             "note": "17.5 GB Q4_K_M"},
            {"id": "qwen3-coder:30b",                                    "capability": "code",  "status": "working",
             "note": "18.6 GB"},
        ],
    },

    # ── LM Studio (local) ─────────────────────────────────────────────────────
    "lm_studio": {
        "base_url": "http://172.30.240.1:12340",
        "auth_env": "LM_STUDIO_BASE_URL",
        "status": "working",
        "note": "Local inference server. No rate limits. Hardware-bound throughput.",
        "models": [
            # ── Chat / reasoning ──────────────────────────────────────────────
            {"id": "qwen/qwen3.5-35b-a3b-uncensored",   "capability": "chat", "status": "working",
             "note": "~/Downloads/Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive-Q8_0.gguf — MoE 35B/3B active"},
            {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "capability": "chat", "status": "working",
             "note": "~/.models/lmstudio-community/nemotron-3-nano-omni-30b-a3b-reasoning-gguf / Q4_K_M"},
            {"id": "nvidia/nemotron-3-nano-4b",          "capability": "chat", "status": "working",
             "note": "~/.models/lmstudio-community/NVIDIA-Nemotron-3-Nano-4B-GGUF / Q4_K_M"},
            {"id": "deepseek/deepseek-r1-0528-qwen3-8b", "capability": "code", "status": "working",
             "note": "~/.models/lmstudio-community/DeepSeek-R1-0528-Qwen3-8B-GGUF / Q4_K_M"},
            {"id": "llama3.3-8b-instruct-thinking-heretic-uncensored-claude-4.5-opus-high-reasoning-i1",
             "capability": "chat", "status": "working",
             "note": "~/.models/mradermacher/Llama3.3-8B-Instruct-Thinking-Heretic-Uncensored-.../ i1-Q6_K"},
            {"id": "llama-3.2-1b-instruct",              "capability": "chat", "status": "working",
             "note": "~/.models/hugging-quants/Llama-3.2-1B-Instruct-Q8_0-GGUF / Q8_0"},
            {"id": "qwen2.5-0.5b-instruct",              "capability": "chat", "status": "working",
             "note": "~/.models/lmstudio-community/Qwen2.5-0.5B-Instruct-GGUF / Q8_0"},
            # ── Vision (main weights + mmproj projector confirmed) ────────────
            {"id": "google/gemma-4-31b",                 "capability": "vision", "status": "working",
             "note": "~/.models/lmstudio-community/gemma-4-31B-it-GGUF / Q4_K_M + mmproj BF16"},
            {"id": "qwen/qwen3.6-27b",                   "capability": "vision", "status": "working",
             "note": "~/.models/lmstudio-community/Qwen3.6-27B-GGUF / Q4_K_M + mmproj BF16"},
            {"id": "google/gemma-4-26b-a4b",             "capability": "vision", "status": "working",
             "note": "~/.models/lmstudio-community/gemma-4-26B-A4B-it-GGUF / Q4_K_M + mmproj BF16"},
            {"id": "google/gemma-4-e4b",                 "capability": "vision", "status": "working",
             "note": "~/.models/lmstudio-community/gemma-4-E4B-it-GGUF / Q8_0 + Q4_K_M + mmproj BF16"},
            {"id": "qwen/qwen3.5-9b",                    "capability": "vision", "status": "working",
             "note": "~/.models/lmstudio-community/Qwen3.5-9B-GGUF / Q4_K_M + mmproj BF16"},
            {"id": "google/gemma-3-12b",                 "capability": "vision", "status": "working",
             "note": "~/.models/lmstudio-community/gemma-3-12b-it-GGUF / Q4_K_M + mmproj F16"},
            {"id": "google/gemma-3-4b",                  "capability": "vision", "status": "working",
             "note": "~/.models/lmstudio-community/gemma-3-4b-it-GGUF / Q4_K_M + mmproj F16"},
            {"id": "zai-org/glm-4.6v-flash",             "capability": "vision", "status": "working",
             "note": "~/.models/lmstudio-community/GLM-4.6V-Flash-GGUF / Q4_K_M + mmproj F16"},
            # ── Embeddings ────────────────────────────────────────────────────
            {"id": "text-embedding-nomic-embed-text-v1.5","capability": "embed", "status": "working",
             "note": "~/.lmstudio/.internal/bundled-models/nomic-ai/nomic-embed-text-v1.5-GGUF / Q4_K_M"},
            # ── TTS ───────────────────────────────────────────────────────────
            {"id": "qwen3-1.7b-multilingual-tts",        "capability": "tts",   "status": "working",
             "note": "~/.models/mradermacher/Qwen3-1.7B-Multilingual-TTS-GGUF / Q8_0"},
            {"id": "tts",                                 "capability": "tts",   "status": "working",
             "note": "LM Studio built-in TTS server endpoint"},
        ],
    },

    # ── Anthropic ─────────────────────────────────────────────────────────────
    # Model listing works; completions blocked — both keys have $0 credits
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "auth_env": "ANTHROPIC_API_KEY,ANTHROPIC_API_KEY_0",
        "status": "billing_needed",
        "note": "Both keys authenticated; $0 credit balance on org. Add credits to use.",
        "models": [
            {"id": "claude-opus-4-7",              "capability": "chat", "status": "billing_needed"},
            {"id": "claude-opus-4-6",              "capability": "chat", "status": "billing_needed"},
            {"id": "claude-opus-4-5-20251101",     "capability": "chat", "status": "billing_needed"},
            {"id": "claude-opus-4-20250514",       "capability": "chat", "status": "billing_needed"},
            {"id": "claude-opus-4-1-20250805",     "capability": "chat", "status": "billing_needed"},
            {"id": "claude-sonnet-4-6",            "capability": "chat", "status": "billing_needed"},
            {"id": "claude-sonnet-4-5-20250929",   "capability": "chat", "status": "billing_needed"},
            {"id": "claude-sonnet-4-20250514",     "capability": "chat", "status": "billing_needed"},
            {"id": "claude-haiku-4-5-20251001",    "capability": "chat", "status": "billing_needed"},
        ],
    },

    # ── OpenAI Direct ─────────────────────────────────────────────────────────
    # Model listing works; completions blocked — project quota exhausted
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "auth_env": "OPENAI_API_KEY",
        "status": "billing_needed",
        "note": "Key valid (sk-proj-). insufficient_quota — add credits at platform.openai.com/billing.",
        "models": [
            {"id": "gpt-4o-mini",    "capability": "chat",  "status": "billing_needed"},
            {"id": "gpt-4o",         "capability": "chat",  "status": "billing_needed"},
            {"id": "gpt-4.1",        "capability": "chat",  "status": "billing_needed"},
            {"id": "o1-mini",        "capability": "chat",  "status": "billing_needed"},
            {"id": "o3-mini",        "capability": "chat",  "status": "billing_needed"},
            {"id": "o4-mini",        "capability": "chat",  "status": "billing_needed"},
        ],
    },

    # ── Azure OpenAI ──────────────────────────────────────────────────────────
    # Key valid; 306 catalog models visible; no deployments created yet
    "azure_openai": {
        "base_url": "https://afaifoundry-resource.openai.azure.com/openai",
        "auth_env": "AZURE_OPENAI_API_KEY_0,AZURE_OPENAI_ENDPOINT_0",
        "status": "no_deployments",
        "note": "Key valid. 306 catalog models. No deployments created — use Azure Portal.",
        "models": [],  # Populated after deployments are created
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def working_models(capability: str | None = None) -> dict[str, list[ModelEntry]]:
    """Return {provider: [models]} for all working providers/models."""
    result: dict[str, list[ModelEntry]] = {}
    for provider, info in REGISTRY.items():
        if info.get("status") not in ("working", "trial"):
            continue
        models = [
            m for m in info.get("models", [])
            if m.get("status") in ("working", "trial")
            and (capability is None or m.get("capability") == capability)
        ]
        if models:
            result[provider] = models
    return result


def models_by_capability(capability: str) -> list[dict]:
    """Return flat list of {provider, base_url, auth_env, model_id, rate_limit} dicts."""
    out = []
    for provider, info in REGISTRY.items():
        for m in info.get("models", []):
            if m.get("capability") == capability and m.get("status") in ("working", "trial"):
                out.append({
                    "provider": provider,
                    "base_url": info["base_url"],
                    "auth_env": info["auth_env"],
                    "model_id": m["id"],
                    "rate_limit": m.get("rate_limit", {}),
                    "note": m.get("note", ""),
                })
    return out


def rate_limit_summary() -> str:
    """Human-readable rate-limit matrix."""
    lines = [
        f"{'Provider':<20} {'Model':<55} {'Status':<18} {'RPM':>8} {'TPM':>12} {'RPD':>7} Notes",
        "-" * 130,
    ]
    for provider, info in REGISTRY.items():
        p_status = info.get("status", "unknown")
        for m in info.get("models", []):
            rl = m.get("rate_limit", {})
            rpm  = str(rl.get("rpm",  "—")).rjust(8)
            tpm  = str(rl.get("tpm",  "—")).rjust(12)
            rpd  = str(rl.get("rpd",  "—")).rjust(7)
            note = rl.get("note", m.get("note", ""))
            status = m.get("status", p_status)
            lines.append(
                f"{provider:<20} {m['id']:<55} {status:<18} {rpm} {tpm} {rpd}  {note}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    print(rate_limit_summary())
    print()
    print("=== Working chat models ===")
    for entry in models_by_capability("chat"):
        print(f"  [{entry['provider']}] {entry['model_id']}")
    print()
    print("=== Working embed models ===")
    for entry in models_by_capability("embed"):
        print(f"  [{entry['provider']}] {entry['model_id']}")
