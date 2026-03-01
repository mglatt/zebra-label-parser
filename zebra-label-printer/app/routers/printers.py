from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.services.print_service import get_available_printers

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/printers", tags=["printers"])

_STATE_NAMES = {3: "idle", 4: "processing", 5: "stopped"}


@router.get("")
async def list_printers(request: Request):
    settings = request.app.state.settings
    logger.info("Listing printers (cups_server=%r)", settings.cups_server)
    printers = get_available_printers(cups_server=settings.cups_server)
    logger.info("Found %d printer(s): %s", len(printers), [p["name"] for p in printers])

    for p in printers:
        p["state_name"] = _STATE_NAMES.get(p.get("state"), "unknown")

    return {"printers": printers, "default": settings.printer_name}
