import os

from fastapi import APIRouter, Request

from app.services.print_service import get_available_printers

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health():
    return {"status": "ok"}


@router.get("/api/debug")
async def debug(request: Request):
    """Temporary endpoint to diagnose config issues."""
    settings = request.app.state.settings
    printers = []
    error = None
    try:
        printers = get_available_printers(cups_server=settings.cups_server)
    except Exception as exc:
        error = str(exc)
    return {
        "env": {
            "ZLP_CUPS_SERVER": os.environ.get("ZLP_CUPS_SERVER"),
            "ZLP_PRINTER_NAME": os.environ.get("ZLP_PRINTER_NAME"),
            "ZLP_ANTHROPIC_API_KEY": "set" if os.environ.get("ZLP_ANTHROPIC_API_KEY") else None,
        },
        "settings": {
            "cups_server": settings.cups_server,
            "printer_name": settings.printer_name,
            "label_dpi": settings.label_dpi,
        },
        "printers": printers,
        "error": error,
    }
