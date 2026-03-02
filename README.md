# Zebra Label Parser

A service that ingests shipping label PDFs or images, extracts the label using Claude AI vision, and prints to a Zebra thermal printer via ZPL/CUPS. Runs as a Home Assistant addon with a drag-and-drop web UI, or standalone via Docker.

## Features

- **Drag-and-drop web UI** with printer selector, scale control, and live print preview
- **AI label extraction** — Claude Vision identifies and crops shipping labels from cluttered, multi-page PDFs
- **Multi-page PDF support** — scans each page to find the one containing the shipping label
- **Heuristic fallback** — works without an API key by cropping the label region from letter-size pages
- **Automatic image processing** — trims whitespace, auto-rotates, resizes to 4x6", converts to monochrome with dithering
- **ZPL generation** with ASCII hex encoding and proper page size commands
- **CUPS integration** — streams ZPL over IPP to any CUPS-configured Zebra printer (USB or network)
- **Virtual CUPS printer** — print from any macOS or Linux app via a `zebrahttp` CUPS backend and Bonjour discovery
- **macOS Quick Action** — right-click any file in Finder to print
- **iOS Shortcut** — share from any iPhone app to print
- **Webhook API** — print from Home Assistant automations, folder watchers, or any HTTP client
- **API key authentication** — optional auth for direct port access (ingress always allowed)
- **Docker health check** — built-in `/api/health` and `/api/debug` diagnostics

## Quick Start

### Home Assistant Addon

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
2. Click **⋮** (three dots menu) → **Repositories**
3. Add: `https://github.com/mglatt/zebra-label-parser`
4. Find **Zebra Label Printer** in the store and click **Install**
5. Set your **Printer Name** (must match a CUPS queue on your network)
6. Optionally add your **Anthropic API Key** for AI label extraction

### Docker Compose

The easiest way to run standalone. The included `docker-compose.yml` reads
settings from a `.env` file:

```bash
cp .env.example .env
# Edit .env — set at least ZLP_PRINTER_NAME
docker compose up --build
```

By default the compose file mounts the host's CUPS socket (`/var/run/cups`)
so the container can talk to printers configured on the host. If your CUPS
server is on a different machine, remove the volume mount and set
`ZLP_CUPS_SERVER` in your `.env` instead:

```env
ZLP_CUPS_SERVER=192.168.1.50:631
```

### Docker (manual)

If you'd rather run `docker run` directly:

```bash
docker build -t zebra-label-parser zebra-label-printer/

# Option A: CUPS on the same host — mount the socket
docker run -d --restart unless-stopped \
  -p 8099:8099 \
  -e ZLP_PRINTER_NAME=Zebra_LP2844 \
  -v /var/run/cups:/var/run/cups:ro \
  zebra-label-parser

# Option B: CUPS on another machine — point to it via env
docker run -d --restart unless-stopped \
  -p 8099:8099 \
  -e ZLP_PRINTER_NAME=Zebra_LP2844 \
  -e ZLP_CUPS_SERVER=192.168.1.50:631 \
  zebra-label-parser
```

Add `-e ZLP_ANTHROPIC_API_KEY=sk-...` for AI label extraction, or omit it
to use the heuristic fallback. Add `-e ZLP_API_KEY=mysecret` to require
authentication on the API.

### Local Development

```bash
cp .env.example zebra-label-printer/.env
# Edit .env with your settings

cd zebra-label-printer
pip install -e ".[dev,cups]"
uvicorn app.main:app --reload --port 8099
```

Open http://localhost:8099 in your browser.

## How It Works

1. **Upload** — User drops a PDF or image in the web UI, sends via API, shares from a phone, or prints from any app via the virtual CUPS printer
2. **Render** — PDFs are rendered to images at 300 DPI (PyMuPDF). Multi-page PDFs are scanned page-by-page.
3. **Extract** — Claude Vision identifies the shipping label bounding box and crops it. Without an API key, a heuristic fallback crops the standard label region from letter-size pages.
4. **Process** — Image is trimmed, auto-rotated, resized to 4x6" @ 203 DPI, scaled, centered, and converted to monochrome
5. **ZPL** — Monochrome bitmap is encoded as ZPL ASCII hex (`^GFA`) with `^PW`/`^LL` page size commands
6. **Print** — ZPL is streamed to the Zebra printer via CUPS as a raw IPP job

## Printing Methods

All methods work with both the HA addon and standalone Docker deployments.

| Method | Setup | Best For |
|--------|-------|----------|
| **Web UI** | None — built in | Quick one-off prints from a browser |
| **iOS Shortcut** | One-time Shortcut setup | Printing from phone (Mail, Safari, Files) |
| **Virtual CUPS printer** | `cups/setup-virtual-printer.sh` | Printing from any Mac/Linux app via system print dialog |
| **macOS Quick Action** | `macos/install-quick-action.sh` | Right-click to print in Finder |
| **Folder watcher** | HA automation + Samba | Household shared folder auto-print |
| **Webhook API** | HTTP client or `curl` | Automations and integrations |

See [DOCS.md](zebra-label-printer/DOCS.md) for detailed setup instructions for each method.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/labels/print` | POST | Upload and print (multipart: `file`, optional `printer`, `scale`) |
| `/api/labels/webhook` | POST | Print from file path or base64 (JSON body) |
| `/api/printers` | GET | List CUPS printers with status |
| `/api/health` | GET | Health check |
| `/api/debug` | GET | Diagnostic info |

## Configuration

All settings use the `ZLP_` env prefix. See [.env.example](.env.example) for all options.

| Variable | Default | Description |
|----------|---------|-------------|
| `ZLP_API_KEY` | *(none)* | Optional auth for direct port access |
| `ZLP_ANTHROPIC_API_KEY` | *(none)* | Claude API key for AI label extraction |
| `ZLP_CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model for label detection |
| `ZLP_PRINTER_NAME` | *(none)* | Default CUPS printer name |
| `ZLP_CUPS_SERVER` | *(local)* | Remote CUPS server (`host:port`) |
| `ZLP_LABEL_DPI` | `203` | Printer resolution |
| `ZLP_LABEL_WIDTH_INCHES` | `4.0` | Label width |
| `ZLP_LABEL_HEIGHT_INCHES` | `6.0` | Label height |

## Printer Setup

Configure your Zebra printer in CUPS as a **raw** queue:

```bash
# Network printer (direct TCP/IP)
lpadmin -p Zebra_LP2844 -v socket://192.168.1.100:9100 -m raw -E

# USB printer (auto-detected by CUPS)
lpadmin -p Zebra_LP2844 -v usb://Zebra/LP2844 -m raw -E
```

## Tests

```bash
cd zebra-label-printer
pip install -e ".[dev]"
pytest ../tests/
```
