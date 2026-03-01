from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import health, labels, printers

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
_STATIC = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    settings = get_settings()

    logger.info("=== Zebra Label Parser settings ===")
    logger.info("  cups_server:  %r", settings.cups_server)
    logger.info("  printer_name: %r", settings.printer_name)
    logger.info("  label_dpi:    %s", settings.label_dpi)
    logger.info("  label_size:   %sx%s inches", settings.label_width_inches, settings.label_height_inches)

    app = FastAPI(title="Zebra Label Parser", version="0.2.0")
    app.state.settings = settings

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.info("%s %s", request.method, request.url.path)
        response = await call_next(request)
        return response

    app.include_router(health.router)
    app.include_router(labels.router)
    app.include_router(printers.router)

    app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")

    return app


app = create_app()
