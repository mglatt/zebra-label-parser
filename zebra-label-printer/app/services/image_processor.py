"""Prepare images for thermal label printing."""
from __future__ import annotations

import logging

from PIL import Image

logger = logging.getLogger(__name__)


def _trim_whitespace(
    img: Image.Image, margin: int = 10, threshold: int = 245
) -> Image.Image:
    """Remove white/near-white borders so content dimensions are accurate.

    Converts to grayscale, treats pixels darker than *threshold* as content,
    and crops to the bounding box of that content plus *margin* pixels on
    each side.  Returns the original image unchanged when it is entirely
    white or when trimming would remove less than 5 % of the area.
    """
    gray = img.convert("L")
    binary = gray.point(lambda p: 255 if p < threshold else 0)
    bbox = binary.getbbox()
    if bbox is None:
        return img  # entirely white / near-white

    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - margin)
    y1 = max(0, y1 - margin)
    x2 = min(img.width, x2 + margin)
    y2 = min(img.height, y2 + margin)

    trimmed_area = (x2 - x1) * (y2 - y1)
    if trimmed_area / (img.width * img.height) > 0.95:
        return img  # almost no whitespace to remove

    logger.info(
        "Trimmed whitespace: %dx%d -> %dx%d",
        img.width, img.height, x2 - x1, y2 - y1,
    )
    return img.crop((x1, y1, x2, y2))


def prepare_label_image(
    image: Image.Image,
    width: int = 812,
    height: int = 1218,
    dither: bool = False,
    scale_pct: int = 100,
) -> Image.Image:
    """Resize, orient, and convert an image to a 1-bit monochrome label.

    - Trims whitespace so rotation/centering uses actual content bounds
    - Auto-rotates landscape images to portrait orientation
    - Resizes to fit within width x height preserving aspect ratio
    - scale_pct (50-100) shrinks the image within the label, adding margins
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
    target_w = int(width * s)
    target_h = int(height * s)

    # Scale to fit within target dimensions, preserving aspect ratio
    scale = min(target_w / img.width, target_h / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # ZPL ^GF requires width in whole bytes (multiples of 8 pixels)
    padded_width = width if width % 8 == 0 else width + (8 - width % 8)

    # Center on white canvas
    canvas = Image.new("RGB", (padded_width, height), (255, 255, 255))
    offset_x = (padded_width - new_w) // 2
    offset_y = (height - new_h) // 2
    canvas.paste(img, (offset_x, offset_y))

    # Convert to monochrome
    if dither:
        mono = canvas.convert("1")  # Floyd-Steinberg dithering (Pillow default)
    else:
        mono = canvas.convert("1", dither=Image.Dither.NONE)

    return mono
