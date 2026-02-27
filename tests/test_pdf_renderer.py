from app.services.pdf_renderer import get_page_count, render_pdf_page


def test_render_pdf_page(sample_pdf_bytes):
    img = render_pdf_page(sample_pdf_bytes, page=0, dpi=150)
    assert img.mode == "RGB"
    assert img.width > 0
    assert img.height > 0


def test_render_pdf_page_high_dpi(sample_pdf_bytes):
    img_lo = render_pdf_page(sample_pdf_bytes, page=0, dpi=72)
    img_hi = render_pdf_page(sample_pdf_bytes, page=0, dpi=300)
    # Higher DPI should produce larger image
    assert img_hi.width > img_lo.width
    assert img_hi.height > img_lo.height


def test_get_page_count(sample_pdf_bytes):
    assert get_page_count(sample_pdf_bytes) == 1


def test_render_invalid_page(sample_pdf_bytes):
    import pytest
    with pytest.raises(ValueError, match="does not exist"):
        render_pdf_page(sample_pdf_bytes, page=5)
