from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from app.services.pipeline import process_and_print

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/labels", tags=["labels"])


@router.post("/print")
async def print_label(
    request: Request,
    file: UploadFile = File(...),
    printer: Optional[str] = Form(None),
):
    settings = request.app.state.settings
    printer_name = printer or settings.printer_name

    if not printer_name:
        raise HTTPException(status_code=400, detail="No printer specified")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    result = await process_and_print(
        file_bytes=contents,
        filename=file.filename or "upload",
        settings=settings,
        printer_name=printer_name,
    )
    return result


class WebhookPayload(BaseModel):
    """Payload for the webhook endpoint, used by HA automations and phone share."""
    file_path: Optional[str] = None
    file_base64: Optional[str] = None
    filename: Optional[str] = None
    printer: Optional[str] = None


@router.post("/webhook")
async def webhook_print(request: Request, payload: WebhookPayload):
    """Print a label from a file path or base64-encoded data.

    Designed for Home Assistant automations (e.g., Folder Watcher,
    Companion App share, or any webhook-driven workflow).

    Accepts either:
    - file_path: absolute path to a file on disk (e.g., from Folder Watcher)
    - file_base64: base64-encoded file data (e.g., from Companion App share)
    """
    settings = request.app.state.settings
    printer_name = payload.printer or settings.printer_name

    if not printer_name:
        raise HTTPException(status_code=400, detail="No printer specified")

    if payload.file_path:
        path = Path(payload.file_path)
        if not path.is_file():
            raise HTTPException(status_code=400, detail=f"File not found: {payload.file_path}")
        contents = path.read_bytes()
        filename = payload.filename or path.name
    elif payload.file_base64:
        try:
            contents = base64.b64decode(payload.file_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64 data")
        filename = payload.filename or "shared-label"
    else:
        raise HTTPException(status_code=400, detail="Provide either file_path or file_base64")

    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    logger.info("Webhook print: %s (%d bytes) -> %s", filename, len(contents), printer_name)

    result = await process_and_print(
        file_bytes=contents,
        filename=filename,
        settings=settings,
        printer_name=printer_name,
    )
    return result
