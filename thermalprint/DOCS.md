# Thermal Print Bridge

An HTTP wrapper around [TiMini Print](https://github.com/Dejniel/TiMini-Print) for
cheap Chinese Bluetooth thermal printers (Tiny Print / Fun Print / cat printer
family, etc.), packaged as a Home Assistant add-on.

## Before installing

1. Pass your Bluetooth USB dongle through to the HAOS VM in Proxmox
   (Hardware -> Add -> USB Device -> Use USB Vendor/Device ID), the same way
   you did for your Zigbee dongle.
2. Confirm HAOS sees it: Settings -> System -> Hardware, or `lsusb` over SSH.

## Configuration options

- `printer_model`: force a specific TiMini Print model key (see
  `--list-models` in the upstream project) if auto-detection picks the wrong
  device or your printer's Bluetooth name isn't recognized.
- `printer_bluetooth`: pin to a specific Bluetooth name or MAC address if you
  have more than one supported printer nearby.
- `discord_enabled`: turn on the Discord bot (off by default). No inbound
  ports are opened for this — the bot only makes an outbound connection to
  Discord's gateway.
- `discord_bot_token`: your bot's token from the Discord Developer Portal.
  Stored as a masked/password field.
- `discord_channel_id`: the ID of the one channel the bot watches. Right-click
  a channel with Developer Mode on to copy it.
- `discord_allowed_user_ids`: optional comma-separated list of Discord user
  IDs allowed to trigger prints. Leave blank to allow anyone who can post in
  the configured channel.

Leave `printer_model`/`printer_bluetooth` blank to auto-detect the first
supported printer found, same as the TiMini Print CLI's default behavior.

## Discord bot

When enabled, the bot watches one channel:

- An image or PDF attachment is forwarded to `/print/file` as-is.
- A plain text message (no attachment) is forwarded to `/print/text` using
  fixed defaults: darkness 3/5 ("normal") and 32 text columns ("medium" font
  size) — the same defaults as the middle position of each slider in the web
  UI. These aren't currently configurable per-message; edit
  `DEFAULT_DARKNESS`/`DEFAULT_TEXT_COLUMNS` in `app/discord_bot.py` if you
  want different fixed values.
- The bot reacts with 🖨️ on success or ⚠️ on failure so you get feedback
  without checking logs.
- Font size (`text_columns`) has no effect on image/PDF attachments — TiMini
  Print rasterizes those as-is, so only the darkness default applies to them.

## Endpoints

- `POST /print/text` — JSON body `{"text": "..."}`
- `POST /print/file` — multipart form upload, field name `file` (.png, .jpg,
  .pdf, .txt supported — see TiMini Print's supported formats)
- `GET /health` — basic liveness check

- `POST /print/text` also accepts `darkness` (1-5) and `text_columns` (8-80,
  fewer = larger glyphs). The web UI's "Font size" slider posts `text_columns`.
  A bundled `DejaVuSansMono-Bold.ttf` is pinned via `--text-font` so upstream
  TiMini Print can scale the text (it needs a real TTF; the Alpine base image
  ships no fonts, which is why the slider previously had no effect).

## Example: Home Assistant `rest_command`

```yaml
rest_command:
  print_text:
    url: "http://localhost:8099/print/text"
    method: POST
    content_type: "application/json"
    payload: '{"message": "{{ message }}"}'
```

Call it from any automation with `service: rest_command.print_text` and a
`message` field.

## Known caveats

- `host_dbus: true` and `host_network: true` are both set in config.yaml.
  Bluetooth's raw connection layer (used for the actual print job, not just
  discovery) has been unreliable in more isolated container setups without
  full host networking — if prints fail with a "Bluetooth connection failed"
  / "Address family not supported" error, this is very likely a network
  namespace issue rather than a bug in this add-on.
- Only one print job can run at a time (BLE connections don't multiplex
  well); concurrent requests queue via a simple lock rather than running in
  parallel. This applies to Discord-triggered prints too — they share the
  same lock as the web UI.
- The base image in the Dockerfile assumes an Alpine-based HA build image.
  If you change `BUILD_FROM` to a Debian-based one, swap `apk add` for
  `apt-get install` accordingly.
- If `discord_enabled` is true but the token or channel ID is missing, the
  add-on logs a warning and skips starting the bot rather than crashing the
  whole add-on.
