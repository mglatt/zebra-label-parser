"""Regression tests over real (sanitized) carrier label files.

See tests/fixtures/real/README.md for how to add fixtures. Skipped while
the directory contains no fixture files.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from app.services.label_extractor import _parse_bbox, _validate_and_crop
from app.services.pdf_renderer import render_pdf_page

REAL_DIR = Path(__file__).parent / "fixtures" / "real"
_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


def _fixture_files() -> list[Path]:
    if not REAL_DIR.is_dir():
        return []
    return sorted(p for p in REAL_DIR.iterdir() if p.suffix.lower() in _EXTENSIONS)


def _load_image(path: Path) -> Image.Image:
    if path.suffix.lower() == ".pdf":
        return render_pdf_page(path.read_bytes(), page=0, dpi=300)
    return Image.open(path).convert("RGB")


if not _fixture_files():
    pytest.skip(
        "no real fixtures present (see tests/fixtures/real/README.md)",
        allow_module_level=True,
    )


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_real_fixture_crop(path: Path):
    image = _load_image(path)
    sidecar = path.with_suffix(path.suffix + "").with_name(path.stem + ".expected.json")

    if not sidecar.is_file():
        # Smoke test only: the crop pipeline must produce an image for a
        # centered 80% bbox without crashing.
        bbox = {
            "x1": image.width * 0.1,
            "y1": image.height * 0.1,
            "x2": image.width * 0.9,
            "y2": image.height * 0.9,
        }
        assert _validate_and_crop(bbox, image) is not None
        return

    expected = json.loads(sidecar.read_text())
    bbox = _parse_bbox(json.dumps(expected["vision_bbox"]), image.width, image.height)
    assert bbox is not None and not bbox.get("no_label")

    result = _validate_and_crop(bbox, image)
    assert result is not None, f"{path.name}: bbox rejected"

    if "min_crop_px" in expected:
        min_w, min_h = expected["min_crop_px"]
        assert result.width >= min_w and result.height >= min_h, (
            f"{path.name}: crop {result.size} below minimum {expected['min_crop_px']}"
        )
    if "max_crop_px" in expected:
        max_w, max_h = expected["max_crop_px"]
        assert result.width <= max_w and result.height <= max_h, (
            f"{path.name}: crop {result.size} above maximum {expected['max_crop_px']}"
        )
