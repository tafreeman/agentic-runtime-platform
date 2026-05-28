"""Adapters for external integrations.

This module provides adapters that bridge external clients and services
to the protocols expected by agentic-v2-eval components.
"""

from .llm_client import LLMClientAdapter, create_llm_client

__all__ = ["LLMClientAdapter", "create_llm_client"]
