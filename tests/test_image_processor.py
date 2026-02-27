from PIL import Image

from app.services.image_processor import prepare_label_image


def test_output_is_monochrome(sample_image):
    result = prepare_label_image(sample_image, width=80, height=120)
    assert result.mode == "1"


def test_output_dimensions(sample_image):
    result = prepare_label_image(sample_image, width=80, height=120)
    assert result.width == 80  # 80 is divisible by 8
    assert result.height == 120


def test_width_padded_to_byte_boundary():
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    result = prepare_label_image(img, width=50, height=75)
    # 50 is not divisible by 8, should be padded to 56
    assert result.width % 8 == 0
    assert result.width == 56


def test_landscape_auto_rotates(sample_landscape_image):
    result = prepare_label_image(sample_landscape_image, width=80, height=120)
    assert result.mode == "1"
    # Should fit within label dimensions
    assert result.width <= 80 + 8  # allow byte padding
    assert result.height == 120


def test_no_dither(sample_image):
    result = prepare_label_image(sample_image, width=80, height=120, dither=False)
    assert result.mode == "1"


def test_preserves_aspect_ratio():
    # Tall narrow image
    img = Image.new("RGB", (100, 600), (128, 128, 128))
    result = prepare_label_image(img, width=80, height=120)
    assert result.mode == "1"
    assert result.height == 120
