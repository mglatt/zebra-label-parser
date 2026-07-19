"""Golden invariant tests for the label-bounding logic.

These encode the carrier behaviors that past hot-fixes protect, as
content-level invariants (ink accounting) rather than pixel-exact sizes,
so behavior-preserving refactors pass unchanged:

- every scene draws ink only inside its keep/drop boxes, so a correct
  crop contains EXACTLY the keep ink: ``crop_ink == keep_ink`` proves the
  label survived whole AND the excluded content was dropped.

If one of these fails, a known carrier regression has been reintroduced.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.services.label_extractor import (
    _tighten_to_content,
    _validate_and_crop,
    extract_label_region,
)
from tests.fixtures import synthetic as syn


def _ink(img) -> int:
    return int((np.array(img.convert("L")) < 128).sum())


def refine(bbox: dict, image):
    """Seam for the bbox-refinement stage (validate → grow/shed → crop)."""
    return _validate_and_crop(bbox, image)


def tighten(image):
    """Seam for the crop-tightening stage (drop gap-separated edge bands)."""
    return _tighten_to_content(image)


@pytest.mark.parametrize("make", syn.BBOX_SCENARIOS, ids=lambda f: f.__name__)
def test_bbox_scenario_crop_contains_exactly_the_label(make):
    sc = make()
    result = refine(sc.bbox, sc.image)
    assert result is not None, f"{sc.name}: bbox rejected"
    assert _ink(result) == sc.keep_ink, (
        f"{sc.name}: crop ink {_ink(result)} != label ink {sc.keep_ink} "
        f"(label clipped or excluded content leaked in)"
    )


@pytest.mark.parametrize("make", syn.CROP_SCENARIOS, ids=lambda f: f.__name__)
def test_crop_scenario_keeps_exactly_the_label(make):
    sc = make()
    result = tighten(sc.image)
    assert _ink(result) == sc.keep_ink, (
        f"{sc.name}: ink {_ink(result)} != label ink {sc.keep_ink}"
    )


def test_sparse_address_text_never_trimmed():
    """Sparse (~1% ink) address columns are label content, not whitespace."""
    sc = syn.sparse_address_crop()
    result = tighten(sc.image)
    assert result.size == sc.image.size, "sparse address text was trimmed"


def test_dense_label_never_cut_through_ink():
    """With no clean whitespace line, the full bbox must be kept."""
    sc = syn.dense_doctab_label()
    result = refine(sc.bbox, sc.image)
    assert result is not None
    assert _ink(result) == sc.keep_ink, "cut through dense label content"


@pytest.mark.asyncio
async def test_bare_label_bypasses_vision():
    """A bare 4x6-proportioned label file is used whole, no API call."""
    sc = syn.bare_label_image()
    img = sc.image.convert("RGB")

    mock_client = AsyncMock()
    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = await extract_label_region(img, api_key="test-key")
        assert result is img
        mock_client.messages.create.assert_not_called()
