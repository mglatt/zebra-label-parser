from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.services.label_extractor import extract_label_region, _parse_bbox, _validate_and_crop


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
    result = _validate_and_crop({"x1": 0, "y1": 0, "x2": 400, "y2": 600}, img)
    assert result is not None
    assert result.width == 400
    assert result.height == 600


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
        assert result.width == 180  # 190 - 10
        assert result.height == 280  # 290 - 10


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
