"""Render PDF pages to PIL images using PyMuPDF."""
from __future__ import annotations

import io

import fitz  # PyMuPDF
from PIL import Image


def render_pdf_page(pdf_bytes: bytes, page: int = 0, dpi: int = 300) -> Image.Image:
    """Render a single PDF page to an RGB PIL Image at the given DPI."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if page >= len(doc):
        raise ValueError(f"Page {page} does not exist (document has {len(doc)} pages)")

    pg = doc[page]
    zoom = dpi / 72  # PDF default is 72 DPI
    mat = fitz.Matrix(zoom, zoom)
    pix = pg.get_pixmap(matrix=mat, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    doc.close()
    return img.convert("RGB")


def get_page_count(pdf_bytes: bytes) -> int:
    """Return the number of pages in a PDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    count = len(doc)
    doc.close()
    return count


def get_page_size_inches(pdf_bytes: bytes, page: int = 0) -> tuple[float, float]:
    """Return the (width, height) of a PDF page in inches."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    count = len(doc)
    if page >= count:
        doc.close()
        raise ValueError(f"Page {page} does not exist (document has {count} pages)")
    rect = doc[page].rect
    doc.close()
    return rect.width / 72.0, rect.height / 72.0
