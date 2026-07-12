#!/usr/bin/env python3
"""Generate a sample workflow trace JSON for testing score-trace.py.

Writes ``sample-trace.json`` to the current directory.  The trace contains
four steps with realistic outputs for different agent types:

- ``generate_code``   — coder agent with a Python code snippet
- ``review_code``     — reviewer agent with a structured code review
- ``architect_plan``  — architect agent with a system design description
- ``summarize``       — orchestrator agent with a workflow summary

Usage:
    python scripts/generate-sample-trace.py
    python scripts/generate-sample-trace.py --output my-trace.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sample step data
# ---------------------------------------------------------------------------

_START = datetime(2025, 5, 21, 9, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


_CODER_OUTPUT = """\
```python
from __future__ import annotations

import hashlib
from pathlib import Path


def compute_file_checksum(file_path: Path, algorithm: str = "sha256") -> str:
    \"\"\"Compute the cryptographic checksum of a file.

    Args:
        file_path: Path to the file.
        algorithm: Hash algorithm to use (default: sha256).

    Returns:
        Hex-encoded digest string.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the algorithm is not supported.
    \"\"\"
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        hasher = hashlib.new(algorithm)
    except ValueError as exc:
        raise ValueError(f"Unsupported algorithm {algorithm!r}: {exc}") from exc

    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            hasher.update(chunk)

    return hasher.hexdigest()


def verify_checksum(file_path: Path, expected: str, algorithm: str = "sha256") -> bool:
    \"\"\"Verify a file's checksum against an expected value.

    Args:
        file_path: Path to the file.
        expected: Expected hex digest.
        algorithm: Hash algorithm to use.

    Returns:
        True if the checksum matches.
    \"\"\"
    actual = compute_file_checksum(file_path, algorithm)
    return actual == expected.lower()
```

The implementation uses a streaming read loop (64 KB chunks) to avoid loading
large files into memory.  Both functions are fully type-annotated and raise
descriptive exceptions on invalid inputs.
"""

_REVIEWER_OUTPUT = """\
## Code Review: compute_file_checksum

**Overall Status:** APPROVED_WITH_NOTES
**Quality Score:** 8.2 / 10

### Findings

#### LOW — Missing algorithm allowlist
- **File:** checksums.py
- **Line:** 22
- **Description:** The `algorithm` parameter is passed directly to `hashlib.new()`
  without restricting to secure algorithms.  A caller could pass `md5` or `sha1`,
  which are considered cryptographically weak.
- **Suggested fix:** Add an `ALLOWED_ALGORITHMS = frozenset({"sha256", "sha384", "sha512"})`
  guard and raise `ValueError` for anything outside this set.

#### INFO — Docstring could include example
- **Description:** Adding a short usage example in the docstring would improve
  discoverability.

### Positive Observations

1. Excellent use of streaming reads — avoids memory issues on large files.
2. Proper `__future__` annotations import.
3. Type hints on all parameters and return values.
4. Descriptive exception messages with f-strings.
5. `verify_checksum` correctly normalises the expected digest to lowercase.

### Recommendation

Merge after addressing the algorithm allowlist concern.
"""

_ARCHITECT_OUTPUT = """\
# System Design: File Integrity Service

## Overview

The File Integrity Service provides a REST API for computing and verifying
cryptographic checksums of artefacts stored in object storage.  It is designed
as a stateless microservice deployed on Kubernetes with a Redis-backed cache
for repeated checksum lookups.

## Component Diagram

```
Client → API Gateway → FastAPI Service → Object Storage (S3-compatible)
                               ↓
                          Redis Cache
                               ↓
                         Audit Log (PostgreSQL)
```

## Key Design Decisions

### 1. Streaming Computation
All files are hashed in 64 KB streaming chunks to keep memory footprint
constant regardless of file size.  This enables processing files up to
100 GB with a 128 MB container memory limit.

### 2. Cache Strategy
Completed checksums are cached in Redis with a TTL of 24 hours, keyed by
`{bucket}/{object_key}:{etag}`.  The ETag ensures cache invalidation when
the object is replaced.

### 3. Algorithm Allowlist
Only SHA-256, SHA-384, and SHA-512 are supported.  MD5 and SHA-1 are
explicitly blocked to prevent use of weak algorithms in compliance contexts.

### 4. Audit Trail
Every verification request is written to an append-only PostgreSQL table with:
- Request timestamp (UTC)
- Caller identity (from JWT sub)
- Object path
- Algorithm used
- Pass/fail result

## Non-Functional Requirements

| Requirement | Target |
|---|---|
| Throughput | 1,000 req/min per replica |
| Latency (p99) | < 2 s for files ≤ 100 MB |
| Availability | 99.9% (3 replicas) |
| Security | mTLS between service and object storage |

## Open Questions

