"""Prepare images for thermal label printing."""
from __future__ import annotations

import logging

from PIL import Image

from app.services import crop_geometry
from app.services.crop_geometry import CropSpec

logger = logging.getLogger(__name__)

_DEFAULT_SPEC = CropSpec()


def _trim_whitespace(img: Image.Image) -> Image.Image:
    """Remove whitespace borders so content dimensions are accurate.

    Delegates to the shared trim stage in crop_geometry (same ink
    threshold and margin as the crop pipeline).
    """
    return crop_geometry.trim_to_content(img, _DEFAULT_SPEC)


def prepare_label_image(
    image: Image.Image,
    width: int = 812,
    height: int = 1218,
    dither: bool = False,
    scale_pct: int = 100,
    left_offset: int = 0,
) -> Image.Image:
    """Resize, orient, and convert an image to a 1-bit monochrome label.

    - Trims whitespace so rotation/centering uses actual content bounds
    - Auto-rotates landscape images to portrait orientation
    - Resizes to fit within width x height preserving aspect ratio
    - scale_pct (50-100) shrinks the image within the label, adding margins
    - left_offset shifts content right to avoid the printer's non-printable
      left margin (typically ~28 dots on Zebra printers)
    - Pads shorter dimension with white
    - Converts to 1-bit monochrome (threshold by default, dithering optional)
    """
    img = image.convert("RGB")

    # Trim whitespace so dimensions reflect actual content, not a loose crop
    img = _trim_whitespace(img)

    # Auto-rotate: if image is landscape but label is portrait, rotate
    img_landscape = img.width > img.height
    label_portrait = height > width
    if img_landscape and label_portrait:
        img = img.rotate(90, expand=True)

    # Apply scale — shrink the target area, image gets centered with margins
    s = max(50, min(100, scale_pct)) / 100.0
    # Reserve left_offset pixels so content avoids the non-printable left margin
    usable_width = width - left_offset
    target_w = int(usable_width * s)
    target_h = int(height * s)

    # Scale to fit within target dimensions, preserving aspect ratio
    scale = min(target_w / img.width, target_h / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # ZPL ^GF requires width in whole bytes (multiples of 8 pixels)
    padded_width = width if width % 8 == 0 else width + (8 - width % 8)

    # Center within usable area (shifted right by left_offset), then on canvas
    canvas = Image.new("RGB", (padded_width, height), (255, 255, 255))
    offset_x = left_offset + (usable_width - new_w) // 2
    offset_y = (height - new_h) // 2
    canvas.paste(img, (offset_x, offset_y))

    # Convert to monochrome
    if dither:
        mono = canvas.convert("1")  # Floyd-Steinberg dithering (Pillow default)
    else:
        mono = canvas.convert("1", dither=Image.Dither.NONE)

    return mono
