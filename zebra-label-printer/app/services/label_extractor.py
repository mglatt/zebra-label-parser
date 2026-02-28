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
Analyze this image and locate the shipping label. The shipping label is the \
rectangular region containing the delivery address, return address, barcodes, \
and carrier information (e.g., UPS, FedEx, USPS, DHL).

If the image contains only a shipping label with no surrounding content, \
return the full image dimensions.

If the image contains a shipping label embedded within other content \
(instructions, packing slips, etc.), return the bounding box of just the \
shipping label.

Return ONLY a JSON object with these exact keys:
{
  "found": true,
  "x1": <left edge in pixels>,
  "y1": <top edge in pixels>,
  "x2": <right edge in pixels>,
  "y2": <bottom edge in pixels>
}

If no shipping label is found, return:
{"found": false}
"""


def _image_to_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _parse_bbox(text: str) -> Optional[dict]:
    """Extract JSON bounding box from Claude's response."""
    # Find the JSON object in the response
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        data = json.loads(text[start:end])
        if not data.get("found", False):
            return None
        for key in ("x1", "y1", "x2", "y2"):
            if key not in data:
                return None
        return data
    except (json.JSONDecodeError, TypeError):
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
            max_tokens=256,
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
                }
            ],
        )

        reply = response.content[0].text
        bbox = _parse_bbox(reply)

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
