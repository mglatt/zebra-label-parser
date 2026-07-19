from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

import numpy as np

from app.services.label_extractor import (
    extract_label_region,
    _content_fills_label_frame,
    _expand_to_whitespace,
    _is_letter_size,
    _letter_size_fallback_crop,
    _parse_bbox,
    _tighten_to_content,
    _validate_and_crop,
)


def _bare_label_image(width=1800, height=1200):
    """A bare landscape label: ink spans nearly the full frame, including a
    rotated address column on the left (UPS/Amazon return label layout).
    Text/barcode lines are drawn sparsely — real labels are mostly white."""
    arr = np.full((height, width), 255, dtype=np.uint8)
    arr[40:1160:6, 40:480] = 0     # rotated address column (left ~25%)
    arr[40:1160:4, 520:1760] = 0   # barcodes / tracking / MaxiCode area
    return Image.fromarray(arr)


# --- _parse_bbox tests ---


def test_parse_bbox_valid():
    text = '{"found": true, "x1": 10, "y1": 20, "x2": 200, "y2": 300}'
    result = _parse_bbox(text, 800, 1000)
    assert result is not None
    assert result["x1"] == 10


def test_parse_bbox_percentage_keys():
    text = '{"x1_pct": 5, "y1_pct": 10, "x2_pct": 80, "y2_pct": 95}'
    result = _parse_bbox(text, 1000, 1000)
    assert result is not None
    assert result["x1"] == 50  # 5% of 1000, snapped to grid
    assert result["y1"] == 100  # 10% of 1000


def test_parse_bbox_with_surrounding_text():
    text = 'Here is the result: {"found": true, "x1": 0, "y1": 0, "x2": 100, "y2": 200} done.'
    result = _parse_bbox(text, 800, 1000)
    assert result is not None


def test_parse_bbox_not_found():
    text = '{"found": false}'
    result = _parse_bbox(text, 800, 1000)
    assert result is None


def test_parse_bbox_invalid_json():
    assert _parse_bbox("not json at all", 800, 1000) is None


def test_parse_bbox_missing_keys():
    text = '{"found": true, "x1": 10}'
    assert _parse_bbox(text, 800, 1000) is None


def test_parse_bbox_no_label():
    text = '{"no_label": true}'
    result = _parse_bbox(text, 1000, 1000)
    assert result is not None
    assert result.get("no_label") is True


def test_parse_bbox_no_label_false():
    """When no_label is false, should try to parse as bbox and fail (missing keys)."""
    text = '{"no_label": false}'
    result = _parse_bbox(text, 1000, 1000)
    assert result is None  # no_label=false, and no bbox keys


def test_parse_bbox_clamps_pct_overshoot():
    """Slightly out-of-range percentages are clamped, not rejected."""
    text = '{"x1_pct": -5, "y1_pct": 2, "x2_pct": 105, "y2_pct": 99}'
    result = _parse_bbox(text, 1000, 1000)
    assert result is not None
    assert result["x1"] == 0
    assert result["x2"] == 1000
    assert result["y2"] <= 1000


def test_parse_bbox_fractional_pct():
    """0-1 fractional coordinates are rescaled to percentages."""
    text = '{"x1_pct": 0.05, "y1_pct": 0.1, "x2_pct": 0.8, "y2_pct": 0.95}'
    result = _parse_bbox(text, 1000, 1000)
    assert result is not None
    assert result["x1"] == 50
    assert result["y1"] == 100
    assert result["x2"] == 800
    assert result["y2"] == 950


def test_parse_bbox_non_numeric():
    text = '{"x1_pct": "left", "y1_pct": 0, "x2_pct": 80, "y2_pct": 95}'
    assert _parse_bbox(text, 1000, 1000) is None


# --- _validate_and_crop tests ---


def test_validate_and_crop_valid():
    img = Image.new("RGB", (800, 1000))
    result = _validate_and_crop({"x1": 50, "y1": 50, "x2": 400, "y2": 600}, img)
    assert result is not None
    # Safety margin expands the crop beyond the raw bbox
    assert result.width > (400 - 50)
    assert result.height > (600 - 50)


def test_validate_and_crop_margin_clamped_to_bounds():
    """Margin must not produce negative coords or exceed image dimensions."""
    img = Image.new("RGB", (800, 1000))
    # Bbox near top-left corner
    result = _validate_and_crop({"x1": 5, "y1": 5, "x2": 400, "y2": 600}, img)
    assert result is not None
    # Crop starts at 0 (clamped), not negative
    assert result.width >= 400
    assert result.height >= 600


