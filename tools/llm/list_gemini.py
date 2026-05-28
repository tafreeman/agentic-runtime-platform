from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root))

from tools.llm.llm_client import LLMClient

logger = logging.getLogger(__name__)

try:
    logger.info("Checking for Gemini models...")
    models = LLMClient.list_gemini_models()
    if models:
        logger.info(f"Found {len(models)} Gemini models:")
        for m in models:
            logger.info(f"- {m}")
    else:
        logger.info("No Gemini models found. Check GEMINI_API_KEY env var.")
except Exception as e:
    logger.error(f"Error listing models: {e}")
