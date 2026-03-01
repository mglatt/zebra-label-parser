#!/bin/bash
set -e

# Detect Home Assistant addon mode
if [ -f /data/options.json ]; then
    echo "Running as Home Assistant addon"
    export ZLP_HOST="0.0.0.0"
    export ZLP_PORT=8099

    # Export HA addon options as ZLP_ env vars so they are available
    # both to this script (for CUPS daemon decision) and to the Python
    # application (via Pydantic BaseSettings with env_prefix="ZLP_").
    # Uses a heredoc to avoid bash/Python quoting issues.
    HA_ENV=$(python3 <<'PYEOF'
import json, sys

try:
    opts = json.load(open("/data/options.json"))
except Exception:
    sys.exit(0)

mapping = {
    "anthropic_api_key": "ZLP_ANTHROPIC_API_KEY",
    "printer_name": "ZLP_PRINTER_NAME",
    "claude_model": "ZLP_CLAUDE_MODEL",
    "cups_server": "ZLP_CUPS_SERVER",
    "label_width_inches": "ZLP_LABEL_WIDTH_INCHES",
    "label_height_inches": "ZLP_LABEL_HEIGHT_INCHES",
    "label_dpi": "ZLP_LABEL_DPI",
}
for key, env in mapping.items():
    val = opts.get(key, "")
    if val is not None and val != "":
        safe = str(val).replace("'", r"'\''")
        print(f"export {env}='{safe}'")
PYEOF
    ) || true
    eval "$HA_ENV"
fi

echo "Starting Zebra Label Parser on port ${ZLP_PORT:-8099}..."
exec uvicorn app.main:app \
    --host "${ZLP_HOST:-0.0.0.0}" \
    --port "${ZLP_PORT:-8099}" \
    --log-level info