1. Should we support batch verification (multiple files in one request)?
2. Is a FIPS-140 compliant HSM required for key storage?
"""

_ORCHESTRATOR_OUTPUT = """\
## Workflow Summary: Code Generation → Review → Architecture

The workflow completed in 3 steps with 1 advisory finding.

### Step Results

| Step | Agent | Status | Duration |
|---|---|---|---|
| generate_code | coder | SUCCESS | 4.2 s |
| review_code | reviewer | SUCCESS | 3.1 s |
| architect_plan | architect | SUCCESS | 6.8 s |

### Key Outcomes

- **Code quality:** The coder produced a clean, streaming-based checksum utility
  with full type annotations.  The reviewer approved it with a minor note about
  the algorithm allowlist.
- **Architecture:** The architect designed a stateless microservice with a
  Redis cache and PostgreSQL audit trail.  Two open questions remain for
  stakeholder review.
- **Action items:**
  1. Add SHA-256/384/512 allowlist to `compute_file_checksum`.
  2. Answer architect's open questions before sprint planning.

### Next Steps

Route to human review for final sign-off on the algorithm allowlist guard and
the batch-verification question.
"""


def _build_trace() -> dict:
    """Construct the full trace dict in WorkflowResult shape."""
    t0 = _START

    steps = [
        {
            "step_name": "generate_code",
            "agent_role": "coder",
            "status": "success",
            "start_time": _iso(t0),
            "end_time": _iso(t0 + timedelta(seconds=4.2)),
            "output_data": {
                "text": _CODER_OUTPUT,
                "language": "python",
                "file_path": "src/checksums.py",
            },
            "metadata": {
                "model_used": "gh:gpt-4o",
                "tokens_used": 812,
            },
            "retry_count": 0,
        },
        {
            "step_name": "review_code",
            "agent_role": "reviewer",
            "status": "success",
            "start_time": _iso(t0 + timedelta(seconds=5)),
            "end_time": _iso(t0 + timedelta(seconds=8.1)),
            "output_data": {
                "text": _REVIEWER_OUTPUT,
                "overall_status": "APPROVED_WITH_NOTES",
                "quality_score": 8.2,
            },
            "metadata": {
                "model_used": "gh:gpt-4o",
                "tokens_used": 654,
            },
            "retry_count": 0,
        },
        {
            "step_name": "architect_plan",
            "agent_role": "architect",
            "status": "success",
            "start_time": _iso(t0 + timedelta(seconds=9)),
            "end_time": _iso(t0 + timedelta(seconds=15.8)),
            "output_data": {
                "text": _ARCHITECT_OUTPUT,
            },
            "metadata": {
                "model_used": "anthropic:claude-opus-4",
                "tokens_used": 1103,
            },
            "retry_count": 0,
        },
        {
            "step_name": "summarize",
            "agent_role": "orchestrator",
            "status": "success",
            "start_time": _iso(t0 + timedelta(seconds=17)),
            "end_time": _iso(t0 + timedelta(seconds=19.5)),
            "output_data": {
                "text": _ORCHESTRATOR_OUTPUT,
            },
            "metadata": {
                "model_used": "gh:gpt-4o-mini",
                "tokens_used": 448,
            },
            "retry_count": 0,
        },
    ]

    return {
        "workflow_id": "wf-20250521-checksum-service",
        "workflow_name": "Checksum Service Development",
        "overall_status": "success",
        "start_time": _iso(t0),
        "end_time": _iso(t0 + timedelta(seconds=20)),
        "steps": steps,
        "final_output": {
            "artifacts": ["src/checksums.py"],
            "review_status": "APPROVED_WITH_NOTES",
            "action_items": 2,
        },
        "metadata": {
            "total_tokens": 3017,
            "workflow_version": "1.0.0",
            "engine": "native",
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="generate-sample-trace",
        description="Generate a sample workflow trace JSON for testing score-trace.py.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("sample-trace.json"),
        help="Output path for the sample trace (default: sample-trace.json).",
    )
    parser.add_argument(
        "--pretty",
        "-p",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: true).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the generate-sample-trace CLI.

    Args:
        argv: Argument list (defaults to ``sys.argv``).

    Returns:
        Exit code 0 on success, 1 on error.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    output_path: Path = args.output
    trace = _build_trace()

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(trace, fh, indent=2 if args.pretty else None, ensure_ascii=False)
    except OSError as exc:
        print(f"ERROR: Could not write {output_path}: {exc}", file=sys.stderr)
        return 1

    print(f"Sample trace written to: {output_path}")
    print(f"  Workflow:  {trace['workflow_name']}")
    print(f"  Steps:     {len(trace['steps'])}")
    print()
    print("To score it, run:")
    print(f"  python scripts/score-trace.py {output_path}")
    print(
        f"  python scripts/score-trace.py {output_path} --output report.html --format html"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
