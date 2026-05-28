#!/usr/bin/env bash
set -euo pipefail

python -m pytest --cov=agentic_v2_eval --cov-report=term-missing --cov-report=xml "$@"

