# Zebra Label Printer

Print shipping labels from any PDF or image to a Zebra thermal printer.

## Setup

1. Connect your Zebra printer to your network or via USB
2. Configure the printer in CUPS (usually at `http://your-ha-ip:631`)
3. Install this addon and set the printer name in the configuration
4. Optionally add an Anthropic API key for smart label extraction from multi-page or cluttered PDFs

## Usage

### From the sidebar (simplest)

1. Open **Label Printer** from the HA sidebar
2. Select your printer from the dropdown
3. Drag and drop a shipping label PDF or image
4. The label is automatically extracted, converted, and printed

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
share sheet in Mail, Safari, Files, or any app:

1. Open the **Shortcuts** app on your iPhone
2. Create a new shortcut named **"Print Label"**
3. Tap the **(i)** button at the bottom and enable **Show in Share Sheet**
4. Set the share sheet to accept **PDFs** and **Images**
5. Add these actions in order:
   - **Base64 Encode** — input: *Shortcut Input*
   - **URL** — enter: `https://<your-ha-url>/api/webhook/zebra_print_label`
   - **Get Contents of URL** — Method: **POST**, Headers: `Content-Type: application/json`, Body (JSON):
     | Key | Value |
     |-----|-------|
     | `file_base64` | *(Base64 Encoded variable)* |
     | `filename` | *(Shortcut Input → Name)* |
6. Save the shortcut
7. Copy the webhook automation from `automations.yaml` (example #1) and add
   the `rest_command` to your `configuration.yaml`

**Usage:** From any app, tap **Share** → **Print Label** and the label prints.

> **Tip:** Use your Nabu Casa URL (e.g., `https://xxxx.ui.nabu.casa`) so it
> works from anywhere, not just your home Wi-Fi.

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

The addon exposes these endpoints for automations:

- `POST /api/labels/print` — Upload a file (multipart form)
- `POST /api/labels/webhook` — Print from file path or base64 data (JSON body)
- `GET /api/printers` — List available printers
- `GET /api/health` — Health check

### Webhook payload

```json
{
  "file_path": "/share/shipping_labels/label.pdf",
  "printer": "Zebra_ZD420"
}
```

Or with base64 data:

```json
{
  "file_base64": "JVBERi0xLjQ...",
  "filename": "label.pdf",
  "printer": "Zebra_ZD420"
}
```

## How It Works

1. **PDF/Image Upload** - Accepts PDF, PNG, JPG, and other image formats
2. **Label Extraction** - If an API key is configured, Claude Vision identifies and crops just the shipping label from the page
3. **Image Processing** - Resizes to 4x6" at 203 DPI and converts to monochrome
4. **ZPL Generation** - Converts the image to ZPL with Z64 compression
5. **Printing** - Sends the ZPL to your Zebra printer via CUPS
