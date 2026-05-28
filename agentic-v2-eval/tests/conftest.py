"""Test configuration for agentic-v2-eval.

This project uses a src/ layout. When running tests without installing
the package (e.g., directly from a repo checkout), ensure the src/
directory is on sys.path so `import agentic_v2_eval` works.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "src").resolve()
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
