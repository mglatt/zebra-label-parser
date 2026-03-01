import os

from fastapi import APIRouter, Request

from app.services.print_service import get_available_printers

router = APIRouter(tags=["health"])

_PRINTER_STATE_NAMES = {
    3: "idle",
    4: "processing",
    5: "stopped",
}


@router.get("/api/health")
async def health(request: Request):
    settings = request.app.state.settings
    printers = []
    cups_ok = False
    try:
        printers = get_available_printers(cups_server=settings.cups_server)
        cups_ok = True
    except Exception:
        pass

    status = "ok" if cups_ok else "degraded"
    return {"status": status, "cups_reachable": cups_ok, "printer_count": len(printers)}


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
