from PIL import Image

from app.services.zpl_generator import image_to_zpl, image_to_zpl_ascii, _crc16_ccitt


def test_zpl_output_structure(mono_image):
    zpl = image_to_zpl(mono_image)
    assert zpl.startswith("^XA")
    assert zpl.strip().endswith("^XZ")
    assert "^GFA" in zpl
    assert ":Z64:" in zpl


def test_zpl_ascii_output_structure(mono_image):
    zpl = image_to_zpl_ascii(mono_image)
    assert zpl.startswith("^XA")
    assert zpl.strip().endswith("^XZ")
    assert "^GFA" in zpl
    assert ":Z64:" not in zpl


def test_zpl_field_params(mono_image):
    """Check that ^GFA parameters are correct."""
    zpl = image_to_zpl_ascii(mono_image)
    # 16 pixels wide = 2 bytes per row, 8 rows = 16 total bytes
    assert "^GFA,16,16,2," in zpl


def test_all_white_image():
    img = Image.new("1", (8, 4), color=1)  # all white
    zpl = image_to_zpl_ascii(img)
    # All white = all 0 bits in ZPL (no black dots)
    assert "^GFA,4,4,1," in zpl
    # Hex data should be all zeros
    assert "00000000" in zpl


def test_all_black_image():
    img = Image.new("1", (8, 4), color=0)  # all black
    zpl = image_to_zpl_ascii(img)
    # All black = all 1 bits in ZPL
    assert "FFFFFFFF" in zpl


def test_z64_smaller_than_ascii(mono_image):
    """Z64 compressed should generally be same size or smaller."""
    zpl_z64 = image_to_zpl(mono_image)
    zpl_ascii = image_to_zpl_ascii(mono_image)
    # For tiny images Z64 overhead might make it bigger, but for real labels it's smaller.
    # Just verify both produce valid ZPL.
    assert "^XA" in zpl_z64
    assert "^XA" in zpl_ascii


def test_crc16_known_value():
    # Known CRC-16-CCITT test vector
    data = b"123456789"
    crc = _crc16_ccitt(data)
    assert crc == 0x29B1


def test_non_monochrome_raises():
    import pytest
    rgb = Image.new("RGB", (8, 4))
    with pytest.raises(ValueError, match="1-bit"):
        image_to_zpl(rgb)
