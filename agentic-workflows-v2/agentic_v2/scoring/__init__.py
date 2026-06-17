"""Scoring and judge domain logic for workflow evaluation.

This package holds the pure-domain scoring, rubric, judge, and dataset-matching
logic that was previously colocated with the FastAPI transport layer in
:mod:`agentic_v2.server`. It has no dependency on the server transport package;
``server`` depends on ``scoring`` (and not the reverse). See ADR-0007.
"""

from __future__ import annotations
