"""Convert monochrome PIL images to ZPL graphic field commands."""
from __future__ import annotations

import base64
import struct
import zlib

from PIL import Image


def _crc16_ccitt(data: bytes) -> int:
    """CRC-16-CCITT (0xFFFF initial) used by ZPL Z64 encoding."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


def _image_to_bytes(image: Image.Image) -> tuple[bytes, int, int]:
    """Convert a 1-bit PIL image to raw bitmap bytes.

    In ZPL, a set bit (1) = black, cleared bit (0) = white.
    Pillow 1-bit mode: 0 = black, 255 = white.
    So we need to invert: ZPL byte = ~PIL byte.

    Returns (data, bytes_per_row, total_bytes).
    """
    if image.mode != "1":
        raise ValueError(f"Expected 1-bit image, got mode '{image.mode}'")

    width, height = image.size
    bytes_per_row = (width + 7) // 8

    rows = []
    for y in range(height):
        row_byte = 0
        row_bytes = bytearray()
        for x in range(width):
            pixel = image.getpixel((x, y))
            bit_pos = 7 - (x % 8)
            # Pillow: 0=black, 255=white. ZPL: 1=black, 0=white.
            if pixel == 0:
                row_byte |= (1 << bit_pos)
            if x % 8 == 7:
                row_bytes.append(row_byte)
                row_byte = 0
        # Flush partial byte at end of row
        if width % 8 != 0:
            row_bytes.append(row_byte)
        rows.append(bytes(row_bytes))

    data = b"".join(rows)
    return data, bytes_per_row, len(data)


def image_to_zpl(image: Image.Image) -> str:
    """Convert a 1-bit image to ZPL using Z64 compression.

    Z64 = zlib-compressed, base64-encoded, with CRC-16-CCITT checksum.
    Typical compression ratio for shipping labels: ~10-20x.
    """
    data, bytes_per_row, total_bytes = _image_to_bytes(image)

    compressed = zlib.compress(data, level=9)
    encoded = base64.b64encode(compressed).decode("ascii")
    crc = _crc16_ccitt(compressed)
    crc_hex = format(crc, "04X")

    zpl = (
        f"^XA\n"
        f"^FO0,0\n"
        f"^GFA,{total_bytes},{total_bytes},{bytes_per_row},"
        f":Z64:{encoded}:{crc_hex}\n"
        f"^FS\n"
        f"^XZ\n"
    )
    return zpl


def image_to_zpl_ascii(image: Image.Image) -> str:
    """Convert a 1-bit image to ZPL using uncompressed ASCII hex.

    Fallback for printers that don't support Z64.
    """
    data, bytes_per_row, total_bytes = _image_to_bytes(image)
    hex_data = data.hex().upper()

    zpl = (
        f"^XA\n"
        f"^FO0,0\n"
        f"^GFA,{total_bytes},{total_bytes},{bytes_per_row},"
        f"{hex_data}\n"
        f"^FS\n"
        f"^XZ\n"
    )
    return zpl
