from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import health, labels, printers

_STATIC = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="Zebra Label Parser", version="0.1.0")
    app.state.settings = settings

    app.include_router(health.router)
    app.include_router(labels.router)
    app.include_router(printers.router)

    app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")

    return app


app = create_app()
