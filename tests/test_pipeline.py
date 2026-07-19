from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.config import Settings
from app.services.pipeline import process_and_print, _detect_file_type, _is_label_sized_page


def test_detect_pdf_by_extension():
    assert _detect_file_type("label.pdf", b"") == "pdf"


def test_detect_image_by_extension():
    assert _detect_file_type("label.png", b"") == "image"
    assert _detect_file_type("photo.jpg", b"") == "image"


def test_detect_pdf_by_magic():
    assert _detect_file_type("unknown", b"%PDF-1.4 ...") == "pdf"


def test_detect_png_by_magic():
    assert _detect_file_type("unknown", b"\x89PNG\r\n\x1a\n...") == "image"


def test_is_label_sized_page():
    assert _is_label_sized_page(4.0, 6.0) is True   # standard 4x6 thermal
    assert _is_label_sized_page(6.0, 4.0) is True   # landscape
    assert _is_label_sized_page(4.0, 8.0) is True   # 4x8 doc-tab stock
    assert _is_label_sized_page(8.5, 11.0) is False  # letter page
    assert _is_label_sized_page(8.5, 5.5) is False   # half letter
    assert _is_label_sized_page(8.27, 11.69) is False  # A4


@pytest.mark.asyncio
async def test_pipeline_label_sized_pdf_skips_vision(sample_pdf_bytes):
    """A 4x6 PDF page IS the label — Vision must not be called, the page is
    used whole."""
    settings = Settings(anthropic_api_key="test-key", printer_name="TestPrinter")

    with patch("app.services.pipeline.extract_label_region") as mock_extract, \
         patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 9, "printer": "TestPrinter"}

        result = await process_and_print(sample_pdf_bytes, "label.pdf", settings, "TestPrinter")

        assert result["success"] is True
        mock_extract.assert_not_called()
        extract_stages = [s for s in result["stages"] if s["name"] == "extract"]
        assert any("used in full" in s["detail"] for s in extract_stages)


@pytest.mark.asyncio
async def test_pipeline_multipage_label_sized_page_used_whole(sample_multipage_pdf_bytes):
    """In a multi-page PDF, a label-sized page short-circuits the strict
    Vision scan and is used whole."""
    settings = Settings(anthropic_api_key="test-key", printer_name="TestPrinter")

    async def mock_extract(image, api_key, model, strict=False, **kwargs):
        return None  # letter pages: no label

    with patch("app.services.pipeline.extract_label_region", side_effect=mock_extract), \
         patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 10, "printer": "TestPrinter"}

        result = await process_and_print(
            sample_multipage_pdf_bytes, "multipage.pdf", settings, "TestPrinter"
        )

        assert result["success"] is True
        extract_stages = [s for s in result["stages"] if s["name"] == "extract"]
        assert any("label-sized page 2" in s["detail"] for s in extract_stages)


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
        assert "preview_base64" in result
        mock_print.assert_called_once()


@pytest.mark.asyncio
async def test_preview_base64_is_valid_png(sample_image):
    """Pipeline result includes a valid base64-encoded PNG preview."""
    import base64
    import io

    buf = io.BytesIO()
    sample_image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    settings = Settings(anthropic_api_key=None, printer_name="TestPrinter")

    with patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 1, "printer": "TestPrinter"}

        result = await process_and_print(png_bytes, "test.png", settings, "TestPrinter")

        raw = base64.b64decode(result["preview_base64"])
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


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

    async def mock_extract(image, api_key, model, strict=False, **kwargs):
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
async def test_pipeline_multipage_fallback(letter_multipage_pdf_bytes):
    """Multi-page PDF (all letter pages): no label found → falls back to
    page 1 non-strict."""
    settings = Settings(anthropic_api_key="test-key", printer_name="TestPrinter")

    async def mock_extract(image, api_key, model, strict=False, **kwargs):
        if strict:
            return None  # Strict: no label found on any page
        return image  # Non-strict fallback: return image as-is

    with patch("app.services.pipeline.extract_label_region", side_effect=mock_extract), \
         patch("app.services.pipeline.print_zpl") as mock_print:
        mock_print.return_value = {"success": True, "job_id": 5, "printer": "TestPrinter"}

        result = await process_and_print(
            letter_multipage_pdf_bytes, "multipage.pdf", settings, "TestPrinter"
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


# --- DPI estimation for uploaded images ---


def test_estimate_dpi_letter_page():
    from app.config import Settings
    from app.services.pipeline import _estimate_image_dpi

    s = Settings(anthropic_api_key=None)
    assert _estimate_image_dpi(2550, 3300, s) == pytest.approx(300.0)
    assert _estimate_image_dpi(1275, 1650, s) == pytest.approx(150.0)
    assert _estimate_image_dpi(3300, 2550, s) == pytest.approx(300.0)  # rotated


def test_estimate_dpi_label_shaped_image():
    from app.config import Settings
    from app.services.pipeline import _estimate_image_dpi

    s = Settings(anthropic_api_key=None)  # 4x6 default stock
    assert _estimate_image_dpi(1200, 1800, s) == pytest.approx(300.0)
    assert _estimate_image_dpi(812, 1218, s) == pytest.approx(203.0)


def test_estimate_dpi_unrecognized_shape_uses_default():
    from app.config import Settings
    from app.services.pipeline import _estimate_image_dpi

    s = Settings(anthropic_api_key=None)
    assert _estimate_image_dpi(1000, 1000, s) == 300
