#!/usr/bin/env bash
set -e

# On standard HA base images, bashio is available and reads options.json
# (populated from your add-on's config panel) into shell variables.
if command -v bashio >/dev/null 2>&1; then
    export PRINTER_MODEL="$(bashio::config 'printer_model')"
    export PRINTER_BLUETOOTH="$(bashio::config 'printer_bluetooth')"
    export DISCORD_ENABLED="$(bashio::config 'discord_enabled')"
    export DISCORD_BOT_TOKEN="$(bashio::config 'discord_bot_token')"
    export DISCORD_CHANNEL_ID="$(bashio::config 'discord_channel_id')"
    export DISCORD_ALLOWED_USER_IDS="$(bashio::config 'discord_allowed_user_ids')"
else
    export PRINTER_MODEL="${PRINTER_MODEL:-}"
    export PRINTER_BLUETOOTH="${PRINTER_BLUETOOTH:-}"
    export DISCORD_ENABLED="${DISCORD_ENABLED:-false}"
    export DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN:-}"
    export DISCORD_CHANNEL_ID="${DISCORD_CHANNEL_ID:-}"
    export DISCORD_ALLOWED_USER_IDS="${DISCORD_ALLOWED_USER_IDS:-}"
fi

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
