import os
import subprocess
import tempfile
import threading

from flask import Flask, request, jsonify, Response

app = Flask(__name__)

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Thermal Print Bridge</title>
<style>
  :root {
    --bg: #0f141a;
    --panel: #1a222b;
    --border: #2a3542;
    --text: #eef2f6;
    --muted: #8492a6;
    --accent-a: #22b6f2;
    --accent-b: #3f51b5;
    --accent-solid: #29a3e0;
    --accent-solid-hover: #47b6ee;
    --ok: #43a047;
    --err: #e5484d;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: Roboto, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    padding: 32px 16px;
  }
  .wrap { width: 100%; max-width: 480px; }

  .header-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 4px;
  }
  .mark {
    width: 26px;
    height: 26px;
    flex-shrink: 0;
  }
  h1 {
    font-size: 19px;
    font-weight: 500;
    margin: 0;
    letter-spacing: -0.01em;
  }
  .sub-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 24px;
  }
  .sub { color: var(--muted); font-size: 13px; }
  .badge {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--muted);
    background: rgba(67,160,71,0.1);
    border: 1px solid rgba(67,160,71,0.25);
    padding: 3px 9px 3px 7px;
    border-radius: 999px;
    white-space: nowrap;
  }
  .badge .dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--ok);
    box-shadow: 0 0 0 0 rgba(67,160,71,0.6);
    animation: pulse 2.4s ease-out infinite;
  }
  @keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(67,160,71,0.5); }
    70%  { box-shadow: 0 0 0 5px rgba(67,160,71,0); }
    100% { box-shadow: 0 0 0 0 rgba(67,160,71,0); }
  }

  .card {
    position: relative;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 22px 20px 20px;
    margin-bottom: 20px;
    overflow: hidden;
  }
  /* Torn-paper edge along the top of each card, a quiet nod to receipt stock. */
  .card::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 8px;
    background:
      linear-gradient(135deg, var(--bg) 50%, transparent 50%),
      linear-gradient(45deg, var(--bg) 50%, transparent 50%);
    background-size: 12px 12px;
    background-position: 0 0, 0 0;
    background-color: var(--panel);
  }
  .card h2 {
    font-size: 13px;
    font-weight: 500;
    margin: 4px 0 14px;
    color: var(--muted);
    letter-spacing: 0.01em;
  }
  textarea, input[type="file"] {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 7px;
    color: var(--text);
    padding: 10px 12px;
    font-size: 14px;
    font-family: inherit;
    resize: vertical;
  }
  textarea:focus, input[type="file"]:focus, input[type="range"]:focus-visible {
    outline: 2px solid var(--accent-solid);
    outline-offset: 1px;
  }
  textarea { min-height: 90px; }
  input[type="file"] { padding: 8px; }

  button {
    margin-top: 14px;
    width: 100%;
    background: linear-gradient(135deg, var(--accent-a), var(--accent-b));
    color: #ffffff;
    border: none;
    border-radius: 7px;
    padding: 11px 16px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: filter 0.15s ease, transform 0.1s ease;
  }
  button:hover { filter: brightness(1.1); }
  button:active { transform: scale(0.99); }
  button:disabled {
    background: var(--border);
    color: var(--muted);
    cursor: not-allowed;
    filter: none;
  }

  .status {
    margin-top: 12px;
    font-size: 13px;
    padding: 8px 10px;
    border-radius: 6px;
    display: none;
  }
  .status.ok { display: block; background: rgba(67,160,71,0.12); color: var(--ok); }
  .status.err { display: block; background: rgba(229,72,77,0.12); color: var(--err); }

  .slider-row { margin-top: 16px; }
  .slider-row label {
    display: flex;
    justify-content: space-between;
    font-size: 13px;
    color: var(--muted);
    margin-bottom: 7px;
  }
  .slider-row label span {
    color: var(--text);
    font-weight: 500;
  }
  input[type="range"] {
    width: 100%;
    height: 4px;
    border-radius: 2px;
    appearance: none;
    background: var(--border);
    cursor: pointer;
  }
  input[type="range"]::-webkit-slider-thumb {
    appearance: none;
    width: 15px;
    height: 15px;
    border-radius: 50%;
    background: var(--accent-solid);
    border: 2px solid var(--panel);
    box-shadow: 0 0 0 1px var(--accent-solid);
    cursor: pointer;
  }
  input[type="range"]::-moz-range-thumb {
    width: 15px;
    height: 15px;
    border: 2px solid var(--panel);
    border-radius: 50%;
    background: var(--accent-solid);
    box-shadow: 0 0 0 1px var(--accent-solid);
    cursor: pointer;
  }

  @media (prefers-reduced-motion: reduce) {
    .badge .dot { animation: none; }
  }