def test_validate_and_crop_margin_near_edge():
    """Bbox near right/bottom edge: margin clamped to image size."""
    img = Image.new("RGB", (800, 1200))
    result = _validate_and_crop({"x1": 100, "y1": 100, "x2": 795, "y2": 1195}, img)
    assert result is not None
    # x2+margin clamped to 800, y2+margin clamped to 1200
    assert result.width <= 800
    assert result.height <= 1200


def test_validate_and_crop_too_small():
    img = Image.new("RGB", (200, 200))
    # Bbox is only 5% of image area
    result = _validate_and_crop({"x1": 0, "y1": 0, "x2": 20, "y2": 25}, img)
    assert result is None


def test_validate_and_crop_inverted():
    img = Image.new("RGB", (200, 200))
    result = _validate_and_crop({"x1": 100, "y1": 100, "x2": 50, "y2": 50}, img)
    assert result is None


def test_validate_and_crop_out_of_bounds_clamped():
    """Out-of-bounds coords are clamped to the image, not rejected.

    After clamping, this bbox covers the full frame, so the original
    image is returned whole.
    """
    img = Image.new("RGB", (200, 300))
    result = _validate_and_crop({"x1": -50, "y1": 0, "x2": 200, "y2": 300}, img)
    assert result is img


def test_validate_and_crop_full_coverage_returns_image():
    """A bbox covering >90% of the image means the image IS the label."""
    img = Image.new("RGB", (800, 1200), (255, 255, 255))
    result = _validate_and_crop({"x1": 0, "y1": 0, "x2": 800, "y2": 1200}, img)
    assert result is img


def test_validate_and_crop_trims_too_square_at_whitespace():
    """A too-square bbox is trimmed back to ~1.5 ratio along a clean
    whitespace line, excluding the return slip below the label."""
    # White letter page with a dense landscape label block and a separate
    # slip block below it, divided by a whitespace gap.
    arr = np.full((3300, 2550), 255, dtype=np.uint8)
    arr[850:2100, 150:2050] = 0  # label: 1900x1250 (~1.52 ratio)
    arr[2200:2380, 150:2050] = 0  # return slip below the gap
    img = Image.fromarray(arr)

    # Bbox spans label + slip: 2000x1600 → ratio 1.25 (too square)
    result = _validate_and_crop({"x1": 100, "y1": 800, "x2": 2100, "y2": 2400}, img)
    assert result is not None
    # Trimmed at the gap: slip excluded, label fully preserved
    assert result.height < 1450, f"Expected slip trimmed, got height {result.height}"
    assert result.height >= 1200, f"Expected full label kept, got height {result.height}"
    assert result.width >= 1850, f"Expected full label width, got {result.width}"


def test_validate_and_crop_no_trim_without_clean_cut():
    """A too-square bbox over dense content is NOT trimmed — cutting would
    slice through label content (e.g. a barcode)."""
    arr = np.full((3300, 2550), 255, dtype=np.uint8)
    arr[800:2400, 100:2100] = 0  # dense content fills the whole bbox
    img = Image.fromarray(arr)

    result = _validate_and_crop({"x1": 100, "y1": 800, "x2": 2100, "y2": 2400}, img)
    assert result is not None
    # No clean cut line exists → full 1600px of content must be preserved
    assert result.height >= 1590, f"Content was sliced: height {result.height}"


def test_validate_and_crop_expands_to_uncovered_barcode():
    """A bbox whose bottom edge slices through a barcode is grown until the
    edge sits on whitespace, recovering the clipped barcode."""
    arr = np.full((1400, 1000), 255, dtype=np.uint8)
    arr[200:880, 200:800] = 0    # address/content block
    arr[900:1050, 200:800] = 0   # tracking barcode at the bottom
    img = Image.fromarray(arr)

    # Bbox bottom edge (950) cuts through the barcode (900-1050)
    result = _validate_and_crop({"x1": 200, "y1": 200, "x2": 800, "y2": 950}, img)
    assert result is not None
    # Full content span is 200..1050 = 850px; without expansion the crop
    # would only reach ~970px from y=180 (≈790 of content).
    assert result.height >= 840, f"Barcode still clipped: height {result.height}"


