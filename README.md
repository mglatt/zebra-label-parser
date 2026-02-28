# Zebra Label Parser

A service that ingests shipping label PDFs or images, extracts the label using Claude AI vision, and prints to a Zebra thermal printer via ZPL/CUPS.

## Features

- **Drag-and-drop web UI** for non-technical users
- **AI label extraction** — Claude Vision identifies and crops shipping labels from cluttered PDFs
- **Automatic image processing** — resizes to 4x6", converts to monochrome with dithering
- **ZPL generation** with Z64 compression for fast printer transfer
- **CUPS integration** — works with any CUPS-configured Zebra printer (USB or network)
- **Graceful fallback** — works without an API key by printing the full page as-is

## Quick Start

### Local Development

```bash
cp .env.example zebra-label-printer/.env
# Edit .env with your settings

cd zebra-label-printer
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8099
```

Open http://localhost:8099 in your browser.

### Docker

```bash
cp .env.example .env
# Edit .env with your settings

docker compose up --build
```

### Docker (standalone)

```bash
docker build -t zebra-label-parser zebra-label-printer/
docker run -p 8099:8099 \
  -e ZLP_ANTHROPIC_API_KEY=your-key \
  -e ZLP_PRINTER_NAME=Zebra_ZD420 \
  -v /var/run/cups:/var/run/cups:ro \
  zebra-label-parser
```

### Home Assistant Addon

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click **⋮** (three dots menu) → **Repositories**
3. Add: `https://github.com/mglatt/zebra-label-parser`
4. Find **Zebra Label Printer** in the store and click **Install**

## How It Works

1. **Upload** — User drops a PDF or image in the web UI
2. **Render** — PDFs are rendered to images at 300 DPI (PyMuPDF)
3. **Extract** — Claude Vision identifies the shipping label bounding box and crops it
4. **Process** — Image is resized to 4x6" @ 203 DPI, auto-rotated, and converted to monochrome
5. **ZPL** — Monochrome bitmap is encoded as ZPL `^GF` with Z64 compression (~10-20x smaller)
6. **Print** — ZPL is sent to the Zebra printer via CUPS as a raw job

## API

- `GET /api/health` — Health check
- `GET /api/printers` — List CUPS printers
- `POST /api/labels/print` — Upload and print a label (multipart form: `file` + optional `printer`)

## Configuration

All settings use the `ZLP_` env prefix. See [.env.example](.env.example) for all options.

| Variable | Default | Description |
|----------|---------|-------------|
| `ZLP_ANTHROPIC_API_KEY` | *(none)* | Claude API key for label extraction |
| `ZLP_PRINTER_NAME` | *(none)* | Default CUPS printer name |
| `ZLP_LABEL_DPI` | `203` | Printer resolution |
| `ZLP_LABEL_WIDTH_INCHES` | `4.0` | Label width |
| `ZLP_LABEL_HEIGHT_INCHES` | `6.0` | Label height |

## Printer Setup

Configure your Zebra printer in CUPS as a **raw** queue:

```bash
# Network printer
lpadmin -p Zebra_ZD420 -v socket://192.168.1.100:9100 -m raw -E

# USB printer (auto-detected by CUPS)
lpadmin -p Zebra_ZD420 -v usb://Zebra/ZD420 -m raw -E
```

## Tests

```bash
cd zebra-label-printer
pip install -e ".[dev]"
cd ..
pytest
```
