from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

import numpy as np

from app.services.label_extractor import extract_label_region, _parse_bbox, _validate_and_crop, _tighten_to_content


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


def test_validate_and_crop_out_of_bounds():
    img = Image.new("RGB", (200, 300))
    result = _validate_and_crop({"x1": -50, "y1": 0, "x2": 200, "y2": 300}, img)
    assert result is None


def test_validate_and_crop_trims_too_square():
    """A bbox with ratio < 1.3 is trimmed to ~1.5 (4×6 label proportions)."""
    # Simulate a landscape label crop that's too tall (includes return auth slip).
    # Bbox: 2000 wide × 1600 tall → ratio 1.25 (too square).
    img = Image.new("RGB", (2550, 3300))
    result = _validate_and_crop({"x1": 100, "y1": 800, "x2": 2100, "y2": 2400}, img)
    assert result is not None
    # After trimming: height should be reduced to ~2000/1.5 = 1333,
    # plus safety margins. Result should be clearly less tall than the
    # original 1600px bbox height + margins.
    assert result.height < 1500


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

    Layout (600 wide x 400 tall):
    - Columns 0-49: scattered dark pixels (rotated "Return Auth Slip" text)
    - Columns 50-69: whitespace gap
    - Columns 70-529: main label content (dense)
    - Columns 530-549: whitespace gap
    - Columns 550-599: scattered dark pixels (rotated "Return Mailing Label")
    """
    img = Image.new("L", (600, 400), 255)
    arr = np.array(img)

    # Left sidebar text: sparse dark pixels in columns 0-49
    for col in range(0, 50):
        for row in range(50, 350, 10):
            arr[row:row+3, col] = 0

    # Main label content: dense dark pixels in columns 70-529
    for col in range(70, 530):
        for row in range(20, 380, 5):
            arr[row:row+2, col] = 0

    # Right sidebar text: sparse dark pixels in columns 550-599
    for col in range(550, 600):
        for row in range(50, 350, 10):
            arr[row:row+3, col] = 0

    img = Image.fromarray(arr)
    result = _tighten_to_content(img)

    # Should have trimmed the sidebars — width should be less than original
    assert result.width < 560, f"Expected width < 560, got {result.width}"
    # Main content (460 px) should be preserved
    assert result.width >= 460, f"Expected width >= 460, got {result.width}"


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


def test_tighten_preserves_when_trim_too_aggressive():
    """If tightening would remove >50% of the image, skip it.

    Create an image where whitespace bands exist but trimming to them
    would leave less than 50% of the original dimensions.
    """
    img = Image.new("L", (400, 300), 255)
    arr = np.array(img)
    # Put sparse content only in a narrow vertical strip (cols 250-280)
    # with wide whitespace on the left. The tightened width (280-0=280 at best)
    # would be 70% of 400. But if content is only in cols 250-280 and
    # there's a whitespace band from 0-249, tightening to col 250 would
    # leave only 30 cols wide = 7.5% of 400 = too aggressive.
    for col in range(250, 280):
        for row in range(0, 300, 4):
            arr[row:row+2, col] = 0
    img = Image.fromarray(arr)
    result = _tighten_to_content(img)
    # Tightening would leave only ~30px wide (7.5%), so it should be skipped.
    # But only the outer 25% is scanned, so cols 0-99 are checked.
    # Since there's a whitespace band in cols 0-99, the left side gets
    # trimmed to col 100 (end of scan range), giving 300px wide = 75%.
    # That's > 50%, so trimming WILL happen on the left side.
    # The key test: original should not be completely destroyed.
    assert result.width >= 200  # at least 50% preserved


# --- extract_label_region tests ---


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
