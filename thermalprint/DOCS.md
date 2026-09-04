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

Leave both blank to auto-detect the first supported printer found, same as
the TiMini Print CLI's default behavior.

## Endpoints

- `POST /print/text` — JSON body `{"text": "..."}`
- `POST /print/file` — multipart form upload, field name `file` (.png, .jpg,
  .pdf, .txt supported — see TiMini Print's supported formats)
- `GET /health` — basic liveness check

## Example: Home Assistant `rest_command`

```yaml
rest_command:
  print_text:
    url: "http://localhost:8099/print/text"
    method: POST
    content_type: "application/json"
    payload: '{"text": "{{ message }}"}'
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
  parallel.
- The base image in the Dockerfile assumes an Alpine-based HA build image.
  If you change `BUILD_FROM` to a Debian-based one, swap `apk add` for
  `apt-get install` accordingly.
