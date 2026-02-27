# Zebra Label Printer

Print shipping labels from any PDF or image to a Zebra thermal printer.

## Setup

1. Connect your Zebra printer to your network or via USB
2. Configure the printer in CUPS (usually at `http://your-ha-ip:631`)
3. Install this addon and set the printer name in the configuration
4. Optionally add an Anthropic API key for smart label extraction from multi-page or cluttered PDFs

## Usage

1. Open the addon from the sidebar (Label Printer)
2. Select your printer from the dropdown
3. Drag and drop a shipping label PDF or image
4. The label is automatically extracted, converted, and printed

## How It Works

1. **PDF/Image Upload** - Accepts PDF, PNG, JPG, and other image formats
2. **Label Extraction** - If an API key is configured, Claude Vision identifies and crops just the shipping label from the page
3. **Image Processing** - Resizes to 4x6" at 203 DPI and converts to monochrome
4. **ZPL Generation** - Converts the image to ZPL with Z64 compression
5. **Printing** - Sends the ZPL to your Zebra printer via CUPS
