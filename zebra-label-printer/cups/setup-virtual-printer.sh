#!/bin/bash
# setup-virtual-printer.sh — Set up the Zebra Label Printer as a shared
# network printer discoverable via Bonjour.
#
# Run on the server (the machine running the Zebra Label Parser service).
# Requires root privileges.
#
# Usage:
#   sudo ./setup-virtual-printer.sh [PRINTER_NAME] [API_PORT]
#
# Examples:
#   sudo ./setup-virtual-printer.sh                     # defaults: Zebra_LP2844, 8099
#   sudo ./setup-virtual-printer.sh MyZebra 8099

set -euo pipefail

PRINTER_NAME="${1:-Zebra_LP2844}"
API_PORT="${2:-8099}"
HASS_IP="${3:-localhost}"
QUEUE_NAME="ZebraLabel"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Zebra Label Virtual Printer Setup ==="
echo "  Printer name:         ${PRINTER_NAME}"
echo "  API port:             ${API_PORT}"
echo "  Home Assistant IP:    ${HASS_IP}"
echo "  CUPS queue:           ${QUEUE_NAME}"
echo ""

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo "Error: This script must be run as root (sudo)."
    exit 1
fi

# Detect backend directory
if [ -d /usr/lib/cups/backend ]; then
    BACKEND_DIR="/usr/lib/cups/backend"
elif [ -d /usr/libexec/cups/backend ]; then
    BACKEND_DIR="/usr/libexec/cups/backend"
else
    echo "Error: Cannot find CUPS backend directory."
    exit 1
fi

# Step 1: Install CUPS backend
echo "[1/4] Installing CUPS backend..."
cp "${SCRIPT_DIR}/zebrahttp" "${BACKEND_DIR}/zebrahttp"
chown root:root "${BACKEND_DIR}/zebrahttp"
chmod 0755 "${BACKEND_DIR}/zebrahttp"
echo "  Installed: ${BACKEND_DIR}/zebrahttp"

# Step 2: Create CUPS print queue
echo "[2/4] Creating CUPS print queue '${QUEUE_NAME}'..."
DEVICE_URI="zebrahttp://${HASS_IP}:${API_PORT}/api/labels/print?printer=${PRINTER_NAME}"
lpadmin -p "${QUEUE_NAME}" \
    -E \
    -v "${DEVICE_URI}" \
    -m raw \
    -D "Zebra Shipping Label Printer" \
    -L "Network" \
    -o printer-is-shared=true
echo "  Device URI: ${DEVICE_URI}"

# Step 3: Enable printer sharing
echo "[3/4] Enabling CUPS printer sharing..."
cupsctl --share-printers 2>/dev/null || true

# Step 4: Install Avahi service for Bonjour discovery
echo "[4/4] Installing Avahi/Bonjour service..."
if [ -d /etc/avahi/services ]; then
    cp "${SCRIPT_DIR}/zebra-label-printer.service" /etc/avahi/services/
    # Restart Avahi if running
    if systemctl is-active --quiet avahi-daemon 2>/dev/null; then
        systemctl restart avahi-daemon
        echo "  Avahi daemon restarted"
    fi
    echo "  Installed: /etc/avahi/services/zebra-label-printer.service"
else
    echo "  Warning: /etc/avahi/services not found. Bonjour discovery requires avahi-daemon."
    echo "  Install with: apt-get install avahi-daemon"
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "The printer '${QUEUE_NAME}' is now shared on the network."
echo ""
echo "On each Mac:"
echo "  1. Open System Settings > Printers & Scanners"
echo "  2. Click '+' to add a printer"
echo "  3. 'Zebra Label Printer' should appear under Bonjour printers"
echo "  4. Select it and click Add"
echo "  5. Now Cmd+P in any app will show it as a printer option"
echo ""
echo "To remove:"
echo "  sudo lpadmin -x ${QUEUE_NAME}"
echo "  sudo rm ${BACKEND_DIR}/zebrahttp"
echo "  sudo rm /etc/avahi/services/zebra-label-printer.service"
