"""Health check endpoint for the Agentic server.

Provides ``GET /api/health`` -- a lightweight liveness probe that
returns a static ``{"status": "ok", "version": "0.1.0"}`` response.
No authentication is required (listed in public prefixes in
:mod:`~agentic_v2.server.auth`).
"""

from __future__ import annotations

from fastapi import APIRouter

from ..models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check if server is alive."""
    return HealthResponse()
