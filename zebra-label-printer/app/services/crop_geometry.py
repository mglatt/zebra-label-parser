"""Geometric refinement of a proposed label bounding box.

Division of labor (see also the extraction prompt in label_extractor):

- The Vision model owns SEMANTICS: deciding what is and is not part of the
  label (include rotated address blocks, exclude return-authorization
  slips, receipts, sidebar headings).
- This module owns GEOMETRIC SAFETY: given the model's bbox proposal it
  may only (a) GROW an edge that slices through ink, (b) SHED content
  bands that are separated from the label by a clean whitespace gap, and
  (c) apply one final trim-to-content + margin.  It never cuts through
  ink, and it never second-guesses semantics beyond gap-separated
  shedding.

Everything is pure numpy over a boolean ink mask — no API calls, no I/O —
so every behavior here is unit-testable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

Box = tuple[int, int, int, int]  # x1, y1, x2, y2 (exclusive)


@dataclass(frozen=True)
class CropSpec:
    """Tuning parameters for bbox refinement.

    Lengths are expressed in inches and converted through ``dpi`` so the
    same spec behaves identically at any working resolution.  Pixel
    defaults match the historical values at the 300-DPI PDF render
    resolution the heuristics were tuned on.
    """

    # Expected label aspect ratio (long/short side); 4x6" stock = 1.5.
    expected_ratio: float = 1.5
    # Resolution of the image being refined.
    dpi: float = 300.0
    # Pixels darker than this grayscale value count as ink.
    ink_threshold: int = 200
    # A row/column is "clean" (whitespace) below this dark fraction.
    clean_frac: float = 0.004
    # Stricter whitespace fraction used when deciding to SHED content:
    # sparse-but-valid ink like address text must never read as whitespace.
    ws_frac: float = 0.003
    # Safety margin added around the final bbox.
    margin_in: float = 20 / 300
    # Minimum width of a whitespace band to count as a genuine gap.
    min_gap_in: float = 20 / 300
    # Cap on outward growth per edge, as a fraction of the page dimension.
    max_grow_frac: float = 0.08
    # Shedding only inspects this outer fraction of each edge.
    edge_frac: float = 0.15

    @property
    def margin_px(self) -> int:
        return max(1, round(self.margin_in * self.dpi))

    @property
    def min_gap_px(self) -> int:
        return max(1, round(self.min_gap_in * self.dpi))

    # Bboxes with a ratio outside [min_ratio, max_ratio] get repaired.
    # The window scales with the expected ratio; at 1.5 it is the
    # historical [1.3, 2.2].
    @property
    def min_ratio(self) -> float:
        return self.expected_ratio * (1.3 / 1.5)

    @property
    def max_ratio(self) -> float:
        return self.expected_ratio * (2.2 / 1.5)


def ink_mask(image: Image.Image, spec: CropSpec) -> np.ndarray:
    """Boolean array (h, w): True where a pixel is dark enough to be ink."""
    return np.array(image.convert("L")) < spec.ink_threshold


def find_clean_line(
    dark: np.ndarray,
    target: int,
    radius: int,
    span: slice,
    axis: int,
    spec: CropSpec,
) -> Optional[int]:
    """Find a whitespace row (axis=0) or column (axis=1) near *target*.

    Scans positions in [target-radius, target+radius]; a position qualifies
    when fewer than ``spec.clean_frac`` of its pixels inside *span* are
    dark.  Returns the qualifying position that keeps the most content
    (largest index — callers only ever trim from the bottom/right), or
    None when no clean line exists.  Cutting anywhere else would slice
    through label content, so callers must skip the trim in that case.
    """
    n = dark.shape[axis]
    lo = max(0, target - radius)
    hi = min(n, target + radius + 1)
    if hi <= lo:
        return None
    if axis == 0:
        frac = dark[lo:hi, span].mean(axis=1)
    else:
        frac = dark[span, lo:hi].mean(axis=0)
    clean = np.nonzero(frac < spec.clean_frac)[0]
    if clean.size == 0:
        return None
    return lo + int(clean[-1])


def expand_into_ink(dark: np.ndarray, box: Box, spec: CropSpec) -> Box:
    """Repair an off-aspect bbox by growing it into adjacent label content.

    A bbox far from label proportions usually means one of two things: it
    includes extra page content (handled by the whitespace cut), or it
    MISSED part of the label — e.g. an address block printed rotated 90°
    along one side (UPS/Amazon return labels).  If ink sits directly
    beyond the deficient dimension's edges, the label continues there:
    grow the bbox toward the expected ratio to recover it.
    """
    x1, y1, x2, y2 = box
    h, w = dark.shape
    crop_w, crop_h = x2 - x1, y2 - y1
    long_side, short_side = max(crop_w, crop_h), min(crop_w, crop_h)
    ratio = long_side / short_side if short_side > 0 else 0
    if ratio <= 0:
        return box

    if ratio < spec.expected_ratio:
        # Too square: the long dimension is deficient — grow it
        grow_width = crop_w >= crop_h
        target = int(short_side * spec.expected_ratio)
    else:
        # Too elongated: the short dimension is deficient — grow it
        grow_width = crop_w < crop_h
        target = int(long_side / spec.expected_ratio)

    # A strip column/row counts as ink with >=3 dark pixels (ignore specks)
    if grow_width:
        needed = target - (x2 - x1)
        if needed > 0:
            lo = max(0, x1 - needed)
            ink = np.nonzero(dark[y1:y2, lo:x1].sum(axis=0) >= 3)[0]
            if ink.size:
                x1 = lo + int(ink[0])
        needed = target - (x2 - x1)
        if needed > 0:
            hi = min(w, x2 + needed)
            ink = np.nonzero(dark[y1:y2, x2:hi].sum(axis=0) >= 3)[0]
            if ink.size:
                x2 = x2 + int(ink[-1]) + 1
    else:
        needed = target - (y2 - y1)
        if needed > 0:
            lo = max(0, y1 - needed)
            ink = np.nonzero(dark[lo:y1, x1:x2].sum(axis=1) >= 3)[0]
            if ink.size:
                y1 = lo + int(ink[0])
        needed = target - (y2 - y1)
        if needed > 0:
            hi = min(h, y2 + needed)
            ink = np.nonzero(dark[y2:hi, x1:x2].sum(axis=1) >= 3)[0]
            if ink.size:
                y2 = y2 + int(ink[-1]) + 1

    return x1, y1, x2, y2


def expand_to_whitespace(dark: np.ndarray, box: Box, spec: CropSpec) -> Box:
    """Grow the bbox outward until every edge lies on a whitespace line.

    If the bbox slices through ink (most commonly the edge of a barcode),
    push that edge outward until the boundary row/column is clean, capped
    at ``spec.max_grow_frac`` of the page dimension so adjacent page
    content is not swallowed wholesale.
    """
    x1, y1, x2, y2 = box
    h, w = dark.shape
    max_dx = max(40, int(w * spec.max_grow_frac))
    max_dy = max(40, int(h * spec.max_grow_frac))
    lim_x1 = max(0, x1 - max_dx)
    lim_x2 = min(w, x2 + max_dx)
    lim_y1 = max(0, y1 - max_dy)
    lim_y2 = min(h, y2 + max_dy)

    # Two passes: expanding one edge can expose ink on a neighbouring edge.
    for _ in range(2):
        while x1 > lim_x1 and dark[y1:y2, x1].mean() >= spec.clean_frac:
            x1 -= 1
        while x2 < lim_x2 and dark[y1:y2, x2 - 1].mean() >= spec.clean_frac:
            x2 += 1
        while y1 > lim_y1 and dark[y1, x1:x2].mean() >= spec.clean_frac:
            y1 -= 1
        while y2 < lim_y2 and dark[y2 - 1, x1:x2].mean() >= spec.clean_frac:
            y2 += 1

    return x1, y1, x2, y2


def tighten_to_content(image: Image.Image, spec: CropSpec) -> Image.Image:
    """Tighten a crop by detecting whitespace bands along the edges.

    After the Vision crop, extraneous content separated from the label by
    a whitespace band may remain (e.g. rotated "Return Authorization Slip"
    text alongside an Amazon return label).  Scan for predominantly-white
    columns/rows near the edges and trim them away.

    Only trims when a truly empty whitespace gap exists in the outer
    ``spec.edge_frac`` of the image.  The ``spec.ws_frac`` threshold is
    deliberately strict so sparse-but-valid label content like address
    text is never trimmed.
    """
    h, w = image.height, image.width

    # Minimum dimension — don't tighten tiny crops
    if w < 200 or h < 200:
        return image

    dark = ink_mask(image, spec)

    col_dark_frac = dark.mean(axis=0)  # shape (w,)
    row_dark_frac = dark.mean(axis=1)  # shape (h,)
    min_band = spec.min_gap_px

    def _find_inner_edge(dark_frac: np.ndarray, total: int, from_start: bool) -> int:
        """Find the inner edge of a whitespace band near one side.

        Scans from the given side inward.  If a whitespace band of at
        least ``min_band`` columns/rows is found, returns the position
        just past the band (where content starts).  Otherwise returns 0
        (start) or total (end), meaning no trimming.
        """
        limit = int(total * spec.edge_frac)
        if from_start:
            indices = range(limit)
        else:
            indices = range(total - 1, total - 1 - limit, -1)

        band_start = None
        band_len = 0

        for i in indices:
            if dark_frac[i] < spec.ws_frac:
                if band_start is None:
                    band_start = i
                band_len += 1
            else:
                if band_len >= min_band:
                    # Found a real gap — return the content side of it
                    if from_start:
                        return i  # first content column/row after the gap
                    else:
                        return i + 1  # content ends here
                band_start = None
                band_len = 0

        # Check if band extends to the edge
        if band_len >= min_band:
            if from_start:
                return band_start + band_len
            else:
                return band_start - band_len + 1 if band_start is not None else total

        return 0 if from_start else total

    new_x1 = _find_inner_edge(col_dark_frac, w, from_start=True)
    new_x2 = _find_inner_edge(col_dark_frac, w, from_start=False)
    new_y1 = _find_inner_edge(row_dark_frac, h, from_start=True)
    new_y2 = _find_inner_edge(row_dark_frac, h, from_start=False)

    # Only apply if we're actually trimming something meaningful
    trimmed_w = new_x2 - new_x1
    trimmed_h = new_y2 - new_y1
    if trimmed_w < w * 0.5 or trimmed_h < h * 0.5:
        # Would remove too much — skip tightening
        logger.info("Tightening would remove >50%% of crop, skipping")
        return image

    if new_x1 > 0 or new_x2 < w or new_y1 > 0 or new_y2 < h:
        logger.info(
            "Tightened crop: x %d→%d, y %d→%d (was %dx%d, now %dx%d)",
            new_x1, new_x2, new_y1, new_y2, w, h, trimmed_w, trimmed_h,
        )
        return image.crop((new_x1, new_y1, new_x2, new_y2))

    return image
