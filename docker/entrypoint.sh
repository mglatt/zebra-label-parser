#!/bin/bash
set -e

# Detect Home Assistant addon mode
if [ -f /data/options.json ]; then
    echo "Running as Home Assistant addon"
    export ZLP_HOST="0.0.0.0"
    export ZLP_PORT=8099
fi

# Start CUPS if no external CUPS server is configured
if [ -z "$ZLP_CUPS_SERVER" ]; then
    echo "Starting local CUPS daemon..."
    cupsd
    sleep 1
fi

echo "Starting Zebra Label Parser on port ${ZLP_PORT:-8099}..."
exec uvicorn app.main:app \
    --host "${ZLP_HOST:-0.0.0.0}" \
    --port "${ZLP_PORT:-8099}" \
    --log-level info