def test_validate_and_crop_normal_ratio_untrimmed():
    """A bbox with a normal label ratio (~1.5) is not trimmed."""
    # Bbox: 2000 wide × 1333 tall → ratio 1.5 (correct for 6×4 label).
    img = Image.new("RGB", (2550, 3300))
    result = _validate_and_crop({"x1": 100, "y1": 800, "x2": 2100, "y2": 2133}, img)
    assert result is not None
    # Height should be the original bbox height + safety margins, not trimmed.
    # Raw height = 1333, margin_y = max(30, ~49) ≈ 49, so result ≈ 1333 + 2*49 ≈ 1431.
    assert result.height > 1350


# --- _tighten_to_content tests ---


def test_tighten_removes_sidebar_text():
    """Simulates an Amazon return label with rotated sidebar text.

    Layout (1000 wide x 700 tall):
    - Columns 0-59: scattered dark pixels (rotated "Return Auth Slip" text)
    - Columns 60-89: truly empty whitespace gap (30px wide, all white)
    - Columns 90-909: main label content (dense)
    - Columns 910-939: truly empty whitespace gap (30px wide, all white)
    - Columns 940-999: scattered dark pixels (rotated "Return Mailing Label")
    """
    img = Image.new("L", (1000, 700), 255)
    arr = np.array(img)

    # Left sidebar text: sparse dark pixels in columns 0-59
    for col in range(0, 60):
        for row in range(50, 650, 10):
            arr[row:row+3, col] = 0

    # Columns 60-89: leave as white (the gap)

    # Main label content: dense dark pixels in columns 90-909
    for col in range(90, 910):
        for row in range(20, 680, 5):
            arr[row:row+2, col] = 0

    # Columns 910-939: leave as white (the gap)

    # Right sidebar text: sparse dark pixels in columns 940-999
    for col in range(940, 1000):
        for row in range(50, 650, 10):
            arr[row:row+3, col] = 0

    img = Image.fromarray(arr)
    result = _tighten_to_content(img)

    # Should have trimmed the sidebars — width should be less than original
    assert result.width < 950, f"Expected width < 950, got {result.width}"
    # Main content (820 px) should be preserved
    assert result.width >= 820, f"Expected width >= 820, got {result.width}"


def test_tighten_no_change_when_no_gaps():
    """An image with content edge-to-edge should not be tightened."""
    img = Image.new("L", (400, 300), 255)
    arr = np.array(img)
    # Fill content across full width and height (no whitespace bands)
    for col in range(0, 400):
        for row in range(0, 300, 4):
            arr[row:row+2, col] = 0
    img = Image.fromarray(arr)
    result = _tighten_to_content(img)
    assert result.width == 400
    assert result.height == 300


def test_tighten_skips_small_images():
    """Images smaller than 200px should not be tightened."""
    img = Image.new("L", (100, 100), 255)
    result = _tighten_to_content(img)
    assert result.width == 100
    assert result.height == 100


def test_tighten_preserves_sparse_content():
    """Sparse address text should NOT be trimmed — it's valid label content.

    Simulates a label where the left side has sparse address text
    (some dark pixels in each column) rather than a truly empty gap.
    The tightening should NOT trim this area.
    """
    img = Image.new("L", (600, 400), 255)
    arr = np.array(img)
    # Left side: sparse text (like addresses) — 1-2% dark pixels per column
    # This should NOT be treated as whitespace
    for col in range(0, 150):
        for row in range(30, 370, 50):
            arr[row:row+4, col] = 0  # ~4/400 = 1% per column
    # Right side: dense barcode content
    for col in range(150, 600):
        for row in range(10, 390, 5):
            arr[row:row+2, col] = 0
    img = Image.fromarray(arr)
    result = _tighten_to_content(img)
    # Address columns have > 0.3% dark pixels, so they should NOT be trimmed
    assert result.width == 600, f"Expected width 600 (no trim), got {result.width}"


# --- _content_fills_label_frame tests ---


def test_content_fills_label_frame_bare_label():
    assert _content_fills_label_frame(_bare_label_image()) is True


def test_content_fills_label_frame_letter_page():
    """A letter-proportioned page never qualifies, even when full of ink."""
    arr = np.zeros((3300, 2550), dtype=np.uint8)
    assert _content_fills_label_frame(Image.fromarray(arr)) is False


def test_content_fills_label_frame_label_on_page_section():
    """Label-ratio frame but content in only one corner → not a bare label."""
    arr = np.full((1200, 1800), 255, dtype=np.uint8)
    arr[100:500, 100:700] = 0
    assert _content_fills_label_frame(Image.fromarray(arr)) is False


