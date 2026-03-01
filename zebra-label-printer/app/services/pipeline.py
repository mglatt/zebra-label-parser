"""Orchestrate the full label processing pipeline."""
from __future__ import annotations

import base64
import io
import logging
import time

from PIL import Image

from app.config import Settings
from app.services.image_processor import prepare_label_image
from app.services.label_extractor import extract_label_region
from app.services.pdf_renderer import get_page_count, render_pdf_page
from app.services.print_service import print_zpl
from app.services.zpl_generator import image_to_zpl_ascii

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
_PDF_EXTENSIONS = {".pdf"}


def _detect_file_type(filename: str, data: bytes) -> str:
    """Detect whether the file is a PDF or image."""
    lower = filename.lower()
    for ext in _PDF_EXTENSIONS:
        if lower.endswith(ext):
            return "pdf"
    for ext in _IMAGE_EXTENSIONS:
        if lower.endswith(ext):
            return "image"
    # Sniff magic bytes
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image"
    if data[:2] in (b"\xff\xd8",):  # JPEG
        return "image"
    return "image"  # default to image, PIL will error if it's not


async def process_and_print(
    file_bytes: bytes,
    filename: str,
    settings: Settings,
    printer_name: str,
    scale_pct: int = 100,
) -> dict:
    """Run the full pipeline: ingest → extract → process → ZPL → print."""
    stages: list[dict] = []
    t0 = time.monotonic()

    def stage(name: str, detail: str = ""):
        elapsed = round(time.monotonic() - t0, 2)
        stages.append({"name": name, "detail": detail, "elapsed_s": elapsed})
        logger.info("Stage: %s %s (%.2fs)", name, detail, elapsed)

    try:
        # 1. Detect file type and load/render image
        file_type = _detect_file_type(filename, file_bytes)
        stage("detect", f"type={file_type}")

        if file_type == "pdf":
            page_count = get_page_count(file_bytes)

            if page_count == 1:
                # Single-page PDF — current behaviour
                image = render_pdf_page(file_bytes, page=0, dpi=300)
                stage("render", f"page 1 of 1, {image.width}x{image.height}")

                extracted = await extract_label_region(
                    image,
                    api_key=settings.anthropic_api_key,
                    model=settings.claude_model,
                )
                if extracted is not image:
                    stage("extract", f"cropped to {extracted.width}x{extracted.height}")
                else:
                    stage("extract", "full page (no crop)")
            else:
                # Multi-page PDF — scan pages for the first label
                logger.info("Multi-page PDF: scanning %d page(s)", page_count)
                extracted = None
                page_0_image = None

                for page_num in range(page_count):
                    page_image = render_pdf_page(file_bytes, page=page_num, dpi=300)
                    if page_num == 0:
                        page_0_image = page_image
                    stage("render", f"page {page_num + 1} of {page_count}, "
                          f"{page_image.width}x{page_image.height}")

                    result = await extract_label_region(
                        page_image,
                        api_key=settings.anthropic_api_key,
                        model=settings.claude_model,
                        strict=True,
                    )
                    if result is not None:
                        extracted = result
                        stage("extract", f"label found on page {page_num + 1}, "
                              f"{extracted.width}x{extracted.height}")
                        break
                    stage("extract", f"no label on page {page_num + 1}")

                if extracted is None:
                    # No page had a confident detection — fall back to
                    # page 0 with full heuristic fallbacks (same as before
                    # multi-page support existed).
                    logger.info("No label found on any page, falling back to page 1")
                    extracted = await extract_label_region(
                        page_0_image,
                        api_key=settings.anthropic_api_key,
                        model=settings.claude_model,
                        strict=False,
                    )
                    stage("extract", f"fallback to page 1, "
                          f"{extracted.width}x{extracted.height}")
        else:
            image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
            stage("load", f"{image.width}x{image.height}")

            extracted = await extract_label_region(
                image,
                api_key=settings.anthropic_api_key,
                model=settings.claude_model,
            )
            if extracted is not image:
                stage("extract", f"cropped to {extracted.width}x{extracted.height}")
            else:
                stage("extract", "full page (no crop)")

        # 3. Prepare label image (resize, monochrome, dither)
        label = prepare_label_image(
            extracted,
            width=settings.label_width_px,
            height=settings.label_height_px,
            scale_pct=scale_pct,
        )
        stage("process", f"{label.width}x{label.height} mono @ {scale_pct}%")

        # Encode preview PNG for the frontend
        buf = io.BytesIO()
        label.save(buf, format="PNG")
        preview_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        # 4. Generate ZPL (ASCII hex for maximum printer compatibility)
        zpl = image_to_zpl_ascii(label)
        stage("zpl", f"{len(zpl)} bytes (ascii)")

        # 5. Print
        result = print_zpl(zpl, printer_name, cups_server=settings.cups_server)
        if result["success"]:
            stage("print", f"job {result.get('job_id', '?')}")
        else:
            stage("print", f"FAILED: {result.get('error', 'unknown')}")

        return {
            "success": result["success"],
            "stages": stages,
            "print_result": result,
            "preview_base64": preview_b64,
            "total_time_s": round(time.monotonic() - t0, 2),
        }

    except Exception as e:
        logger.exception("Pipeline failed")
        stage("error", str(e))
        return {
            "success": False,
            "stages": stages,
            "error": str(e),
            "total_time_s": round(time.monotonic() - t0, 2),
        }
