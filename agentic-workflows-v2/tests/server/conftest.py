"""Shared fixtures for tests/server/ route tests.

Provides a ``configured_app`` factory and a ``client`` fixture that inject a
minimal no-op sanitization detector into ``app.state.sanitization`` so that
the ``SanitizationASGIMiddleware`` admits requests without running the full
lifespan (which probes LLM providers and requires API keys).

IMPORTANT: This conftest does NOT use ``autouse=True``.  The
``test_sanitization_middleware.py`` tests must remain free to construct their
own apps without sanitization state and assert the resulting 503 / 500 —
those tests must NOT pick up this fixture automatically.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests._server_test_helpers import make_configured_app  # noqa: F401 (re-exported)


@pytest.fixture()
def configured_app():
    """Pytest fixture: a ``FastAPI`` app with a no-op sanitizer."""
    return make_configured_app()


@pytest.fixture()
def client(configured_app):
    """Pytest fixture: a ``TestClient`` wrapping a sanitizer-configured app."""
    return TestClient(configured_app)
