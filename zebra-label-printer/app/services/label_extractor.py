"""Use Claude Vision API to identify and extract shipping labels from images."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Locate the shipping label in this image and return a bounding box that \
contains the ENTIRE label.

Shipping labels come from carriers such as UPS, FedEx, USPS, DHL, Amazon, \
OnTrac, and regional couriers. A label is approximately 4x6 inches and may \
be oriented portrait OR landscape on the page. A COMPLETE label includes \
ALL of:
- the carrier logo/banner and service type (e.g. GROUND, PRIORITY MAIL, \
  2DAY, SUREPOST, HOME DELIVERY)
- ship-from and ship-to addresses
- weight, date, zone, and reference/order numbers
- routing text and sort codes (e.g. "TRK#", USPS banner text, FedEx ASTRA)
- EVERY barcode belonging to the label: linear barcodes, QR / Data Matrix / \
  Aztec codes, and the square dotted UPS MaxiCode. The main tracking \
  barcode is usually near the BOTTOM of the label — it must NOT be cut off.

CRITICAL: a bounding box that clips ANY part of the label (a barcode, a \
text line, or the carrier banner) is wrong. If you are unsure exactly where \
the label ends, return a slightly LARGER box — surrounding whitespace is \
removed automatically later, but clipped content cannot be recovered.

On full-page documents (8.5x11"), the label is one section of the page. \
Exclude everything that is NOT the label itself:
- Return authorization slips, return slips, receipts, customs forms, \
  packing slips, instructions, fold lines, scissors icons.
- Any barcodes or text OUTSIDE the label border.
- Section headings like "Return Mailing Label" or "Return Authorization Slip" \
  that appear OUTSIDE or alongside the label.
- Rotated text printed vertically along the edges of the label area \
  (e.g., "Return Authorization Slip", "Return Mailing Label", or instruction \
  text rotated 90 degrees). These are NOT part of the label.

If the label is enclosed by a dashed border, cut line, or rectangular outline, \
the bounding box must cover everything INSIDE those lines but nothing outside \
them.

Return the bounding box as percentages of image dimensions (0-100):

{"x1_pct": <left>, "y1_pct": <top>, "x2_pct": <right>, "y2_pct": <bottom>}

If the shipping label fills the entire image (or the image IS the label), \
return:
{"x1_pct": 0, "y1_pct": 0, "x2_pct": 100, "y2_pct": 100}

If there is NO shipping label in this image (e.g. it is an instruction page, \
packing slip, or receipt with no carrier label), return:
{"no_label": true}

Return ONLY valid JSON, no other text."""

# Pixels darker than this grayscale value count as ink.
_DARK_THRESH = 200
# A row/column is "clean" (whitespace) when fewer than this fraction of its
# pixels are dark.
_CLEAN_FRAC = 0.004


