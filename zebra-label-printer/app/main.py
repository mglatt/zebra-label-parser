from __future__ import annotations

import logging
from pathlib import Path

import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import health, labels, printers

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
_STATIC = Path(__file__).parent / "static"


def _is_allowed(request: Request, api_key: str) -> bool:
    """Check if a request should be allowed through the API key gate."""
    # HA ingress proxy sets this header — already authenticated by HA
    if request.headers.get("x-ingress-path"):
        return True
    # Health endpoint is always public
    if request.url.path == "/api/health":
        return True
    # Check X-API-Key header or ?api_key= query param
    provided = request.headers.get("x-api-key") or request.query_params.get("api_key")
    return bool(provided) and hmac.compare_digest(provided, api_key)


def create_app() -> FastAPI:
    settings = get_settings()

    logger.info("=== Zebra Label Parser settings ===")
    logger.info("  cups_server:  %r", settings.cups_server)
    logger.info("  printer_name: %r", settings.printer_name)
    logger.info("  label_dpi:    %s", settings.label_dpi)
    logger.info("  label_size:   %sx%s inches", settings.label_width_inches, settings.label_height_inches)

    app = FastAPI(title="Zebra Label Parser", version="0.5.7")
    app.state.settings = settings

    @app.middleware("http")
    async def check_api_key(request: Request, call_next):
        logger.info("%s %s", request.method, request.url.path)
        api_key = request.app.state.settings.api_key
        if api_key and not _is_allowed(request, api_key):
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
        return await call_next(request)

    app.include_router(health.router)
    app.include_router(labels.router)
    app.include_router(printers.router)

    app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")

    return app


app = create_app()
