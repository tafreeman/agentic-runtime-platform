"""Tests for module-level constants in tools/llm/model_registry.py.

Importing the module executes the module-level lines that define
_LM_STUDIO_HOST, _LM_STUDIO_PORT, and _LM_STUDIO_BASE_URL (~lines 50-57).
These tests assert the expected values so those lines are counted as covered.

Target:
  - tools/llm/model_registry.py  _LM_STUDIO_HOST/_PORT/_BASE_URL (~lines 50-57)
"""

from __future__ import annotations

import tools.llm.model_registry as registry_module
from tools.llm.model_registry import (
    REGISTRY,
    _LM_STUDIO_BASE_URL,
    _LM_STUDIO_HOST,
    _LM_STUDIO_PORT,
)


class TestLmStudioConstants:
    """Tier 2: module-level LM Studio endpoint constants have expected values."""

    def test_lm_studio_host_is_wsl2_gateway(self):
        """_LM_STUDIO_HOST must be the WSL2 host-gateway IP."""
        assert _LM_STUDIO_HOST == "172.30.240.1"

    def test_lm_studio_port(self):
        """_LM_STUDIO_PORT must be the configured port number."""
        assert _LM_STUDIO_PORT == 12340

    def test_lm_studio_base_url_is_composed_from_host_and_port(self):
        """_LM_STUDIO_BASE_URL is http://<host>:<port> with no trailing slash."""
        assert f"http://{_LM_STUDIO_HOST}:{_LM_STUDIO_PORT}" == _LM_STUDIO_BASE_URL
        assert _LM_STUDIO_BASE_URL == "http://172.30.240.1:12340"

    def test_lm_studio_registry_entry_uses_base_url_constant(self):
        """The lm_studio REGISTRY entry's base_url matches the constant."""
        lm_studio_entry = REGISTRY.get("lm_studio")
        assert lm_studio_entry is not None, "lm_studio key missing from REGISTRY"
        assert lm_studio_entry["base_url"] == _LM_STUDIO_BASE_URL

    def test_module_exports_registry(self):
        """REGISTRY is a non-empty dict — module imported and executed correctly."""
        assert isinstance(REGISTRY, dict)
        assert len(REGISTRY) > 0
