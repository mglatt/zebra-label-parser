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
You are a shipping label detector. Your ONLY job is to return a JSON bounding \
box for the shipping label in this image.

Rules:
1. A shipping label contains: delivery address, return address, barcodes, and \
carrier branding (UPS, FedEx, USPS, DHL, etc.).
2. If the ENTIRE image is a shipping label (no surrounding content like \
instructions or packing slips), return: {"found": false}
3. If the image contains a shipping label embedded within other content, return \
the bounding box as percentages of image dimensions (0-100):

{"found": true, "x1_pct": <left>, "y1_pct": <top>, "x2_pct": <right>, "y2_pct": <bottom>}

Return ONLY valid JSON, no other text."""


def _image_to_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _parse_bbox(text: str, width: int, height: int) -> Optional[dict]:
    """Extract JSON bounding box from Claude's response.

    Handles both percentage-based keys (x1_pct) and legacy pixel keys (x1).
    Returns pixel coordinates snapped to a 10px grid for consistency.
    """
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        data = json.loads(text[start:end])
        if not data.get("found", False):
            return None

        # Convert percentage coords to pixels
        if "x1_pct" in data:
            data = {
                "found": True,
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


def _validate_bbox(bbox: dict, width: int, height: int) -> bool:
    """Check that the bounding box is reasonable."""
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]

    # Must be positive dimensions
    if x2 <= x1 or y2 <= y1:
        return False

    # Must be within image bounds (with small tolerance)
    if x1 < -5 or y1 < -5 or x2 > width + 5 or y2 > height + 5:
        return False

    # Must cover at least 10% of the image area (too small = likely wrong)
    bbox_area = (x2 - x1) * (y2 - y1)
    image_area = width * height
    if bbox_area < image_area * 0.10:
        logger.warning("Bbox too small (%.1f%% of image), using full image", bbox_area / image_area * 100)
        return False

    return True


async def extract_label_region(
    image: Image.Image,
    api_key: Optional[str],
    model: str = "claude-sonnet-4-20250514",
) -> Image.Image:
    """Use Claude Vision to find and crop the shipping label from an image.

    Returns the cropped label region, or the original image if extraction
    fails or no API key is configured.
    """
    if not api_key:
        logger.info("No API key configured, skipping label extraction")
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
                # Prefill forces the model to emit JSON immediately
                {
                    "role": "assistant",
                    "content": "{",
                },
            ],
        )

        reply = "{" + response.content[0].text
        bbox = _parse_bbox(reply, image.width, image.height)

        if bbox is None:
            logger.info("No label region detected, using full image")
            return image

        if not _validate_bbox(bbox, image.width, image.height):
            return image

        # Clamp to image bounds
        x1 = max(0, int(bbox["x1"]))
        y1 = max(0, int(bbox["y1"]))
        x2 = min(image.width, int(bbox["x2"]))
        y2 = min(image.height, int(bbox["y2"]))

        cropped = image.crop((x1, y1, x2, y2))
        logger.info("Extracted label region: (%d,%d)-(%d,%d)", x1, y1, x2, y2)
        return cropped

    except Exception:
        logger.exception("Label extraction failed, using full image")
        return image
