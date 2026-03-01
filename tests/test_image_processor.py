from PIL import Image

from app.services.image_processor import prepare_label_image, _trim_whitespace


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


# --- Whitespace trimming tests ---


def test_trim_removes_wide_white_borders():
    """Portrait content in a landscape crop should be trimmed to portrait."""
    # Simulate a loose Vision crop: 600x300 landscape canvas with
    # a 200x280 portrait content block in the centre.
    img = Image.new("RGB", (600, 300), (255, 255, 255))
    # Draw dark content block in center
    for x in range(200, 400):
        for y in range(10, 290):
            img.putpixel((x, y), (0, 0, 0))

    trimmed = _trim_whitespace(img)
    # After trimming, width should be much smaller than 600
    assert trimmed.width < 300
    # Content is taller than wide, so trimmed should be portrait
    assert trimmed.height > trimmed.width


def test_trim_no_whitespace_unchanged():
    """An image with no significant whitespace borders is returned as-is."""
    img = Image.new("RGB", (200, 300), (100, 100, 100))
    trimmed = _trim_whitespace(img)
    assert trimmed.width == 200
    assert trimmed.height == 300


def test_trim_all_white_unchanged():
    """An entirely white image is returned unchanged."""
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    trimmed = _trim_whitespace(img)
    assert trimmed.width == 200
    assert trimmed.height == 200


def test_trim_prevents_false_landscape_rotation():
    """Portrait label in a wide crop should NOT be rotated after trimming."""
    # 500x200 landscape crop, but content is a 150x180 portrait block
    img = Image.new("RGB", (500, 200), (255, 255, 255))
    for x in range(175, 325):
        for y in range(10, 190):
            img.putpixel((x, y), (0, 0, 0))

    # Without trimming: 500>200 → landscape detected → would rotate
    # With trimming: content is ~150x180 → portrait → no rotation
    result = prepare_label_image(img, width=80, height=120)
    assert result.mode == "1"
    assert result.width % 8 == 0
    assert result.height == 120


def test_trim_true_landscape_still_rotates():
    """Genuinely landscape content should still be auto-rotated."""
    # 400x200 image with landscape content filling most of it
    img = Image.new("RGB", (400, 200), (0, 0, 0))
    trimmed = _trim_whitespace(img)
    # Content fills the image, so trim shouldn't change it
    assert trimmed.width == 400
    assert trimmed.height == 200

    result = prepare_label_image(img, width=80, height=120)
    assert result.mode == "1"
