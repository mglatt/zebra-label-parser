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

from app.services import crop_geometry
from app.services.crop_geometry import CropSpec

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
- Standalone instruction or heading text printed rotated 90 degrees \
  alongside the label area (e.g., "Return Authorization Slip", "Return \
  Mailing Label"). These are NOT part of the label.

IMPORTANT exception: ship-from / ship-to ADDRESS BLOCKS are often printed \
rotated 90 degrees relative to the barcodes (common on UPS and Amazon \
return labels, where the addresses run along one side of the label). \
Address blocks are ALWAYS part of the label and must be inside the \
bounding box, whatever their rotation.

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

# Default refinement parameters — see CropSpec for the tunables.
_DEFAULT_SPEC = CropSpec()


def _ink_mask(image: Image.Image, spec: CropSpec = _DEFAULT_SPEC) -> np.ndarray:
    """Boolean array (h, w): True where a pixel is dark enough to be ink."""
    return crop_geometry.ink_mask(image, spec)


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


def _content_fills_label_frame(
    image: Image.Image, expected_ratio: float = 1.5
) -> bool:
    """True when the image itself is a bare label.

    A carrier-generated label file (e.g. an Amazon "save label" PNG) has
    the configured stock's proportions with ink reaching nearly every
    edge.  Such an image IS the label — cropping it can only lose content,
    so Vision should be skipped entirely.

    Guards: the frame must be within ±10% of the label ratio, content must
    span ~85% of the frame, and the image must be mostly white (so a photo
    of a label on a dark background still goes through Vision cropping).
    """
    ratio = max(image.width, image.height) / min(image.width, image.height)
    if not (0.9 * expected_ratio <= ratio <= 1.1 * expected_ratio):
        return False

    dark = _ink_mask(image)
    if dark.mean() > 0.4:
        return False  # dark background — not a printed label file

    # Ignore stray specks: a row/column counts as content with >=3 dark px
    cols = np.nonzero(dark.sum(axis=0) >= 3)[0]
    rows = np.nonzero(dark.sum(axis=1) >= 3)[0]
    if cols.size == 0 or rows.size == 0:
        return False

    content_area = (cols[-1] - cols[0] + 1) * (rows[-1] - rows[0] + 1)
    return bool(content_area / dark.size >= 0.85)


def _letter_size_fallback_crop(
    image: Image.Image, label_size_in: tuple[float, float] = (4.0, 6.0)
) -> Image.Image:
    """Apply a heuristic crop for a standard letter-size page.

    On a typical USPS/FedEx/UPS full-page PDF, the label occupies the
    upper-left portion of the page, so crop the configured stock size as a
    fraction of the 8.5x11" page plus a generous slack margin to avoid
    clipping (with 4x6 stock: 50% x 58% portrait, 57% wide landscape).
    """
    label_short = min(label_size_in)
    label_long = max(label_size_in)

    w, h = image.width, image.height
    if w > h:
        # Landscape — the label lies rotated in the left portion
        crop_w = int(w * (label_long + 0.27) / 11.0)
        crop_h = int(h * 0.97)
        cropped = image.crop((0, 0, crop_w, crop_h))
    else:
        # Portrait — label is in the upper-left; slack avoids clipping
        crop_w = int(w * (label_short + 0.25) / 8.5)
        crop_h = int(h * (label_long + 0.38) / 11.0)
        cropped = image.crop((0, 0, crop_w, crop_h))

    logger.info(
        "Letter-size fallback crop: %dx%d -> %dx%d",
        w, h, cropped.width, cropped.height,
    )
    return cropped


def _tighten_to_content(
    image: Image.Image, spec: CropSpec = _DEFAULT_SPEC
) -> Image.Image:
    """Trim whitespace-separated bands along the crop edges (see crop_geometry)."""
    return crop_geometry.tighten_to_content(image, spec)


def _expand_into_ink(
    dark: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    spec: CropSpec = _DEFAULT_SPEC,
) -> tuple[int, int, int, int]:
    """Grow an off-aspect bbox into adjacent label ink (see crop_geometry)."""
    return crop_geometry._grow_into_ink(dark, (x1, y1, x2, y2), spec)


def _expand_to_whitespace(
    dark: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    spec: CropSpec = _DEFAULT_SPEC,
) -> tuple[int, int, int, int]:
    """Grow the bbox until every edge lies on whitespace (see crop_geometry)."""
    return crop_geometry._grow_to_whitespace(dark, (x1, y1, x2, y2), spec)


def _validate_and_crop(
    bbox: dict, image: Image.Image, spec: CropSpec = _DEFAULT_SPEC
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

    dark = _ink_mask(image, spec)

    # Refine the proposal: GROW so no edge slices the label, SHED
    # gap-separated non-label content, then the single trim+margin FINISH.
    x1, y1, x2, y2 = crop_geometry.refine_label_box(dark, (x1, y1, x2, y2), spec)

    cropped = image.crop((x1, y1, x2, y2))
    logger.info("Vision crop: (%d,%d)-(%d,%d) = %dx%d (%.1f%% of page)",
                x1, y1, x2, y2, cropped.width, cropped.height, coverage * 100)

    return cropped


async def extract_label_region(
    image: Image.Image,
    api_key: Optional[str],
    model: str = "claude-sonnet-4-20250514",
    strict: bool = False,
    usage_out: Optional[dict] = None,
    label_size_in: tuple[float, float] = (4.0, 6.0),
    dpi: Optional[float] = None,
) -> Optional[Image.Image]:
    """Use Claude Vision to find and crop the shipping label from an image.

    Returns the cropped label region.  When *strict* is ``False`` (the
    default), falls back to a letter-size heuristic crop or the original
    image so the caller always gets an image.  When *strict* is ``True``
    (used during multi-page scanning), returns ``None`` when no label is
    confidently detected — no fallbacks are applied.

    *label_size_in* is the configured label stock size in inches; *dpi* is
    the working resolution of *image* (defaults to the 300-DPI PDF render
    resolution the refinement heuristics are tuned in).
    """
    label_short, label_long = sorted(label_size_in)
    spec = CropSpec(
        expected_ratio=label_long / label_short if label_short else 1.5,
        dpi=dpi if dpi else _DEFAULT_SPEC.dpi,
    )
    is_letter = _is_letter_size(image.width, image.height)
    logger.info(
        "Extraction input: %dx%d, letter_size=%s, has_api_key=%s, strict=%s",
        image.width, image.height, is_letter, bool(api_key), strict,
    )

    # The image itself is a bare label (label proportions, content edge to
    # edge): use it whole.  Asking Vision for a bbox here can only lose
    # content — there is nothing to crop away.
    if _content_fills_label_frame(image, spec.expected_ratio):
        logger.info("Image is already a bare label (content fills label frame), using full image")
        return image

    if not api_key:
        logger.info("No API key configured, skipping Vision extraction")
        if strict:
            return None
        if is_letter:
            return _letter_size_fallback_crop(image, label_size_in)
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
                cropped = _validate_and_crop(bbox, image, spec)
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
            return _letter_size_fallback_crop(image, label_size_in)

        return image

    except Exception:
        logger.exception("Label extraction failed")
        if strict:
            return None
        if is_letter:
            logger.info("Falling back to letter-size heuristic crop")
            return _letter_size_fallback_crop(image, label_size_in)
        return image
