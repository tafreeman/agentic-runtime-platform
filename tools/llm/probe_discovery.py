"""Model discovery across all configured providers.

The :func:`discover_all_models` function scans every supported provider
(local ONNX, GitHub Models, Ollama, OpenAI, Gemini, Claude, Azure,
Windows AI, AI Toolkit, LM Studio, generic local servers) and returns
a comprehensive inventory of available models.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def discover_all_models(verbose: bool = False) -> dict[str, Any]:
    """Discover all available models from all configured providers.

    Returns a dict with models grouped by provider.
    """
    from tools.llm.probe_discovery_providers import (
        _probe_aitk,
        _probe_anthropic,
        _probe_azure_foundry,
        _probe_azure_openai,
        _probe_gemini,
        _probe_github_models,
        _probe_lmstudio,
        _probe_local_onnx,
        _probe_local_openai_compatible,
        _probe_nvidia,
        _probe_ollama,
        _probe_openai,
        _probe_windows_ai,
    )

    discovered: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "providers": {},
    }

    # 1. Local ONNX (AI Gallery)
    if verbose:
        logger.info("[Discovery] Checking local ONNX models...")
    discovered["providers"]["local_onnx"] = _probe_local_onnx(verbose=verbose)

    # 2. GitHub Models
    if verbose:
        logger.info("[Discovery] Checking GitHub Models...")
    discovered["providers"]["github_models"] = _probe_github_models()

    # 3. Ollama
    if verbose:
        logger.info("[Discovery] Checking Ollama models...")
    discovered["providers"]["ollama"] = _probe_ollama()

    # 4. Azure Foundry
    if verbose:
        logger.info("[Discovery] Checking Azure Foundry...")
    discovered["providers"]["azure_foundry"] = _probe_azure_foundry()

    # 5. Azure OpenAI
    if verbose:
        logger.info("[Discovery] Checking Azure OpenAI...")
    discovered["providers"]["azure_openai"] = _probe_azure_openai()

    # 6. OpenAI (direct)
    if verbose:
        logger.info("[Discovery] Checking OpenAI API...")
    discovered["providers"]["openai"] = _probe_openai()

    # 7. Gemini
    if verbose:
        logger.info("[Discovery] Checking Google Gemini...")
    discovered["providers"]["gemini"] = _probe_gemini()

    # 8. Anthropic Claude
    if verbose:
        logger.info("[Discovery] Checking Anthropic Claude...")
    discovered["providers"]["anthropic"] = _probe_anthropic()

    # 9. Windows AI (Phi Silica)
    if verbose:
        logger.info("[Discovery] Checking Windows AI / Phi Silica...")
    discovered["providers"]["windows_ai"] = _probe_windows_ai(
        bridge_dir=Path(__file__).parent
    )

    # 10. AI Toolkit Local Models (FREE - local ONNX models from VS Code AI Toolkit)
    if verbose:
        logger.info("[Discovery] Checking AI Toolkit local models...")
    discovered["providers"]["ai_toolkit"] = _probe_aitk()

    # 11. LM Studio (OpenAI-compatible local server)
    if verbose:
        logger.info("[Discovery] Checking LM Studio...")
    lmstudio_result = _probe_lmstudio()
    discovered["providers"]["lmstudio"] = lmstudio_result

    # 12. Generic OpenAI-compatible local servers (LocalAI, text-generation-webui, etc.)
    if verbose:
        logger.info("[Discovery] Checking local OpenAI-compatible servers...")
    lmstudio_host = lmstudio_result.get("host", "")
    discovered["providers"]["local_openai_compatible"] = _probe_local_openai_compatible(
        lmstudio_host=lmstudio_host
    )

    # 13. NVIDIA NIM (cloud inference with bearer key)
    if verbose:
        logger.info("[Discovery] Checking NVIDIA NIM...")
    discovered["providers"]["nvidia_nim"] = _probe_nvidia()

    # Summary
    total_available = sum(
        len(p.get("available", []))
        for p in discovered["providers"].values()
        if isinstance(p.get("available"), list)
    )
    discovered["summary"] = {
        "total_available": total_available,
        "providers_configured": sum(
            1
            for p in discovered["providers"].values()
            if p.get("configured", False) or p.get("available")
        ),
    }

    return discovered
