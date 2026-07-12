"""Shared test helpers for server route tests.

Provides ``make_configured_app`` — a factory that creates a FastAPI app with a
minimal no-op sanitizer injected into ``app.state.sanitization``, bypassing
the lifespan startup (LLM provider probe) while satisfying the
``SanitizationASGIMiddleware`` fail-closed guard.

These helpers are consumed by the top-level test files
(``tests/test_server_*.py``, ``tests/test_workflow_editor_routes.py``).
The ``tests/server/conftest.py`` file re-uses the same factory for its pytest
fixtures so all route tests stay in sync.

DO NOT add an ``autouse`` pytest fixture here — that would break
``tests/server/test_sanitization_middleware.py``, which explicitly tests
that a None sanitizer state triggers HTTP 503.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from agentic_v2.contracts.sanitization import Classification, SanitizationResult
from agentic_v2.core.tenant import TenantContext, get_tenant_context
from agentic_v2.server.app import create_app

#: Shared fake tenant used by all server route tests.
FAKE_TENANT = TenantContext(tenant_id="default", source="default")


class _PassThroughSanitizer:
    """Minimal sanitizer that always returns CLEAN — no detection, no blocking.

    Used in route-shape tests where we need requests to reach route
    handlers without running the real sanitization pipeline.
    """

    async def process(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> SanitizationResult:
        return SanitizationResult(
            classification=Classification.CLEAN,
            findings=(),
            sanitized_text=text,
            original_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            timestamp=datetime.now(UTC),
            detector_versions={},
        )


def make_configured_app():
    """Create a ``FastAPI`` app with a no-op sanitizer and tenant override injected.

    This bypasses:
    - The lifespan startup (LLM provider probe) by injecting a no-op sanitizer
      into ``app.state.sanitization``, satisfying the
      ``SanitizationASGIMiddleware`` fail-closed guard.
    - The ``get_tenant_context`` FastAPI dependency by overriding it to return
      a stable default-tenant ``TenantContext``, so route handlers that access
      ``tenant.tenant_id`` / ``tenant.source`` work without a live HTTP request
      carrying OIDC claims or ``X-Tenant-ID`` headers.
    """
    app = create_app()
    app.state.sanitization = _PassThroughSanitizer()
    app.dependency_overrides[get_tenant_context] = lambda: FAKE_TENANT
    return app
