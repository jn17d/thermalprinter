import atexit
import logging
import os
import tempfile

from flask import Flask, request, jsonify, Response

from printer_manager import (
    PrinterManager,
    PrinterReleasedError,
    PrinterUnavailableError,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("print_server")

app = Flask(__name__)
manager = PrinterManager()

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Thermal Print Bridge</title>
<style>
  :root {
    --bg: #16181d;
    --panel: #1f2229;
    --border: #2c303a;
    --text: #e8eaed;
    --muted: #9aa0ac;
    --accent: #ff7a45;
    --accent-hover: #ff8f63;
    --ok: #4caf7d;
    --err: #e5484d;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    padding: 32px 16px;
  }
  .wrap { width: 100%; max-width: 480px; }
  h1 {
    font-size: 20px;
    font-weight: 600;
    margin: 0 0 4px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
  }
  .card h2 {
    font-size: 14px;
    font-weight: 600;
    margin: 0 0 12px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  textarea, input[type="file"] {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 10px 12px;
    font-size: 14px;
    font-family: inherit;
    resize: vertical;
  }
  textarea { min-height: 90px; }
  input[type="file"] { padding: 8px; }
  button {
    margin-top: 12px;
    width: 100%;
    background: var(--accent);
    color: #1a1a1a;
    border: none;
    border-radius: 8px;
    padding: 11px 16px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s ease;
  }
  button:hover { background: var(--accent-hover); }
  button:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; }
  .status {
    margin-top: 12px;
    font-size: 13px;
    padding: 8px 10px;
    border-radius: 6px;
    display: none;
  }
  .status.ok { display: block; background: rgba(76,175,125,0.12); color: var(--ok); }
  .status.err { display: block; background: rgba(229,72,77,0.12); color: var(--err); }
  .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--ok); display: inline-block;
  }
  .slider-row {
    margin-top: 14px;
  }
  .slider-row label {
    display: flex;
    justify-content: space-between;
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 6px;
  }
  .slider-row label span {
    color: var(--text);
    font-weight: 600;
  }
  input[type="range"] {
    width: 100%;
    accent-color: var(--accent);
    height: 4px;
    cursor: pointer;
  }
  .printer-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .printer-meta { flex: 1; min-width: 0; }
  .printer-state { font-size: 15px; font-weight: 600; color: var(--text); }
  .printer-sub { font-size: 12px; color: var(--muted); margin-top: 2px; word-break: break-word; }
  .dot.idle { background: var(--muted); }
  .dot.busy { background: #f0b429; animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
  .btn-secondary {
    background: transparent;
    color: var(--text);
    border: 1px solid var(--border);
  }
  .btn-secondary:hover { background: var(--border); }
</style>
</head>
<body>
<div class="wrap">
  <h1><span class="dot"></span> Thermal Print Bridge</h1>
  <div class="sub">Send text or images straight to your Bluetooth thermal printer.</div>

  <div class="card">
    <h2>Printer</h2>
    <div class="printer-row">
      <span class="dot idle" id="printerDot"></span>
      <div class="printer-meta">
        <div class="printer-state" id="printerState">Checking...</div>
        <div class="printer-sub" id="printerDetail"></div>
      </div>
    </div>
    <button type="button" id="printerToggle" class="btn-secondary" disabled>...</button>
    <div class="status" id="printerStatus"></div>
  </div>

  <div class="card">
    <h2>Print text</h2>
    <form id="textForm">
      <textarea id="textInput" placeholder="Type something to print..."></textarea>

      <div class="slider-row">
        <label for="darknessInput">Darkness <span id="darknessVal">3</span></label>
        <input type="range" id="darknessInput" min="1" max="5" step="1" value="3">
      </div>

      <div class="slider-row">
        <label for="fontSizeInput">Font size <span id="fontSizeVal">Medium</span></label>
        <input type="range" id="fontSizeInput" min="0" max="4" step="1" value="2">
      </div>

      <button type="submit" id="textBtn">Print text</button>
    </form>
    <div class="status" id="textStatus"></div>
  </div>

  <div class="card">
    <h2>Print image / PDF</h2>
    <form id="fileForm">
      <input type="file" id="fileInput" accept=".png,.jpg,.jpeg,.gif,.bmp,.pdf,.txt">

      <div class="slider-row">
        <label for="fileDarknessInput">Darkness <span id="fileDarknessVal">3</span></label>
        <input type="range" id="fileDarknessInput" min="1" max="5" step="1" value="3">
      </div>

      <button type="submit" id="fileBtn">Print file</button>
    </form>
    <div class="status" id="fileStatus"></div>
  </div>
</div>

<script>
let printerReleased = false;

const PRINTER_STATE_META = {
  connected:    { cls: "ok",   label: "Connected" },
  connecting:   { cls: "busy", label: "Connecting..." },
  reconnecting: { cls: "busy", label: "Reconnecting..." },
  released:     { cls: "idle", label: "Handed off to phone" },
  unknown:      { cls: "idle", label: "Unknown" }
};

function renderPrinter(data) {
  const meta = PRINTER_STATE_META[data.state] || PRINTER_STATE_META.unknown;
  const dot = document.getElementById("printerDot");
  dot.className = "dot " + meta.cls;

  document.getElementById("printerState").textContent = meta.label;

  const parts = [];
  if (data.model) parts.push(data.model);
  if (data.address) parts.push(data.address);
  if (data.detail) parts.push(data.detail);
  document.getElementById("printerDetail").textContent = parts.join(" - ");

  const status = document.getElementById("printerStatus");
  status.className = "status";
  status.textContent = "";

  const btn = document.getElementById("printerToggle");
  btn.disabled = false;
  btn.textContent = data.released ? "Take back over" : "Hand off to phone";
}

async function refreshPrinterStatus() {
  try {
    const res = await fetch("printer/status");
    const data = await res.json();
    printerReleased = !!data.released;
    renderPrinter(data);
  } catch (err) {
    printerReleased = false;
    renderPrinter({ state: "unknown", detail: "Status unavailable: " + err.message });
  }
}

document.getElementById("printerToggle").addEventListener("click", async () => {
  const btn = document.getElementById("printerToggle");
  const status = document.getElementById("printerStatus");
  btn.disabled = true;
  try {
    const res = await fetch("printer/connection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ connected: printerReleased })
    });
    const data = await res.json();
    if (res.ok) {
      printerReleased = !!data.released;
      renderPrinter(data);
    } else {
      status.className = "status err";
      status.textContent = "Error: " + (data.error || "request failed");
      btn.disabled = false;
    }
  } catch (err) {
    status.className = "status err";
    status.textContent = "Request failed: " + err.message;
    btn.disabled = false;
  }
});

