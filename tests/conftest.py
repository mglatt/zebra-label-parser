from __future__ import annotations

import io

import fitz  # PyMuPDF
import pytest
from PIL import Image


@pytest.fixture
def sample_image() -> Image.Image:
    """A simple 200x300 test image with a black rectangle."""
    img = Image.new("RGB", (200, 300), (255, 255, 255))
    for x in range(50, 150):
        for y in range(75, 225):
            img.putpixel((x, y), (0, 0, 0))
    return img


@pytest.fixture
def sample_landscape_image() -> Image.Image:
    """A 400x200 landscape test image."""
    return Image.new("RGB", (400, 200), (128, 128, 128))


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """A minimal single-page PDF with text."""
    doc = fitz.open()
    page = doc.new_page(width=288, height=432)  # 4x6 inches at 72 DPI
    page.insert_text((72, 200), "SHIP TO:", fontsize=14)
    page.insert_text((72, 220), "John Doe", fontsize=12)
    page.insert_text((72, 240), "123 Main St", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def sample_multipage_pdf_bytes() -> bytes:
    """A 3-page PDF: instructions / shipping label / receipt."""
    doc = fitz.open()

    # Page 0: instructions (letter size 8.5x11 at 72 DPI)
    p0 = doc.new_page(width=612, height=792)
    p0.insert_text((72, 100), "INSTRUCTIONS", fontsize=18)
    p0.insert_text((72, 140), "1. Print the label on the next page", fontsize=12)
    p0.insert_text((72, 160), "2. Affix to package", fontsize=12)

    # Page 1: shipping label (4x6 at 72 DPI)
    p1 = doc.new_page(width=288, height=432)
    p1.insert_text((72, 100), "SHIP TO:", fontsize=14)
    p1.insert_text((72, 120), "John Doe", fontsize=12)
    p1.insert_text((72, 140), "123 Main St", fontsize=12)
    p1.insert_text((72, 200), "TRACKING: 1Z999AA10123456784", fontsize=10)

    # Page 2: receipt (letter size)
    p2 = doc.new_page(width=612, height=792)
    p2.insert_text((72, 100), "ORDER RECEIPT", fontsize=18)
    p2.insert_text((72, 140), "Item: Widget x1", fontsize=12)

    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def mono_image() -> Image.Image:
    """A small 16x8 monochrome test image for ZPL testing."""
    img = Image.new("1", (16, 8), color=1)  # all white
    # Draw a small black square
    for x in range(4, 12):
        for y in range(2, 6):
            img.putpixel((x, y), 0)  # black
    return img