def _image_to_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _parse_bbox(text: str, width: int, height: int) -> Optional[dict]:
    """Extract JSON bounding box from Claude's response.

    Handles both percentage-based keys (x1_pct) and pixel keys (x1).
    Returns pixel coordinates snapped to a 10px grid for consistency.
    """
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        data = json.loads(text[start:end])

        # Explicit "no label" response from the model
        if data.get("no_label"):
            return {"no_label": True}

        # Convert percentage coords to pixels
        if "x1_pct" in data:
            vals = [
                float(data["x1_pct"]),
                float(data["y1_pct"]),
                float(data["x2_pct"]),
                float(data["y2_pct"]),
            ]
            # Some responses use 0-1 fractions instead of 0-100 percentages.
            # A genuine percentage bbox with all values <= 1 would cover under
            # 1% of the image — degenerate either way — so rescaling is safe.
            if all(0 <= v <= 1.0 for v in vals) and (vals[2] > vals[0] and vals[3] > vals[1]):
                vals = [v * 100.0 for v in vals]
            # Clamp slight overshoots (e.g. 100.5 or -2) rather than letting
            # them invalidate an otherwise good bbox.
            vals = [min(100.0, max(0.0, v)) for v in vals]
            data = {
                "x1": vals[0] / 100.0 * width,
                "y1": vals[1] / 100.0 * height,
                "x2": vals[2] / 100.0 * width,
                "y2": vals[3] / 100.0 * height,
            }

        for key in ("x1", "y1", "x2", "y2"):
            if key not in data:
                return None

        # Clamp pixel coords to image bounds
        data["x1"] = min(width, max(0, float(data["x1"])))
        data["x2"] = min(width, max(0, float(data["x2"])))
        data["y1"] = min(height, max(0, float(data["y1"])))
        data["y2"] = min(height, max(0, float(data["y2"])))

        # Snap to 10px grid to reduce run-to-run jitter
        _GRID = 10
        data["x1"] = int(data["x1"] // _GRID * _GRID)
        data["y1"] = int(data["y1"] // _GRID * _GRID)
        data["x2"] = int(-(-data["x2"] // _GRID) * _GRID)  # ceil to grid
        data["y2"] = int(-(-data["y2"] // _GRID) * _GRID)

        return data
    except (json.JSONDecodeError, TypeError, KeyError, ValueError):
        return None


def _is_letter_size(width: int, height: int) -> bool:
    """Check if image dimensions match US letter proportions (8.5x11").

    Works for both portrait and landscape orientations.
    Allows ~10% tolerance for rendering differences.
    """
    ratio = max(width, height) / min(width, height)
    letter_ratio = 11.0 / 8.5  # ~1.294
    return abs(ratio - letter_ratio) < 0.13


def _letter_size_fallback_crop(image: Image.Image) -> Image.Image:
    """Apply a heuristic crop for a standard letter-size page.

    On a typical USPS/FedEx/UPS full-page PDF, the 4x6" shipping label
    occupies roughly the upper-left portion:
    - Width: 4" / 8.5" ≈ 47% of page width
    - Height: 6" / 11" ≈ 55% of page height

    We use slightly generous bounds to avoid clipping.
    """
    # Ensure we're working with portrait orientation
    w, h = image.width, image.height
    if w > h:
        # Landscape — the label is in the left portion
        crop_w = int(w * 0.57)
        crop_h = int(h * 0.97)
        cropped = image.crop((0, 0, crop_w, crop_h))
    else:
        # Portrait — label is in the upper-left
        crop_w = int(w * 0.50)
        crop_h = int(h * 0.58)
        cropped = image.crop((0, 0, crop_w, crop_h))

    logger.info(
        "Letter-size fallback crop: %dx%d -> %dx%d",
        w, h, cropped.width, cropped.height,
    )
    return cropped


def _tighten_to_content(image: Image.Image) -> Image.Image:
    """Tighten a crop by detecting whitespace bands along the edges.

    After the Vision API crops a region, there may still be extraneous
    content separated from the actual label by a whitespace band (e.g.,
    rotated "Return Authorization Slip" text alongside an Amazon return
    label).  This function scans for predominantly-white columns/rows
    near the edges and trims them away.

    Only trims if a clear, truly empty whitespace gap is found in the
    outer portion of the image (outer 15% on each side).  Thresholds are
    deliberately strict to avoid trimming sparse-but-valid label content
    like address text.
    """
    arr = np.array(image.convert("L"))
    h, w = arr.shape

    # Minimum dimension — don't tighten tiny crops
    if w < 200 or h < 200:
        return image

    # Threshold: pixels below this are "dark" (ink)
    _DARK_THRESH = 200
    # A column/row is "whitespace" if fewer than this fraction of pixels are dark.
    # Very strict: 0.3% — only truly empty columns/rows qualify.  Even a single
    # character of address text pushes a column above this threshold.
    _WS_FRAC = 0.003
    # Minimum width of a whitespace band to count as a real gap (pixels).
    # Must be wide enough to represent a genuine separation, not just normal
    # spacing between text characters or lines.
    _MIN_BAND = 20
    # Only look in the outer portion of each edge
    _EDGE_FRAC = 0.15

    dark = arr < _DARK_THRESH  # boolean array: True where ink exists

    # Column-wise dark pixel fraction
    col_dark_frac = dark.mean(axis=0)  # shape (w,)
    # Row-wise dark pixel fraction
    row_dark_frac = dark.mean(axis=1)  # shape (h,)

    def _find_inner_edge(dark_frac: np.ndarray, total: int, from_start: bool) -> int:
        """Find the inner edge of a whitespace band near one side.

        Scans from the given side inward.  If a whitespace band of at
        least _MIN_BAND columns/rows is found, returns the position just
        past the band (where content starts).  Otherwise returns 0 (start)
        or total (end), meaning no trimming.
        """
        limit = int(total * _EDGE_FRAC)
        if from_start:
            indices = range(limit)
        else:
            indices = range(total - 1, total - 1 - limit, -1)

        band_start = None
        band_len = 0

        for i in indices:
            if dark_frac[i] < _WS_FRAC:
                if band_start is None:
                    band_start = i
                band_len += 1
            else:
                if band_len >= _MIN_BAND:
                    # Found a real gap — return the content side of it
                    if from_start:
                        return i  # first content column/row after the gap
                    else:
                        return i + 1  # content ends here (exclusive not needed, +1 to include)
                band_start = None
                band_len = 0

        # Check if band extends to the edge
        if band_len >= _MIN_BAND:
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


def _find_clean_line(
    dark: np.ndarray, target: int, radius: int, span: slice, axis: int
) -> Optional[int]:
    """Find a whitespace row (axis=0) or column (axis=1) near *target*.

    Scans positions in [target-radius, target+radius]; a position qualifies
    when fewer than _CLEAN_FRAC of its pixels inside *span* are dark.
    Returns the qualifying position that keeps the most content (largest
    index — callers only ever trim from the bottom/right), or None when no
    clean line exists.  Cutting anywhere else would slice through label
    content, so callers must skip the trim in that case.
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
    clean = np.nonzero(frac < _CLEAN_FRAC)[0]
    if clean.size == 0:
        return None
    return lo + int(clean[-1])


def _expand_to_whitespace(
    dark: np.ndarray, x1: int, y1: int, x2: int, y2: int
) -> tuple[int, int, int, int]:
    """Grow the bbox outward until every edge lies on a whitespace line.

    If the Vision bbox slices through ink (most commonly the edge of a
    barcode), push that edge outward until the boundary row/column is
    clean, capped at ~8% of the page dimension so adjacent page content
    is not swallowed wholesale.
    """
    h, w = dark.shape
    max_dx = max(40, int(w * 0.08))
    max_dy = max(40, int(h * 0.08))
    lim_x1 = max(0, x1 - max_dx)
    lim_x2 = min(w, x2 + max_dx)
    lim_y1 = max(0, y1 - max_dy)
    lim_y2 = min(h, y2 + max_dy)

    # Two passes: expanding one edge can expose ink on a neighbouring edge.
    for _ in range(2):
        while x1 > lim_x1 and dark[y1:y2, x1].mean() >= _CLEAN_FRAC:
            x1 -= 1
        while x2 < lim_x2 and dark[y1:y2, x2 - 1].mean() >= _CLEAN_FRAC:
            x2 += 1
        while y1 > lim_y1 and dark[y1, x1:x2].mean() >= _CLEAN_FRAC:
            y1 -= 1
        while y2 < lim_y2 and dark[y2 - 1, x1:x2].mean() >= _CLEAN_FRAC:
            y2 += 1

    return x1, y1, x2, y2


def _validate_and_crop(
    bbox: dict, image: Image.Image
) -> Optional[Image.Image]:
    """Validate bbox and return cropped image, or None if invalid.

    Accepts both portrait and landscape crops — the image processor
    handles rotation later.  Coordinates are clamped to the image rather
    than rejected, and all trimming is whitespace-aware: a cut is only
    made along a genuinely blank line so label content is never sliced.
    """
    width, height = image.width, image.height

    # Clamp to image bounds — Vision occasionally overshoots slightly, and
    # rejecting the bbox outright would fall back to a heuristic crop that
    # is far more likely to cut the label.
    x1 = int(min(width, max(0, bbox["x1"])))
    x2 = int(min(width, max(0, bbox["x2"])))
    y1 = int(min(height, max(0, bbox["y1"])))
    y2 = int(min(height, max(0, bbox["y2"])))

    # Must be positive dimensions
    if x2 <= x1 or y2 <= y1:
        logger.warning("Invalid bbox dimensions: (%d,%d)-(%d,%d)", x1, y1, x2, y2)
        return None

    bbox_area = (x2 - x1) * (y2 - y1)
    image_area = width * height
    coverage = bbox_area / image_area

    # Too small = likely wrong
    if coverage < 0.10:
        logger.warning("Bbox too small (%.1f%% of image)", coverage * 100)
        return None

    # Covers >90% of the image: the image IS the label (e.g. a 4x6 PDF or a
    # pre-cropped upload).  Return it whole — falling back to a heuristic
    # crop here would cut a full-frame label apart.
    if coverage > 0.90:
        logger.info("Bbox covers %.1f%% of image, using full frame", coverage * 100)
        return image

    dark = np.array(image.convert("L")) < _DARK_THRESH

    # Trim bbox toward a 4×6" label aspect ratio (1.5:1) when it is far off —
    # that usually means the crop includes content outside the label (e.g. a
    # return-slip barcode below it).  The cut is only applied along a clean
    # whitespace line; if none exists near the target, the label itself is
    # probably non-standard (doc-tab labels, etc.) and we keep the full bbox
    # rather than risk slicing it.
    crop_w = x2 - x1
    crop_h = y2 - y1
    long_side = max(crop_w, crop_h)
    short_side = min(crop_w, crop_h)
    ratio = long_side / short_side if short_side > 0 else 0

    _EXPECTED_RATIO = 1.5  # 4×6 label
    _MIN_RATIO = 1.3
    _MAX_RATIO = 2.2

    cut: Optional[int] = None
    if 0 < ratio < _MIN_RATIO:
        # Too square — trim the longer dimension to ~1.5 ratio
        if crop_w >= crop_h:
            # Landscape: trim from bottom (return slips are typically below)
            target = y1 + int(crop_w / _EXPECTED_RATIO)
            cut = _find_clean_line(dark, target, int(crop_h * 0.12), slice(x1, x2), axis=0)
            if cut is not None and cut > y1:
                y2 = cut
        else:
            # Portrait: trim from right
            target = x1 + int(crop_h / _EXPECTED_RATIO)
            cut = _find_clean_line(dark, target, int(crop_w * 0.12), slice(y1, y2), axis=1)
            if cut is not None and cut > x1:
                x2 = cut
    elif ratio > _MAX_RATIO:
        # Too elongated — trim the longer dimension
        if crop_w >= crop_h:
            # Very wide: trim from right
            target = x1 + int(crop_h * _EXPECTED_RATIO)
            cut = _find_clean_line(dark, target, int(crop_w * 0.12), slice(y1, y2), axis=1)
            if cut is not None and cut > x1:
                x2 = cut
        else:
            # Very tall: trim from bottom
            target = y1 + int(crop_w * _EXPECTED_RATIO)
            cut = _find_clean_line(dark, target, int(crop_h * 0.12), slice(x1, x2), axis=0)
            if cut is not None and cut > y1:
                y2 = cut

    if ratio and (ratio < _MIN_RATIO or ratio > _MAX_RATIO):
        if cut is not None:
            logger.info("Bbox ratio %.2f off-label, trimmed along whitespace at %d", ratio, cut)
        else:
            logger.info("Bbox ratio %.2f off-label but no clean cut line — keeping full bbox", ratio)

    # If the bbox edge slices through ink (e.g. the edge of a barcode), grow
    # it outward until each edge sits on whitespace.
    ex1, ey1, ex2, ey2 = _expand_to_whitespace(dark, x1, y1, x2, y2)
    if (ex1, ey1, ex2, ey2) != (x1, y1, x2, y2):
        logger.info(
            "Expanded bbox to whitespace: x %d→%d, y %d→%d, x2 %d→%d, y2 %d→%d",
            x1, ex1, y1, ey1, x2, ex2, y2, ey2,
        )
        x1, y1, x2, y2 = ex1, ey1, ex2, ey2

    # Small safety margin; _trim_whitespace() in the image processor removes
    # excess whitespace later.
    _MARGIN = 20
    x1 = max(0, x1 - _MARGIN)
    y1 = max(0, y1 - _MARGIN)
    x2 = min(width, x2 + _MARGIN)
    y2 = min(height, y2 + _MARGIN)

    cropped = image.crop((x1, y1, x2, y2))
    logger.info("Vision crop: (%d,%d)-(%d,%d) = %dx%d (%.1f%% of page)",
                x1, y1, x2, y2, cropped.width, cropped.height, coverage * 100)

    # Tighten the crop by detecting whitespace bands that separate the
    # actual label content from extraneous text (e.g., rotated sidebar text).
    cropped = _tighten_to_content(cropped)

    return cropped


async def extract_label_region(
    image: Image.Image,
    api_key: Optional[str],
    model: str = "claude-sonnet-4-20250514",
    strict: bool = False,
    usage_out: Optional[dict] = None,
) -> Optional[Image.Image]:
    """Use Claude Vision to find and crop the shipping label from an image.

    Returns the cropped label region.  When *strict* is ``False`` (the
    default), falls back to a letter-size heuristic crop or the original
    image so the caller always gets an image.  When *strict* is ``True``
    (used during multi-page scanning), returns ``None`` when no label is
    confidently detected — no fallbacks are applied.
    """
    is_letter = _is_letter_size(image.width, image.height)
    logger.info(
        "Extraction input: %dx%d, letter_size=%s, has_api_key=%s, strict=%s",
        image.width, image.height, is_letter, bool(api_key), strict,
    )

    if not api_key:
        logger.info("No API key configured, skipping Vision extraction")
        if strict:
            return None
        if is_letter:
            return _letter_size_fallback_crop(image)
        return image

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        b64 = _image_to_base64(image)

        request = dict(
            model=model,
            max_tokens=128,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": _EXTRACTION_PROMPT,
                        },
                    ],
                },
            ],
        )

        # Retry once on transient API failures before giving up — a failed
        # call otherwise degrades to a heuristic crop that may cut the label.
        try:
            response = await client.messages.create(**request)
        except Exception as exc:
            logger.warning("Vision API call failed, retrying once: %s", exc)
            await asyncio.sleep(1)
            response = await client.messages.create(**request)

        # Capture token usage for the caller
        if usage_out is not None and hasattr(response, "usage"):
            usage_out["input_tokens"] = response.usage.input_tokens
            usage_out["output_tokens"] = response.usage.output_tokens
            usage_out["model"] = model

        reply = response.content[0].text
        logger.info("Vision raw response: %s", reply)

        bbox = _parse_bbox(reply, image.width, image.height)

        if bbox is not None:
            if bbox.get("no_label"):
                logger.info("Vision reports no shipping label on this page")
                if strict:
                    return None
                # Non-strict: fall through to heuristic fallback below
            else:
                logger.info("Parsed bbox: x1=%d y1=%d x2=%d y2=%d",
                            bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"])
                cropped = _validate_and_crop(bbox, image)
                if cropped is not None:
                    return cropped
                logger.info("Vision bbox rejected by validation")
                if strict:
                    return None
        else:
            logger.warning("Failed to parse bbox from response: %s", reply)
            if strict:
                return None

        # Vision didn't produce a usable crop — fall back to heuristic
        if is_letter:
            logger.info("Falling back to letter-size heuristic crop")
            return _letter_size_fallback_crop(image)

        return image

    except Exception:
        logger.exception("Label extraction failed")
        if strict:
            return None
        if is_letter:
            logger.info("Falling back to letter-size heuristic crop")
            return _letter_size_fallback_crop(image)
        return image
