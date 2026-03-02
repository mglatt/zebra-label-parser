# Zebra Label Printer

Print shipping labels from any PDF or image to a Zebra thermal printer. Supports drag-and-drop from the browser, sharing from your phone, auto-printing from a watched folder, and printing from any macOS or Windows app via a virtual CUPS printer.

## Setup

1. Connect your Zebra printer to your network or via USB to the machine running CUPS
2. Configure the printer in CUPS as a **raw** queue (usually at `http://your-cups-host:631`)
3. Install this addon and set the **Printer Name** to match the CUPS queue name
4. Optionally add an **Anthropic API Key** for smart label extraction from multi-page or cluttered PDFs
5. Set an **API Key** in the addon settings to protect direct access to port 8099 (the sidebar is always accessible without it)

## Usage

### From the sidebar (simplest)

1. Open **Label Printer** from the HA sidebar
2. Select your printer from the dropdown (status dot shows idle/processing/stopped)
3. Optionally adjust the **scale** (50-100%) if labels print too large for the printable area
4. Drag and drop a shipping label PDF or image
5. The label is automatically extracted, converted, and printed
6. A preview of the processed label is shown after printing

### From your phone

There are two ways to print from your phone:

**Option A: Use the sidebar (simple)**

1. Open the HA Companion App on your phone
2. Tap **Label Printer** in the sidebar
3. Tap the drop zone to open the file picker
4. Select a shipping label PDF from your Downloads, email, or files
5. The label prints automatically

**Option B: Share from any app via iOS Shortcut (recommended)**

Set up a one-time iOS Shortcut so you can print labels directly from the
share sheet in Mail, Safari, Files, or any app. The Shortcut sends the file
straight to the addon's API — no HA automation or `rest_command` needed.

1. Open the **Shortcuts** app on your iPhone
2. Create a new shortcut named **"Print Label"**
3. Tap the **(i)** button at the bottom and enable **Show in Share Sheet**
4. Set the share sheet to accept **PDFs** and **Images**
5. Add these actions in order:
   - **Base64 Encode** — input: *Shortcut Input*
   - **URL** — enter: `http://<your-ha-ip>:8099/api/labels/webhook`
   - **Get Contents of URL** — Method: **POST**, Headers: `Content-Type: application/json` and `X-API-Key: <your-api-key>`, Body (JSON):
     | Key | Value |
     |-----|-------|
     | `file_base64` | *(Base64 Encoded variable)* |
     | `filename` | *(Shortcut Input → Name)* |
6. Save the shortcut

**Usage:** From any app, tap **Share** → **Print Label** and the label prints.

> **Note:** This works when your phone is on the same network as Home
> Assistant. For remote printing, use a VPN such as Tailscale or WireGuard.

### Print from any macOS app (virtual CUPS printer)

Set up a virtual printer on a Linux/HA host so macOS (or any CUPS client) can print labels via the standard system print dialog — no browser needed.

**On the server (one-time setup):**

```bash
cd cups/
sudo ./setup-virtual-printer.sh Zebra_LP2844 homeassistant.local:8099 YOUR_API_KEY
```

This installs the `zebrahttp` CUPS backend, creates a shared `ZebraLabel` print queue, and advertises it via Bonjour/mDNS.

**On the Mac:**

The printer appears automatically in **System Settings → Printers & Scanners** (via Bonjour). Add it, and then print from any application — PDFs are sent to the addon, processed, and forwarded to the physical Zebra printer.

If the virtual printer doesn't appear via Bonjour, add it manually:

```bash
lpadmin -p ZebraLabel -E \
  -v "zebrahttp://homeassistant.local:8099/api/labels/print?printer=Zebra_LP2844&api_key=YOUR_KEY" \
  -m raw -D "Zebra Shipping Label Printer" -L "Network"
```

### macOS Quick Action (right-click to print)

Install a Finder Quick Action so you can right-click any PDF or image and print it:

```bash
cd macos/
./install-quick-action.sh http://homeassistant.local:8099
```

Then right-click a file → **Quick Actions** → **Print to Zebra**.

### Auto-print from a shared folder

Set up a watched folder so anyone in the household can print by simply dropping a file:

1. Mount a network share to `/share/shipping_labels` (e.g., via the Samba addon)
2. Add the Folder Watcher integration to your `configuration.yaml`
3. Create an automation that calls the label printer webhook (see `automations.yaml` for examples)
4. Now anyone can drag a PDF into the shared folder and it auto-prints

### From a dashboard

Add a button to any Lovelace dashboard:

