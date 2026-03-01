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
Locate the shipping label in this image and return its bounding box.

A shipping label is the rectangular region containing:
- Delivery address and return address
- Carrier barcodes (tracking barcode, routing barcode)
- Carrier branding (UPS, FedEx, USPS, DHL)

Common layouts you will encounter:
- A full 8.5x11" page from USPS, FedEx, or UPS that contains the 4x6" \
shipping label PLUS a receipt, customs form, or instructions. You MUST crop \
to just the shipping label, excluding the receipt and instructions.
- A standalone 4x6" shipping label with no surrounding content.
- A photo of a shipping label on a package.

ALWAYS return the bounding box of the shipping label as percentages of the \
image dimensions (0-100):

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


def _validate_bbox(bbox: dict, width: int, height: int) -> str:
    """Check that the bounding box is reasonable.

    Returns:
        "crop"  – bbox is valid, crop to it
        "full"  – bbox covers the whole image or is invalid, use full image
    """
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]

    # Must be positive dimensions
    if x2 <= x1 or y2 <= y1:
        return "full"

    # Must be within image bounds (with small tolerance)
    if x1 < -5 or y1 < -5 or x2 > width + 5 or y2 > height + 5:
        return "full"

    bbox_area = (x2 - x1) * (y2 - y1)
    image_area = width * height
    coverage = bbox_area / image_area

    # Too small = likely wrong
    if coverage < 0.10:
        logger.warning("Bbox too small (%.1f%% of image), using full image", coverage * 100)
        return "full"

    # Covers >90% of the image = it's already just a label, skip crop
    if coverage > 0.90:
        logger.info("Bbox covers %.1f%% of image, skipping crop", coverage * 100)
        return "full"

    return "crop"


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

        action = _validate_bbox(bbox, image.width, image.height)
        if action == "full":
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
