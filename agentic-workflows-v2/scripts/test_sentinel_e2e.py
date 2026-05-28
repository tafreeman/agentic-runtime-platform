"""Quick end-to-end test: run one coder step and inspect whether sentinel
blocks appear in the raw LLM response, then check the parser output."""

import asyncio
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_v2.engine.agent_resolver import (
    _TIER_MAX_TOKENS,
    _make_llm_step,
    _parse_sentinel_output,
)
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.models.router import ModelTier


async def main():
    ctx = ExecutionContext()
    await ctx.set(
        "feature_spec",
        "Build a minimal 'hello world' FastAPI app with one GET /health endpoint that returns {status: ok}.",
    )
    await ctx.set(
        "tech_stack", {"frontend": "none", "backend": "fastapi", "database": "none"}
    )

    tier = ModelTier.TIER_2
    print(f"max_tokens for tier {tier.name}: {_TIER_MAX_TOKENS[tier]}")

    step_fn = _make_llm_step(
        agent_name="tier2_coder",
        description="Generate the complete backend code for the feature spec. Use the sentinel artifact format exactly as described in your system prompt.",
        tier=tier,
        expected_output_keys=["backend_code", "integration_tests"],
    )

    print("\nCalling LLM step... (this may take 30-60s)")
    result = await step_fn(ctx)

    # Check for sentinel blocks in the raw response
    raw_keys = list(result.keys())
    print(f"\nOutput keys: {raw_keys}")

    if "backend_code" in result:
        code = result["backend_code"]
        print(f"\n✅ backend_code present ({len(code)} chars)")
        print("--- first 300 chars ---")
        print(code[:300])
    elif "raw_response" in result:
        raw = result["raw_response"]
        print(f"\n⚠️  Only raw_response returned ({len(raw)} chars)")
        print("--- first 500 chars ---")
        print(raw[:500])
        # Try manual sentinel parse
        parsed = _parse_sentinel_output(raw, ["backend_code"])
        if parsed:
            print(f"\nManual sentinel parse found: {list(parsed.keys())}")
        else:
            print("\nNo sentinel blocks found in raw_response")
    else:
        print(
            f"\n❓ Unexpected result: {json.dumps({k: str(v)[:100] for k, v in result.items()}, indent=2)}"
        )

    if "backend_code_files" in result:
        files = result["backend_code_files"]
        print(f"\n✅ backend_code_files index: {list(files.keys())}")

    meta = result.get("_meta", {})
    if meta:
        print(
            f"\nModel used: {meta.get('model_used')}, tokens: {meta.get('tokens_used')}"
        )


if __name__ == "__main__":
    asyncio.run(main())
