"""Characterization tests: pin the EXACT current crop geometry.

Unlike test_crop_golden.py (behavior invariants that must always hold),
these pin concrete output sizes and ink counts.  They exist to make every
geometry change during refactoring an explicit, reviewed diff: when a
refactor step intentionally alters geometry (e.g. where a margin is
applied), update the values here in the same commit and say why in the
commit message.  An UNINTENTIONAL failure here means behavior drifted.
"""
import numpy as np
import pytest

from app.services.label_extractor import _tighten_to_content, _validate_and_crop
from tests.fixtures import synthetic as syn


def _ink(img) -> int:
    return int((np.array(img.convert("L")) < 128).sum())


# (scenario, expected width, expected height, expected ink count)
# Crops are content bounds + the 20px safety margin on every side (since
# the finish_box refactor made the margin survive to the final crop).
BBOX_EXPECTED = [
    (syn.ups_rotated_address_page, 1840, 1240, 2_112_000),
    (syn.label_with_return_slip_below, 1940, 1290, 2_375_000),
    (syn.dense_doctab_label, 2040, 1640, 3_200_000),
    (syn.barcode_clipped_bbox, 640, 890, 498_000),
    (syn.elongated_strip_bbox, 1840, 1240, 2_160_000),
]

CROP_EXPECTED = [
    (syn.amazon_sidebar_crop, 820, 657, 216_480),
    (syn.sparse_address_crop, 600, 400, 72_600),
]


@pytest.mark.parametrize(
    "make,w,h,ink", BBOX_EXPECTED, ids=lambda p: getattr(p, "__name__", p)
)
def test_bbox_crop_geometry_pinned(make, w, h, ink):
    sc = make()
    result = _validate_and_crop(sc.bbox, sc.image)
    assert result is not None
    assert (result.width, result.height) == (w, h)
    assert _ink(result) == ink


@pytest.mark.parametrize(
    "make,w,h,ink", CROP_EXPECTED, ids=lambda p: getattr(p, "__name__", p)
)
def test_tighten_geometry_pinned(make, w, h, ink):
    sc = make()
    result = _tighten_to_content(sc.image)
    assert (result.width, result.height) == (w, h)
    assert _ink(result) == ink
