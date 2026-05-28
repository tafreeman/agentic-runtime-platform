"""Evaluation runners for batch and streaming execution.

This module provides runners for executing evaluations:
- batch: Run evaluations on a batch of test cases
- streaming: Run evaluations with real-time callbacks
"""

from __future__ import annotations

from .batch import BatchRunner, run_batch_evaluation
from .streaming import StreamingRunner, run_streaming_evaluation

__all__ = [
    "BatchRunner",
    "StreamingRunner",
    "run_batch_evaluation",
    "run_streaming_evaluation",
]