refreshPrinterStatus();
setInterval(refreshPrinterStatus, 3000);

function setStatus(el, ok, message) {
  el.textContent = message;
  el.className = "status " + (ok ? "ok" : "err");
}

// Font-size slider: position -> [text-columns value, display label].
// Fewer columns means the same paper width is divided among fewer
// characters, so each character renders larger.
const FONT_STEPS = [
  { columns: 48, label: "Tiny" },
  { columns: 40, label: "Small" },
  { columns: 32, label: "Medium" },
  { columns: 24, label: "Large" },
  { columns: 16, label: "Extra Large" }
];

const darknessInput = document.getElementById("darknessInput");
const darknessVal = document.getElementById("darknessVal");
darknessInput.addEventListener("input", () => {
  darknessVal.textContent = darknessInput.value;
});

const fontSizeInput = document.getElementById("fontSizeInput");
const fontSizeVal = document.getElementById("fontSizeVal");
fontSizeInput.addEventListener("input", () => {
  fontSizeVal.textContent = FONT_STEPS[fontSizeInput.value].label;
});

const fileDarknessInput = document.getElementById("fileDarknessInput");
const fileDarknessVal = document.getElementById("fileDarknessVal");
fileDarknessInput.addEventListener("input", () => {
  fileDarknessVal.textContent = fileDarknessInput.value;
});

document.getElementById("textForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("textBtn");
  const status = document.getElementById("textStatus");
  const text = document.getElementById("textInput").value.trim();
  if (!text) return;

  const darkness = parseInt(darknessInput.value, 10);
  const textColumns = FONT_STEPS[fontSizeInput.value].columns;

  btn.disabled = true;
  btn.textContent = "Printing...";
  try {
    const res = await fetch("print/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, darkness, text_columns: textColumns })
    });
    const data = await res.json();
    if (res.ok) {
      setStatus(status, true, "Printed successfully.");
      document.getElementById("textInput").value = "";
    } else {
      setStatus(status, false, "Error: " + (data.error || "unknown error"));
    }
  } catch (err) {
    setStatus(status, false, "Request failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Print text";
  }
});