def test_content_fills_label_frame_dark_photo():
    """A mostly-dark image (photo on dark background) must go through Vision."""
    arr = np.full((1200, 1800), 30, dtype=np.uint8)
    assert _content_fills_label_frame(Image.fromarray(arr)) is False


# --- _expand_into_ink (via _validate_and_crop) tests ---


def test_validate_and_crop_recovers_rotated_address_column():
    """Reproduces the UPS/Amazon return label failure: Vision excludes the
    rotated address column, leaving a too-square bbox.  The bbox must grow
    back into the adjacent ink so the address block is framed."""
    # Letter page with the landscape label content at (300..2100, 800..2000)
    arr = np.full((3300, 2550), 255, dtype=np.uint8)
    arr[800:2000, 300:740] = 0     # rotated SHIP TO address column
    arr[800:2000, 780:2100] = 0    # barcode / tracking area
    img = Image.fromarray(arr)

    # Vision bbox excludes the address column: 1300x1200 → ratio 1.08
    result = _validate_and_crop({"x1": 800, "y1": 800, "x2": 2100, "y2": 2000}, img)
    assert result is not None
    # Full label is 1800 wide; without recovery the crop is ~1320 wide
    assert result.width >= 1790, f"Address column not recovered: width {result.width}"


def test_validate_and_crop_recovers_from_elongated_strip():
    """A bbox framing only a wide strip of the label (e.g. just the barcode
    band) grows vertically into the adjacent label content."""
    arr = np.full((3300, 2550), 255, dtype=np.uint8)
    arr[800:2000, 300:2100] = 0    # full label block: 1800x1200
    img = Image.fromarray(arr)

    # Bbox covers only the bottom 500px band: 1800x500 → ratio 3.6
    result = _validate_and_crop({"x1": 300, "y1": 1500, "x2": 2100, "y2": 2000}, img)
    assert result is not None
    assert result.height >= 1190, f"Label body not recovered: height {result.height}"


# --- _is_letter_size tests ---


def test_is_letter_size_portrait_and_landscape():
    assert _is_letter_size(2550, 3300) is True  # 300 DPI letter
    assert _is_letter_size(3300, 2550) is True  # rotated


def test_is_letter_size_rejects_other_shapes():
    assert _is_letter_size(1000, 1000) is False  # square
    assert _is_letter_size(1800, 1200) is False  # 4x6 label ratio
    assert _is_letter_size(1000, 1163) is False  # just below tolerance
    assert _is_letter_size(1000, 1425) is False  # just above tolerance


def test_is_letter_size_within_tolerance():
    assert _is_letter_size(1000, 1294) is True  # exact letter ratio


# --- _letter_size_fallback_crop tests ---


def test_letter_fallback_crop_portrait():
    """Portrait letter page: label + slack in the upper-left (50% x 58%)."""
    img = Image.new("RGB", (2550, 3300))
    result = _letter_size_fallback_crop(img)
    assert result.size == (
        int(2550 * 4.25 / 8.5),   # = 50% of page width
        int(3300 * 6.38 / 11.0),  # = 58% of page height
    )


def test_letter_fallback_crop_landscape():
    """Landscape letter page: rotated label + slack in the left 57%."""
    img = Image.new("RGB", (3300, 2550))
    result = _letter_size_fallback_crop(img)
    assert result.size == (
        int(3300 * 6.27 / 11.0),  # = 57% of page width
        int(2550 * 0.97),
    )


# --- _expand_to_whitespace tests ---


def test_expand_to_whitespace_grows_edge_off_ink():
    """An edge slicing through ink is pushed out to the nearest clean line."""
    arr = np.full((1000, 1000), 255, dtype=np.uint8)
    arr[300:700, 300:700] = 0
    dark = arr < 200

    x1, y1, x2, y2 = _expand_to_whitespace(dark, 300, 300, 700, 650)
    assert y2 >= 700, f"Edge still slices ink: y2={y2}"
    # Flush edges step out one line to whitespace; none may move inward
    assert x1 <= 300 and y1 <= 300 and x2 >= 700
    assert x1 >= 295 and y1 >= 295 and x2 <= 705


