#!/usr/bin/env bash
set -e

# On standard HA base images, bashio is available and reads options.json
# (populated from your add-on's config panel) into shell variables.
if command -v bashio >/dev/null 2>&1; then
    export PRINTER_MODEL="$(bashio::config 'printer_model')"
    export PRINTER_BLUETOOTH="$(bashio::config 'printer_bluetooth')"
else
    export PRINTER_MODEL="${PRINTER_MODEL:-}"
    export PRINTER_BLUETOOTH="${PRINTER_BLUETOOTH:-}"
fi

echo "Starting thermal print bridge (model='${PRINTER_MODEL}', bluetooth='${PRINTER_BLUETOOTH}')"
exec python3 /app/print_server.py
