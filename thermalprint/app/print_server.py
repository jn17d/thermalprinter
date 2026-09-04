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
</style>
</head>
<body>
<div class="wrap">
  <h1><span class="dot"></span> Thermal Print Bridge</h1>
  <div class="sub">Send text or images straight to your Bluetooth thermal printer.</div>

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
