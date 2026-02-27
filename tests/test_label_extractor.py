from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.services.label_extractor import extract_label_region, _parse_bbox, _validate_bbox


def test_parse_bbox_valid():
    text = '{"found": true, "x1": 10, "y1": 20, "x2": 200, "y2": 300}'
    result = _parse_bbox(text)
    assert result is not None
    assert result["x1"] == 10


def test_parse_bbox_with_surrounding_text():
    text = 'Here is the result: {"found": true, "x1": 0, "y1": 0, "x2": 100, "y2": 200} done.'
    result = _parse_bbox(text)
    assert result is not None


def test_parse_bbox_not_found():
    text = '{"found": false}'
    result = _parse_bbox(text)
    assert result is None


def test_parse_bbox_invalid_json():
    assert _parse_bbox("not json at all") is None


def test_parse_bbox_missing_keys():
    text = '{"found": true, "x1": 10}'
    assert _parse_bbox(text) is None


def test_validate_bbox_valid():
    assert _validate_bbox({"x1": 0, "y1": 0, "x2": 400, "y2": 600}, 800, 1000)


def test_validate_bbox_too_small():
    # Bbox is only 5% of image area
    assert not _validate_bbox({"x1": 0, "y1": 0, "x2": 20, "y2": 25}, 200, 200)


def test_validate_bbox_inverted():
    assert not _validate_bbox({"x1": 100, "y1": 100, "x2": 50, "y2": 50}, 200, 200)


def test_validate_bbox_out_of_bounds():
    assert not _validate_bbox({"x1": -50, "y1": 0, "x2": 200, "y2": 300}, 200, 300)


@pytest.mark.asyncio
async def test_extract_no_api_key(sample_image):
    result = await extract_label_region(sample_image, api_key=None)
    assert result is sample_image  # should return original


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
