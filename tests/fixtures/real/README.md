# Real carrier label fixtures

Drop sanitized real carrier files here (PDF, PNG, or JPEG) to have them
exercised by `tests/test_real_fixtures.py`. Redact names/addresses freely —
the tests only check crop *geometry*, so what matters is that the layout
(barcodes, address blocks, slips, sidebars) is preserved.

For each fixture `<name>.<ext>`, add a sidecar `<name>.expected.json`:

```json
{
  "vision_bbox": {"x1_pct": 4, "y1_pct": 24, "x2_pct": 82, "y2_pct": 61},
  "min_crop_px": [1500, 1000],
  "max_crop_px": [2200, 1500],
  "comment": "UPS return label, rotated address column on the left"
}
```

- `vision_bbox` — a recorded Vision response (percent coordinates), so
  tests run offline and deterministically. Grab it from the app log line
  `Vision raw response:` when printing the label for real.
- `min_crop_px` / `max_crop_px` — optional [width, height] bounds the
  final crop must fall within.
- PDFs are rendered at 300 DPI, page 0.

Files without a sidecar are still smoke-tested (the crop pipeline must not
crash and must return an image). The test module is skipped entirely while
this directory has no fixtures.

Most valuable additions: a UPS return label, an Amazon return label with
rotated sidebar text, a FedEx full-page label, a USPS full-page label, and
a bare 4x6 label PNG.
