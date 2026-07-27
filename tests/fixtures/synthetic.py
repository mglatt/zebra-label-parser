"""Synthetic recreations of the carrier-label scenarios the crop logic must handle.

Each generator builds a black-on-white scene at a given scale (1.0 = the
300-DPI letter-page geometry the scenarios were originally tuned on) and
returns a Scenario describing:

- ``image``: the page/crop image
- ``bbox``: the Vision bbox proposal to feed into the crop logic (page px)
- ``keep_boxes``: regions whose ink is part of the label and must survive
- ``drop_boxes``: regions whose ink must NOT appear in the final crop

Scenes contain ink ONLY inside keep/drop boxes, so golden tests can verify
crops by ink accounting: a crop that contains exactly the keep ink has
framed the label correctly.

These are promoted from inline arrays in tests/test_label_extractor.py so
the same geometry can back golden, characterization, and multi-DPI tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image

Box = tuple[int, int, int, int]  # x1, y1, x2, y2 (exclusive)


@dataclass
class Scenario:
    name: str
    image: Image.Image
    bbox: Optional[dict]  # {"x1","y1","x2","y2"} in page pixels, or None
    keep_boxes: dict[str, Box] = field(default_factory=dict)
    drop_boxes: dict[str, Box] = field(default_factory=dict)

    def ink_count(self, boxes: dict[str, Box]) -> int:
        arr = np.array(self.image.convert("L")) < 128
        total = 0
        for x1, y1, x2, y2 in boxes.values():
            total += int(arr[y1:y2, x1:x2].sum())
        return total

    @property
    def keep_ink(self) -> int:
        return self.ink_count(self.keep_boxes)

    @property
    def drop_ink(self) -> int:
        return self.ink_count(self.drop_boxes)


def _blank_page(w: int, h: int) -> np.ndarray:
    return np.full((h, w), 255, dtype=np.uint8)


def _s(v: float, scale: float) -> int:
    return int(round(v * scale))


def _scaler(scale: float):
    def s(v: float) -> int:
        return _s(v, scale)

    return s


def ups_rotated_address_page(scale: float = 1.0) -> Scenario:
    """Letter page where Vision missed the rotated address column.

    The landscape label spans x 300..2100: a solid rotated SHIP TO address
    column (300..740) plus the barcode/tracking area (780..2100).  The
    Vision bbox frames only the barcode area — too square — and the crop
    logic must grow left to recover the address column.
    """
    s = _scaler(scale)
    arr = _blank_page(s(2550), s(3300))
    addr = (s(300), s(800), s(740), s(2000))
    body = (s(780), s(800), s(2100), s(2000))
    arr[addr[1]:addr[3], addr[0]:addr[2]] = 0
    arr[body[1]:body[3], body[0]:body[2]] = 0
    return Scenario(
        name="ups_rotated_address_page",
        image=Image.fromarray(arr),
        bbox={"x1": s(800), "y1": s(800), "x2": s(2100), "y2": s(2000)},
        keep_boxes={"address_column": addr, "label_body": body},
    )


def label_with_return_slip_below(scale: float = 1.0) -> Scenario:
    """Letter page where the Vision bbox spans label + return slip.

    The label block (~1.52 ratio) sits above a whitespace gap; a return
    slip strip sits below it.  The too-square bbox must be trimmed at the
    gap so the slip is excluded while the label survives whole.
    """
    s = _scaler(scale)
    arr = _blank_page(s(2550), s(3300))
    label = (s(150), s(850), s(2050), s(2100))
    slip = (s(150), s(2200), s(2050), s(2380))
    arr[label[1]:label[3], label[0]:label[2]] = 0
    arr[slip[1]:slip[3], slip[0]:slip[2]] = 0
    return Scenario(
        name="label_with_return_slip_below",
        image=Image.fromarray(arr),
        bbox={"x1": s(100), "y1": s(800), "x2": s(2100), "y2": s(2400)},
        keep_boxes={"label": label},
        drop_boxes={"return_slip": slip},
    )


def dense_doctab_label(scale: float = 1.0) -> Scenario:
    """A too-square bbox over dense content with no clean cut line.

    Trimming anywhere would slice through label ink, so the crop logic
    must keep the full bbox (non-standard/doc-tab label stock).
    """
    s = _scaler(scale)
    arr = _blank_page(s(2550), s(3300))
    block = (s(100), s(800), s(2100), s(2400))
    arr[block[1]:block[3], block[0]:block[2]] = 0
    return Scenario(
        name="dense_doctab_label",
        image=Image.fromarray(arr),
        bbox={"x1": s(100), "y1": s(800), "x2": s(2100), "y2": s(2400)},
        keep_boxes={"label": block},
    )


def barcode_clipped_bbox(scale: float = 1.0) -> Scenario:
    """A bbox whose bottom edge slices through the tracking barcode.

    The edge must grow outward until the whole barcode is inside.
    """
    s = _scaler(scale)
    arr = _blank_page(s(1000), s(1400))
    content = (s(200), s(200), s(800), s(880))
    barcode = (s(200), s(900), s(800), s(1050))
    arr[content[1]:content[3], content[0]:content[2]] = 0
    arr[barcode[1]:barcode[3], barcode[0]:barcode[2]] = 0
    return Scenario(
        name="barcode_clipped_bbox",
        image=Image.fromarray(arr),
        bbox={"x1": s(200), "y1": s(200), "x2": s(800), "y2": s(950)},
        keep_boxes={"content": content, "barcode": barcode},
    )


def elongated_strip_bbox(scale: float = 1.0) -> Scenario:
    """A bbox framing only the barcode band of the label (ratio 3.6).

    The deficient dimension must grow back into the adjacent label ink.
    """
    s = _scaler(scale)
    arr = _blank_page(s(2550), s(3300))
    label = (s(300), s(800), s(2100), s(2000))
    arr[label[1]:label[3], label[0]:label[2]] = 0
    return Scenario(
        name="elongated_strip_bbox",
        image=Image.fromarray(arr),
        bbox={"x1": s(300), "y1": s(1500), "x2": s(2100), "y2": s(2000)},
        keep_boxes={"label": label},
    )


def bare_label_image(scale: float = 1.0) -> Scenario:
    """A bare landscape label file: ink spans nearly the full 4x6 frame.

    Includes a rotated address column on the left (UPS/Amazon return
    layout).  Text/barcode lines are drawn sparsely — real labels are
    mostly white.  Must bypass Vision and be used whole.
    """
    s = _scaler(scale)
    w, h = s(1800), s(1200)
    arr = _blank_page(w, h)
    arr[s(40):s(1160):6, s(40):s(480)] = 0     # rotated address column
    arr[s(40):s(1160):4, s(520):s(1760)] = 0   # barcodes / tracking area
    return Scenario(
        name="bare_label_image",
        image=Image.fromarray(arr),
        bbox=None,
        keep_boxes={"label": (0, 0, w, h)},
    )


def amazon_sidebar_crop(scale: float = 1.0) -> Scenario:
    """A Vision crop that still contains rotated sidebar heading text.

    Layout (1000x700): sparse rotated text bands at both side edges,
    separated from the dense label content by ~30px whitespace gaps.
    The tighten/shed stage must drop the sidebars and keep the label.
    """
    s = _scaler(scale)
    w, h = s(1000), s(700)
    arr = _blank_page(w, h)
    left = (0, s(50), s(60), s(650))
    label = (s(90), s(20), s(910), s(682))
    right = (s(940), s(50), w, s(650))
    for col in range(0, s(60)):                      # left sidebar (sparse)
        for row in range(s(50), s(650), max(1, s(10))):
            arr[row:row + max(1, s(3)), col] = 0
    for col in range(s(90), s(910)):                 # main label (dense)
        for row in range(s(20), s(680), max(1, s(5))):
            arr[row:row + max(1, s(2)), col] = 0
    for col in range(s(940), w):                     # right sidebar (sparse)
        for row in range(s(50), s(650), max(1, s(10))):
            arr[row:row + max(1, s(3)), col] = 0
    return Scenario(
        name="amazon_sidebar_crop",
        image=Image.fromarray(arr),
        bbox=None,
        keep_boxes={"label": label},
        drop_boxes={"left_sidebar": left, "right_sidebar": right},
    )


def sparse_address_crop(scale: float = 1.0) -> Scenario:
    """A crop whose left side is sparse address text — NOT trimmable.

    Address columns carry ~1% ink: above the whitespace threshold, so the
    tighten/shed stage must leave the crop untouched.
    """
    s = _scaler(scale)
    w, h = s(600), s(400)
    arr = _blank_page(w, h)
    addr = (0, s(30), s(150), s(374))
    body = (s(150), s(10), w, s(392))
    for col in range(0, s(150)):                     # sparse address text
        for row in range(s(30), s(370), max(1, s(50))):
            arr[row:row + max(1, s(4)), col] = 0
    for col in range(s(150), w):                     # dense barcode content
        for row in range(s(10), s(390), max(1, s(5))):
            arr[row:row + max(1, s(2)), col] = 0
    return Scenario(
        name="sparse_address_crop",
        image=Image.fromarray(arr),
        bbox=None,
        keep_boxes={"address": addr, "body": body},
    )


# Scenarios exercised through _validate_and_crop / refine_label_box
BBOX_SCENARIOS = [
    ups_rotated_address_page,
    label_with_return_slip_below,
    dense_doctab_label,
    barcode_clipped_bbox,
    elongated_strip_bbox,
]

# Scenarios exercised through the tighten/shed stage on an existing crop
CROP_SCENARIOS = [
    amazon_sidebar_crop,
    sparse_address_crop,
]