```yaml
type: button
name: Print Label
icon: mdi:printer
tap_action:
  action: navigate
  navigation_path: /hassio/ingress/zebra-label-printer
```

Or embed the full UI with the `addon-iframe` card (install from HACS):

```yaml
type: custom:addon-iframe
addon: zebra-label-printer
```

## API

If an **API Key** is set in the addon configuration, direct requests to port
8099 must include it as an `X-API-Key` header or `?api_key=` query parameter.
Requests through the HA sidebar (ingress) are always allowed.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/labels/print` | POST | Upload and print a file (multipart form: `file`, optional `printer`, `scale`) |
| `/api/labels/webhook` | POST | Print from file path or base64 data (JSON body) |
| `/api/printers` | GET | List available CUPS printers with status |
| `/api/health` | GET | Health check (public, no auth required) |
| `/api/debug` | GET | Diagnostic info: settings, CUPS connectivity, printer list |

### Print endpoint

```bash
curl -X POST http://your-ha-ip:8099/api/labels/print \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@label.pdf" \
  -F "printer=Zebra_LP2844" \
  -F "scale=95"
```

Returns HTTP 200 on success, HTTP 502 on print failure (with error details in the JSON body).

### Webhook payload

```json
{
  "file_path": "/share/shipping_labels/label.pdf",
  "printer": "Zebra_ZD420"
}
```

Or with base64 data (useful for iOS Shortcuts and remote clients):

```json
{
  "file_base64": "JVBERi0xLjQ...",
  "filename": "label.pdf",
  "printer": "Zebra_ZD420"
}
```

Returns HTTP 200 on success, HTTP 502 on print failure.

## How It Works

1. **Upload** — User drops a PDF or image in the web UI, sends via API, or prints from any app
2. **Render** — PDFs are rendered to images at 300 DPI via PyMuPDF. Multi-page PDFs are scanned page-by-page to find the shipping label.
3. **Extract** — If an Anthropic API key is configured, Claude Vision identifies the shipping label bounding box and crops it. Without a key, a heuristic fallback crops the upper-left region of letter-size pages (where carriers typically place the label).
4. **Process** — The image is trimmed, auto-rotated (landscape to portrait if needed), resized to 4x6" at 203 DPI, scaled to the chosen percentage, centered on a white canvas, and converted to monochrome with Floyd-Steinberg dithering.
5. **ZPL** — The monochrome bitmap is encoded as ZPL ASCII hex (`^GFA` graphic field) with `^PW`/`^LL` page size commands.
6. **Print** — ZPL is streamed to the Zebra printer via CUPS as a raw IPP job.

## Configuration

All settings are configurable from the HA addon UI. For Docker or local development, use environment variables with the `ZLP_` prefix.

| Setting | Env Variable | Default | Description |
|---------|-------------|---------|-------------|
| API Key | `ZLP_API_KEY` | *(none)* | Protect direct port access (ingress always allowed) |
| Anthropic API Key | `ZLP_ANTHROPIC_API_KEY` | *(none)* | Claude API key for AI label extraction |
| Claude Model | `ZLP_CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Model used for label detection |
| Printer Name | `ZLP_PRINTER_NAME` | *(none)* | Default CUPS printer queue name |
| CUPS Server | `ZLP_CUPS_SERVER` | *(local)* | Remote CUPS server (`host:port`) |
| Label Width | `ZLP_LABEL_WIDTH_INCHES` | `4.0` | Label width in inches |
| Label Height | `ZLP_LABEL_HEIGHT_INCHES` | `6.0` | Label height in inches |
| Label DPI | `ZLP_LABEL_DPI` | `203` | Printer resolution (203 is standard for Zebra) |

## Troubleshooting

### Labels don't print / jobs stuck in "processing"

Check the CUPS error log for details — the `zebrahttp` backend logs server-side errors directly into the CUPS log. Common causes:

- **Wrong printer name** — The `printer` parameter must match a physical CUPS printer on the server, not the virtual `ZebraLabel` queue (which would create a loop).
- **CUPS not reachable** — Check that the CUPS server is running and the addon can reach it. Visit `/api/debug` for connectivity diagnostics.
- **Printer offline** — Run `lpstat -p` on the CUPS host to check printer state.

### Labels print but are cut off or misaligned

- Try reducing the **Scale** to 90% or 85% in the web UI
- Verify your label dimensions match the physical media (4x6" is the default)

### No AI extraction (full page prints)

Without an Anthropic API key, the addon uses a heuristic crop for letter-size pages and prints the full image for other sizes. Add a key for accurate extraction from multi-page or cluttered documents.
