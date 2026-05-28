"""Pluggable evaluator implementations and central registry.

Exposes four evaluator strategies:
    LLMEvaluator: Choice-anchored LLM-as-judge scoring.
    PatternEvaluator: Agentic-pattern phase/constraint scoring.
    QualityEvaluator: Coherence / Fluency / Relevance / Groundedness / Similarity.
    StandardEvaluator: Five-dimension prompt quality scoring.

All evaluators self-register in :class:`EvaluatorRegistry` at import time.
"""

from .base import Evaluator, EvaluatorRegistry
from .llm import STANDARD_CHOICES, Choice, LLMClientProtocol, LLMEvaluator
from .pattern import PatternEvaluator, PatternScore
from .quality import (
    COHERENCE,
    FLUENCY,
    GROUNDEDNESS,
    RELEVANCE,
    SIMILARITY,
    LLMEvaluatorDefinition,
    QualityEvaluator,
)
from .standard import StandardEvaluator, StandardScore

__all__ = [
    "COHERENCE",
    "FLUENCY",
    "GROUNDEDNESS",
    "RELEVANCE",
    "SIMILARITY",
    "STANDARD_CHOICES",
    "Choice",
    # Base
    "Evaluator",
    "EvaluatorRegistry",
    # LLM
    "LLMClientProtocol",
    "LLMEvaluator",
    "LLMEvaluatorDefinition",
    # Pattern
    "PatternEvaluator",
    "PatternScore",
    # Quality
    "QualityEvaluator",
    # Standard
    "StandardEvaluator",
    "StandardScore",
]
