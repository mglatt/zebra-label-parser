"""Use Claude Vision API to identify and extract shipping labels from images."""
from __future__ import annotations

import base64
import io
import json
import logging
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Locate the shipping label in this image and return its TIGHT bounding box.

A shipping label is approximately 4x6 inches and contains: delivery address, \
return address, carrier barcodes, and carrier branding (UPS, FedEx, USPS, DHL). \
The label may be oriented portrait OR landscape on the page.

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
the bounding box must be STRICTLY INSIDE those lines. Do not include any \
content outside the dashed rectangle, even if it is adjacent to the label. \
The bounding box should approximate the label's 4x6 inch proportions \
(either portrait or landscape).

Return the bounding box as percentages of image dimensions (0-100):

{"x1_pct": <left>, "y1_pct": <top>, "x2_pct": <right>, "y2_pct": <bottom>}

If the shipping label fills the entire image, return:
{"x1_pct": 0, "y1_pct": 0, "x2_pct": 100, "y2_pct": 100}

If there is NO shipping label in this image (e.g. it is an instruction page, \
packing slip, or receipt with no carrier label), return:
{"no_label": true}

Return ONLY valid JSON, no other text."""


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
            data = {
                "x1": data["x1_pct"] / 100.0 * width,
                "y1": data["y1_pct"] / 100.0 * height,
                "x2": data["x2_pct"] / 100.0 * width,
                "y2": data["y2_pct"] / 100.0 * height,
            }

        for key in ("x1", "y1", "x2", "y2"):
            if key not in data:
                return None

        # Snap to 10px grid to reduce run-to-run jitter
        _GRID = 10
        data["x1"] = int(data["x1"] // _GRID * _GRID)
        data["y1"] = int(data["y1"] // _GRID * _GRID)
        data["x2"] = int(-(-data["x2"] // _GRID) * _GRID)  # ceil to grid
        data["y2"] = int(-(-data["y2"] // _GRID) * _GRID)

        return data
    except (json.JSONDecodeError, TypeError, KeyError):
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

    Only trims if a clear whitespace gap is found in the outer portion
    of the image (outer 25% on each side).
    """
    arr = np.array(image.convert("L"))
    h, w = arr.shape

    # Minimum dimension — don't tighten tiny crops
    if w < 200 or h < 200:
        return image

    # Threshold: pixels below this are "dark" (ink)
    _DARK_THRESH = 200
    # A column/row is "whitespace" if fewer than this fraction of pixels are dark
    _WS_FRAC = 0.02
    # Minimum width of a whitespace band to count as a gap (pixels)
    _MIN_BAND = 8
    # Only look in the outer portion of each edge
    _EDGE_FRAC = 0.25

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


def _validate_and_crop(
    bbox: dict, image: Image.Image
) -> Optional[Image.Image]:
    """Validate bbox and return cropped image, or None if invalid.

    Accepts both portrait and landscape crops — the image processor
    handles rotation later.
    """
    width, height = image.width, image.height
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]

    # Must be positive dimensions
    if x2 <= x1 or y2 <= y1:
        logger.warning("Invalid bbox dimensions: (%d,%d)-(%d,%d)", x1, y1, x2, y2)
        return None

    # Must be within image bounds (with small tolerance)
    if x1 < -5 or y1 < -5 or x2 > width + 5 or y2 > height + 5:
        logger.warning("Bbox out of bounds: (%d,%d)-(%d,%d) for %dx%d image", x1, y1, x2, y2, width, height)
        return None

    bbox_area = (x2 - x1) * (y2 - y1)
    image_area = width * height
    coverage = bbox_area / image_area

    # Too small = likely wrong
    if coverage < 0.10:
        logger.warning("Bbox too small (%.1f%% of image)", coverage * 100)
        return None

    # Covers >90% of the image = no meaningful crop
    if coverage > 0.90:
        logger.info("Bbox covers %.1f%% of image, no meaningful crop", coverage * 100)
        return None

    # Trim bbox to approximate a 4×6" label aspect ratio (1.5:1).
    # A ratio far from 1.5 likely means the crop includes content outside
    # the label (e.g., a return authorization slip barcode below the label).
    crop_w = x2 - x1
    crop_h = y2 - y1
    long_side = max(crop_w, crop_h)
    short_side = min(crop_w, crop_h)
    ratio = long_side / short_side if short_side > 0 else 0

    _EXPECTED_RATIO = 1.5  # 4×6 label
    _MIN_RATIO = 1.3
    _MAX_RATIO = 2.2

    if 0 < ratio < _MIN_RATIO:
        # Too square — trim the longer dimension to ~1.5 ratio
        if crop_w >= crop_h:
            # Landscape: trim from bottom (return slips are typically below)
            y2 = y1 + int(crop_w / _EXPECTED_RATIO)
        else:
            # Portrait: trim from right
            x2 = x1 + int(crop_h / _EXPECTED_RATIO)
        logger.info("Bbox ratio %.2f too square, trimmed to ~%.1f ratio", ratio, _EXPECTED_RATIO)
    elif ratio > _MAX_RATIO:
        # Too elongated — trim the longer dimension
        if crop_w >= crop_h:
            # Very wide: trim from right
            x2 = x1 + int(crop_h * _EXPECTED_RATIO)
        else:
            # Very tall: trim from bottom
            y2 = y1 + int(crop_w * _EXPECTED_RATIO)
        logger.info("Bbox ratio %.2f too elongated, trimmed to ~%.1f ratio", ratio, _EXPECTED_RATIO)

    # Add safety margin to prevent edge content (barcodes) from being clipped.
    # _trim_whitespace() in the image processor removes excess whitespace later.
    margin_x = max(30, int(width * 0.015))
    margin_y = max(30, int(height * 0.015))
    x1 = max(0, int(x1) - margin_x)
    y1 = max(0, int(y1) - margin_y)
    x2 = min(width, int(x2) + margin_x)
    y2 = min(height, int(y2) + margin_y)

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

        response = await client.messages.create(
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
