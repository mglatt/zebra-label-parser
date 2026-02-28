from __future__ import annotations

from fastapi import APIRouter, Request

from app.services.print_service import get_available_printers

router = APIRouter(prefix="/api/printers", tags=["printers"])


@router.get("")
async def list_printers(request: Request):
    settings = request.app.state.settings
    printers = get_available_printers(cups_server=settings.cups_server)
    return {"printers": printers, "default": settings.printer_name}