def test_expand_to_whitespace_growth_is_capped():
    """Growth stops at ~8% of the page even if the edge is still on ink."""
    arr = np.full((1000, 1000), 255, dtype=np.uint8)
    arr[300:900, 300:700] = 0
    dark = arr < 200

    _, _, _, y2 = _expand_to_whitespace(dark, 300, 300, 700, 650)
    max_dy = max(40, int(1000 * 0.08))
    assert y2 <= 650 + max_dy, f"Growth exceeded cap: y2={y2}"


# --- extract_label_region tests ---


@pytest.mark.asyncio
async def test_extract_bare_label_image_skips_vision():
    """A bare label image is used whole without calling the Vision API."""
    img = _bare_label_image().convert("RGB")

    mock_client = AsyncMock()
    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = await extract_label_region(img, api_key="test-key")
        assert result is img
        mock_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_extract_no_api_key(sample_image):
    result = await extract_label_region(sample_image, api_key=None)
    assert result is sample_image  # should return original (non-letter-size)


@pytest.mark.asyncio
async def test_extract_with_mock_api(sample_image):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"found": true, "x1": 10, "y1": 10, "x2": 190, "y2": 290}')]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = await extract_label_region(sample_image, api_key="test-key")
        # Result is cropped from original — should be smaller or equal
        assert result is not None
        assert result.width <= sample_image.width
        assert result.height <= sample_image.height


@pytest.mark.asyncio
async def test_extract_retries_after_transient_error(sample_image):
    """A single transient API failure is retried instead of degrading to
    the heuristic fallback."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"x1": 10, "y1": 10, "x2": 190, "y2": 290}')]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=[Exception("transient"), mock_response]
    )
    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = await extract_label_region(sample_image, api_key="test-key")
        assert result is not None
        assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_extract_api_error_returns_original(sample_image):
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))

    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = await extract_label_region(sample_image, api_key="test-key")
        assert result is sample_image  # fallback to original


# --- strict mode tests ---


@pytest.mark.asyncio
async def test_extract_strict_no_api_key_returns_none(sample_image):
    result = await extract_label_region(sample_image, api_key=None, strict=True)
    assert result is None


@pytest.mark.asyncio
async def test_extract_strict_no_label_returns_none(sample_image):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"no_label": true}')]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = await extract_label_region(sample_image, api_key="test-key", strict=True)
        assert result is None


@pytest.mark.asyncio
async def test_extract_non_strict_no_label_returns_image(sample_image):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"no_label": true}')]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = await extract_label_region(sample_image, api_key="test-key", strict=False)
        assert result is not None  # falls back to original image


@pytest.mark.asyncio
async def test_extract_strict_api_error_returns_none(sample_image):
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))
    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = await extract_label_region(sample_image, api_key="test-key", strict=True)
        assert result is None


@pytest.mark.asyncio
async def test_extract_strict_valid_bbox_returns_crop(sample_image):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"x1_pct": 5, "y1_pct": 5, "x2_pct": 80, "y2_pct": 80}')]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = await extract_label_region(sample_image, api_key="test-key", strict=True)
        assert result is not None
        assert result.width < sample_image.width  # was cropped


# --- config-derived ratios (non-4x6 stock) ---


def test_ratio_windows_derive_from_label_size():
    """The repair window scales with the configured stock's aspect ratio."""
    from app.services.crop_geometry import CropSpec

    default = CropSpec()  # 4x6
    assert default.min_ratio == pytest.approx(1.3)
    assert default.max_ratio == pytest.approx(2.2)

    doctab = CropSpec(expected_ratio=8.0 / 4.0)  # 4x8 doc-tab stock
    assert doctab.min_ratio == pytest.approx(2.0 * 1.3 / 1.5)
    assert doctab.max_ratio == pytest.approx(2.0 * 2.2 / 1.5)


def test_content_fills_label_frame_respects_stock_ratio():
    """A 4x6-proportioned bare label is NOT a bare 4x8 label."""
    img = _bare_label_image()  # 1800x1200, ratio 1.5
    assert _content_fills_label_frame(img, expected_ratio=1.5) is True
    assert _content_fills_label_frame(img, expected_ratio=2.0) is False


def test_letter_fallback_crop_scales_with_label_size():
    """Fallback page fractions derive from the configured stock size."""
    img = Image.new("RGB", (2550, 3300))
    result = _letter_size_fallback_crop(img, label_size_in=(4.0, 8.0))
    assert result.size == (
        int(2550 * 4.25 / 8.5),
        int(3300 * 8.38 / 11.0),
    )
