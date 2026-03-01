"""Use Claude Vision API to identify and extract shipping labels from images."""
from __future__ import annotations

import base64
import io
import json
import logging
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Locate the shipping label in this image and return its TIGHT bounding box.

A shipping label is approximately 4x6 inches (portrait orientation — taller \
than wide) and contains: delivery address, return address, carrier barcodes, \
and carrier branding (UPS, FedEx, USPS, DHL).

IMPORTANT: The label is PORTRAIT (taller than wide). If you see a label region \
that appears landscape (wider than tall), look more carefully — the actual \
label is likely a portrait sub-region within it.

On full-page documents (8.5x11"), exclude everything that is NOT part of the \
label: receipts, customs forms, instructions, fold lines, scissors icons. \
Return ONLY the label itself.

Return the TIGHT bounding box as percentages of image dimensions (0-100). \
The box should closely hug the label edges with minimal extra whitespace:

{"x1_pct": <left>, "y1_pct": <top>, "x2_pct": <right>, "y2_pct": <bottom>}

If the shipping label fills the entire image, return:
{"x1_pct": 0, "y1_pct": 0, "x2_pct": 100, "y2_pct": 100}

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


def _validate_and_crop(
    bbox: dict, image: Image.Image
) -> Optional[Image.Image]:
    """Validate bbox and return cropped image, or None if invalid."""
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

    # Clamp to image bounds and crop
    x1 = max(0, int(x1))
    y1 = max(0, int(y1))
    x2 = min(width, int(x2))
    y2 = min(height, int(y2))

    cropped = image.crop((x1, y1, x2, y2))
    logger.info("Vision crop: (%d,%d)-(%d,%d) = %dx%d (%.1f%% of page)",
                x1, y1, x2, y2, cropped.width, cropped.height, coverage * 100)
    return cropped


async def extract_label_region(
    image: Image.Image,
    api_key: Optional[str],
    model: str = "claude-sonnet-4-20250514",
) -> Image.Image:
    """Use Claude Vision to find and crop the shipping label from an image.

    Returns the cropped label region, or the original image if extraction
    fails or no API key is configured.

    Falls back to a letter-size heuristic crop if Vision doesn't produce
    a usable result on a letter-size input.
    """
    is_letter = _is_letter_size(image.width, image.height)
    logger.info(
        "Extraction input: %dx%d, letter_size=%s, has_api_key=%s",
        image.width, image.height, is_letter, bool(api_key),
    )

    if not api_key:
        logger.info("No API key configured, skipping Vision extraction")
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

        reply = response.content[0].text
        logger.info("Vision raw response: %s", reply)

        bbox = _parse_bbox(reply, image.width, image.height)

        if bbox is not None:
            logger.info("Parsed bbox: x1=%d y1=%d x2=%d y2=%d", bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"])
            cropped = _validate_and_crop(bbox, image)
            if cropped is not None:
                return cropped
            logger.info("Vision bbox rejected by validation")
        else:
            logger.warning("Failed to parse bbox from response: %s", reply)

        # Vision didn't produce a usable crop — fall back to heuristic
        if is_letter:
            logger.info("Falling back to letter-size heuristic crop")
            return _letter_size_fallback_crop(image)

        return image

    except Exception:
        logger.exception("Label extraction failed")
        if is_letter:
            logger.info("Falling back to letter-size heuristic crop")
            return _letter_size_fallback_crop(image)
        return image
