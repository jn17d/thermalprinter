#!/usr/bin/env bash
set -e

# bashio::config was unreliable in this environment (silently returned
# "command not found" while still hitting the success branch), so options
# are read directly from /data/options.json with Python instead.
read_opt() {
    python3 - "$1" <<'PYEOF'
import json, sys
key = sys.argv[1]
try:
    with open("/data/options.json") as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
value = data.get(key)
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(value)
PYEOF
}

export PRINTER_MODEL="$(read_opt printer_model)"
export PRINTER_BLUETOOTH="$(read_opt printer_bluetooth)"
export DISCORD_ENABLED="$(read_opt discord_enabled)"
export DISCORD_BOT_TOKEN="$(read_opt discord_bot_token)"
export DISCORD_CHANNEL_ID="$(read_opt discord_channel_id)"
export DISCORD_ALLOWED_USER_IDS="$(read_opt discord_allowed_user_ids)"

echo "Starting thermal print bridge (model='${PRINTER_MODEL}', bluetooth='${PRINTER_BLUETOOTH}')"

if [ "$DISCORD_ENABLED" = "true" ]; then
    if [ -z "$DISCORD_BOT_TOKEN" ] || [ -z "$DISCORD_CHANNEL_ID" ]; then
        echo "discord_enabled is true but discord_bot_token or discord_channel_id is missing; skipping Discord bot."
    else
        echo "Starting Discord bot (channel=${DISCORD_CHANNEL_ID})"
        python3 /app/discord_bot.py &
    fi
fi

exec python3 /app/print_server.py