</style>
</head>
<body>
<div class="wrap">
  <div class="header-row">
    <svg class="mark" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="markGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="var(--accent-a)"/>
          <stop offset="100%" stop-color="var(--accent-b)"/>
        </linearGradient>
      </defs>
      <path d="M12 2 L22 10.5 V21 a1 1 0 0 1 -1 1 H15 v-7 H9 v7 H3 a1 1 0 0 1 -1 -1 V10.5 Z" fill="url(#markGrad)"/>
    </svg>
    <h1>Thermal Print Bridge</h1>
  </div>
  <div class="sub-row">
    <div class="sub">Send text or images to your Bluetooth thermal printer.</div>
    <div class="badge"><span class="dot"></span>Ready</div>
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

# Bluetooth on these printers only tolerates one active connection at a time.
# This lock makes sure concurrent requests queue instead of colliding.
print_lock = threading.Lock()

TIMINI_CLI = "/app/timini/timiniprint_command_line.py"
# Monospace bold TrueType font bundled with this add-on. Upstream TiMini Print
# scales the rendered text by binary-searching the largest font size that fits
# the requested text_columns within the paper width, but ONLY if a real TTF is
# provided. The stripped-down Alpine base image ships no fonts and no fc-match,
# so without pinning --text-font to this bundled file the "Font size" slider
# would silently have no effect (Pillow would fall back to its fixed-size
# bitmap font). See print/text flow and Dockerfile.
TEXT_FONT = "/app/DejaVuSansMono-Bold.ttf"
PRINTER_MODEL = os.environ.get("PRINTER_MODEL", "").strip()
PRINTER_BLUETOOTH = os.environ.get("PRINTER_BLUETOOTH", "").strip()


def build_cmd(target_path=None, text=None, darkness=None, text_columns=None):
    cmd = ["python3", TIMINI_CLI]
    if PRINTER_BLUETOOTH:
        cmd += ["--bluetooth", PRINTER_BLUETOOTH]
    if PRINTER_MODEL:
        cmd += ["--printer-model", PRINTER_MODEL]
    if darkness is not None:
        cmd += ["--darkness", str(darkness)]
    if text is not None:
        cmd += ["--text", text]
        # Pin a real TrueType font so upstream's column->font-size scaling works
        # in the font-shipless Alpine container (see TEXT_FONT above).
        cmd += ["--text-font", TEXT_FONT]
        if text_columns is not None:
            cmd += ["--text-columns", str(text_columns)]
    elif target_path is not None:
        cmd += [target_path]
    return cmd


def run_print(cmd, timeout=60):
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, "Print job timed out (Bluetooth connection may have hung)."

    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip() or "Unknown error"
    return True, result.stdout.strip()


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

    with print_lock:
        ok, output = run_print(
            build_cmd(text=text, darkness=darkness, text_columns=text_columns)
        )

    if not ok:
        return jsonify({"error": output}), 500
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
        with print_lock:
            ok, output = run_print(
                build_cmd(target_path=tmp_path, darkness=darkness), timeout=90
            )
    finally:
        os.unlink(tmp_path)

    if not ok:
        return jsonify({"error": output}), 500
    return jsonify({"status": "ok", "output": output})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "up"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099)
