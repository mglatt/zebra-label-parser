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
async def test_pipeline_single_page_pdf_unchanged(sample_pdf_bytes):
    """Single-page PDF should render exactly once with no page-scan loop."""
    settings = Settings(anthropic_api_key=None, printer_name="TestPrinter")

    with patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 3, "printer": "TestPrinter"}

        result = await process_and_print(sample_pdf_bytes, "label.pdf", settings, "TestPrinter")

        assert result["success"] is True
        render_stages = [s for s in result["stages"] if s["name"] == "render"]
        assert len(render_stages) == 1
        assert "page 1 of 1" in render_stages[0]["detail"]


@pytest.mark.asyncio
async def test_pipeline_multipage_finds_label(sample_multipage_pdf_bytes):
    """Multi-page PDF: label found on page 2 via strict scan."""
    settings = Settings(anthropic_api_key="test-key", printer_name="TestPrinter")

    call_count = 0

    async def mock_extract(image, api_key, model, strict=False):
        nonlocal call_count
        call_count += 1
        if strict and call_count <= 1:
            return None  # Page 0: no label
        return image  # Page 1 (or fallback): found label

    with patch("app.services.pipeline.extract_label_region", side_effect=mock_extract), \
         patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 4, "printer": "TestPrinter"}

        result = await process_and_print(
            sample_multipage_pdf_bytes, "multipage.pdf", settings, "TestPrinter"
        )

        assert result["success"] is True
        extract_stages = [s for s in result["stages"] if s["name"] == "extract"]
        assert any("page 2" in s["detail"] for s in extract_stages)


@pytest.mark.asyncio
async def test_pipeline_multipage_fallback(sample_multipage_pdf_bytes):
    """Multi-page PDF: no label on any page → falls back to page 1 non-strict."""
    settings = Settings(anthropic_api_key="test-key", printer_name="TestPrinter")

    async def mock_extract(image, api_key, model, strict=False):
        if strict:
            return None  # Strict: no label found on any page
        return image  # Non-strict fallback: return image as-is

    with patch("app.services.pipeline.extract_label_region", side_effect=mock_extract), \
         patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 5, "printer": "TestPrinter"}

        result = await process_and_print(
            sample_multipage_pdf_bytes, "multipage.pdf", settings, "TestPrinter"
        )

        assert result["success"] is True
        extract_stages = [s for s in result["stages"] if s["name"] == "extract"]
        assert any("fallback" in s["detail"] for s in extract_stages)


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
