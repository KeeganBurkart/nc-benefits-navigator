"""FastAPI application factory for the NC Benefits Navigator.

Usage::

    from server.app import create_app
    app = create_app()

    # or run directly:
    # uvicorn server.app:app

Behaviour
---------
- Routes are mounted from server.routes.
- web/dist is served statically at / if the directory exists; otherwise a
  warning is logged so the server boots in dev/test without the built UI.
  SPA fallback: any non-API, non-healthz GET that doesn't map to a static
  file is served index.html.
- demo_mode=True (NAV_DEMO_MODE=1) adds ``X-Demo-Mode: 1`` to all responses
  via middleware.
- No CORS, no database, no auth.  Deploy behind the org's own access control.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from server.config import get_settings
from server.routes import router

logger = logging.getLogger(__name__)

_WEB_DIST = Path(__file__).parent.parent / "web" / "dist"


# ---------------------------------------------------------------------------
# Demo-mode middleware
# ---------------------------------------------------------------------------


class _DemoHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Demo-Mode"] = "1"
        return response


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(title="NC Benefits Navigator", version="1.0.0")

    settings = get_settings()

    # --- Demo-mode header ---
    if settings.demo_mode:
        app.add_middleware(_DemoHeaderMiddleware)

    # --- API routes ---
    app.include_router(router)

    # --- Static / SPA ---
    if _WEB_DIST.is_dir():
        _mount_spa(app)
    else:
        logger.warning(
            "web/dist not found — skipping static file serving. "
            "Run `npm run build` in web/ to enable the UI."
        )

    return app


def _mount_spa(app: FastAPI) -> None:
    """Mount web/dist as static files with an SPA fallback for unknown paths."""
    # Serve known static files normally.
    app.mount("/assets", StaticFiles(directory=str(_WEB_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str):
        # Pass through API and healthz paths — they're handled by the router.
        if full_path.startswith("api/") or full_path == "healthz":
            return JSONResponse({"error": "not found"}, status_code=404)
        # Return the static file if it exists; otherwise serve index.html.
        candidate = _WEB_DIST / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        index = _WEB_DIST / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        return JSONResponse({"error": "not found"}, status_code=404)


# ---------------------------------------------------------------------------
# Module-level app instance for uvicorn
# ---------------------------------------------------------------------------

app = create_app()
