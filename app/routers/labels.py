from __future__ import annotations

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from typing import Optional

from app.services.pipeline import process_and_print

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
