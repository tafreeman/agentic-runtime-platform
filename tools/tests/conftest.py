"""Shared fixtures for tools/ test suite."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is on sys.path so `from tools.xxx import yyy` works.
_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