document.getElementById("fileForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("fileBtn");
  const status = document.getElementById("fileStatus");
  const fileInput = document.getElementById("fileInput");
  if (!fileInput.files.length) return;

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("darkness", fileDarknessInput.value);

  btn.disabled = true;
  btn.textContent = "Printing...";
  try {
    const res = await fetch("print/file", { method: "POST", body: formData });
    const data = await res.json();
    if (res.ok) {
      setStatus(status, true, "Printed successfully.");
      fileInput.value = "";
    } else {
      setStatus(status, false, "Error: " + (data.error || "unknown error"));
    }
  } catch (err) {
    setStatus(status, false, "Request failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Print file";
  }
});
</script>
</body>
</html>
"""

# --- Connection management ------------------------------------------------
#
# The bridge keeps one TiMini-Print connection open for as long as it runs, so
# the printer never idles into its ~1 hour auto power-off (the firmware counts
# *disconnected* time). The PrinterManager owns that connection: it reconnects
# with a backoff when the link drops, and it supports handing the printer off
# to a phone app (POST /printer/connection + the web UI toggle). See
# printer_manager.py.
#
# PRINTER_MODEL / PRINTER_BLUETOOTH (set by run.sh from the add-on options)
# are read inside the manager's device-resolution step.


@app.route("/", methods=["GET"])
def index():
    return Response(INDEX_HTML, mimetype="text/html")


def parse_darkness(value):
    try:
        d = int(value)
    except (TypeError, ValueError):
        return None
    return d if 1 <= d <= 5 else None


def parse_text_columns(value):
    try:
        c = int(value)
    except (TypeError, ValueError):
        return None
    return c if 8 <= c <= 80 else None


@app.route("/print/text", methods=["POST"])
def print_text():
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text")
    if not text:
        return jsonify({"error": "missing 'text' field in JSON body"}), 400

    darkness = parse_darkness(data.get("darkness"))
    text_columns = parse_text_columns(data.get("text_columns"))

    try:
        output = manager.print_text(text, darkness=darkness, text_columns=text_columns)
    except PrinterReleasedError as exc:
        return jsonify({"error": str(exc)}), 503
    except PrinterUnavailableError as exc:
        return jsonify({"error": str(exc)}), 502
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        log.exception("print/text failed")
        return jsonify({"error": f"Print failed: {exc}"}), 500
    return jsonify({"status": "ok", "output": output})


@app.route("/print/file", methods=["POST"])
def print_file():
    if "file" not in request.files:
        return jsonify({"error": "missing multipart 'file' upload"}), 400

    f = request.files["file"]
    suffix = os.path.splitext(f.filename or "")[1] or ".png"
    darkness = parse_darkness(request.form.get("darkness"))

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    try:
        output = manager.print_file(tmp_path, darkness=darkness)
    except PrinterReleasedError as exc:
        return jsonify({"error": str(exc)}), 503
    except PrinterUnavailableError as exc:
        return jsonify({"error": str(exc)}), 502
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        log.exception("print/file failed")
        return jsonify({"error": f"Print failed: {exc}"}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return jsonify({"status": "ok", "output": output})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "up"})


@app.route("/printer/status", methods=["GET"])
def printer_status():
    try:
        return jsonify(manager.status())
    except Exception as exc:  # noqa: BLE001
        log.exception("printer/status failed")
        return (
            jsonify(
                {
                    "state": "unknown",
                    "released": False,
                    "model": "",
                    "detail": str(exc),
                }
            ),
            500,
        )


@app.route("/printer/connection", methods=["POST"])
def printer_connection():
    data = request.get_json(force=True, silent=True) or {}
    connected = data.get("connected")
    if not isinstance(connected, bool):
        return jsonify({"error": "'connected' must be true or false"}), 400
    try:
        manager.set_released(not connected)
    except Exception as exc:  # noqa: BLE001
        log.exception("printer/connection failed")
        return jsonify({"error": str(exc)}), 500
    try:
        return jsonify(manager.status())
    except Exception:  # noqa: BLE001
        return jsonify({"state": "unknown", "released": not connected, "model": "", "detail": "state changed"})


if __name__ == "__main__":
    manager.start()
    atexit.register(manager.close)
    app.run(host="0.0.0.0", port=8099, threaded=True)
