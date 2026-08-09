"""Single-page application (SPA) static file serving helpers.

Mounts the built React frontend under ``ui/dist/`` when it exists, serving
static assets at ``/assets/`` and falling back to ``index.html`` for all
remaining paths to support client-side routing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agentic_v2.utils.path_safety import ensure_within_base

logger = logging.getLogger(__name__)

# Built frontend assets directory
UI_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "ui" / "dist"
UI_DIST_DIR_RESOLVED = UI_DIST_DIR.resolve()


def _mount_spa(app: FastAPI) -> None:
    """Mount static assets and the SPA fallback route for the built React UI."""
    # Serve static assets (JS, CSS, etc.)
    app.mount(
        "/assets", StaticFiles(directory=str(UI_DIST_DIR / "assets")), name="assets"
    )

    # SPA fallback: serve index.html for all non-API, non-asset routes
    index_html = UI_DIST_DIR / "index.html"

    @app.get("/{path:path}")
    async def spa_fallback(request: Request, path: str):
        # Serve real files from dist/, but prevent directory traversal.
        if path:
            try:
                candidate = ensure_within_base(
                    UI_DIST_DIR_RESOLVED / path, UI_DIST_DIR_RESOLVED
                )
                if candidate.is_file():
                    return FileResponse(str(candidate))
            except (ValueError, OSError):
                pass
        return FileResponse(index_html)

    logger.info("Serving UI from %s", UI_DIST_DIR)
