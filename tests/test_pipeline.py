from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.config import Settings
from app.services.pipeline import process_and_print, _detect_file_type


def test_detect_pdf_by_extension():
    assert _detect_file_type("label.pdf", b"") == "pdf"


def test_detect_image_by_extension():
    assert _detect_file_type("label.png", b"") == "image"
    assert _detect_file_type("photo.jpg", b"") == "image"


def test_detect_pdf_by_magic():
    assert _detect_file_type("unknown", b"%PDF-1.4 ...") == "pdf"


def test_detect_png_by_magic():
    assert _detect_file_type("unknown", b"\x89PNG\r\n\x1a\n...") == "image"


@pytest.mark.asyncio
async def test_pipeline_with_image(sample_image):
    """Test pipeline with an image file (no PDF rendering)."""
    import io

    buf = io.BytesIO()
    sample_image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    settings = Settings(anthropic_api_key=None, printer_name="TestPrinter")

    with patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 1, "printer": "TestPrinter"}

        result = await process_and_print(png_bytes, "test.png", settings, "TestPrinter")

        assert result["success"] is True
        assert any(s["name"] == "load" for s in result["stages"])
        assert any(s["name"] == "zpl" for s in result["stages"])
        mock_print.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_with_pdf(sample_pdf_bytes):
    settings = Settings(anthropic_api_key=None, printer_name="TestPrinter")

    with patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 2, "printer": "TestPrinter"}

        result = await process_and_print(sample_pdf_bytes, "label.pdf", settings, "TestPrinter")

        assert result["success"] is True
        assert any(s["name"] == "render" for s in result["stages"])


@pytest.mark.asyncio
async def test_pipeline_print_failure(sample_image):
    import io

    buf = io.BytesIO()
    sample_image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    settings = Settings(anthropic_api_key=None, printer_name="TestPrinter")

    with patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": False, "error": "printer offline"}

        result = await process_and_print(png_bytes, "test.png", settings, "TestPrinter")

        assert result["success"] is False
