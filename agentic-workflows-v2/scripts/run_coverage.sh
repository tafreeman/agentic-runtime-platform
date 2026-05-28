#!/usr/bin/env bash
set -euo pipefail

python -m pytest --cov=agentic_v2 --cov-report=term-missing --cov-report=xml "$@"

