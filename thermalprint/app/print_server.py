import os
import subprocess
import tempfile
import threading

from flask import Flask, request, jsonify

app = Flask(__name__)

# Bluetooth on these printers only tolerates one active connection at a time.
# This lock makes sure concurrent requests queue instead of colliding.
print_lock = threading.Lock()

TIMINI_CLI = "/app/timini/timiniprint_command_line.py"
PRINTER_MODEL = os.environ.get("PRINTER_MODEL", "").strip()
PRINTER_BLUETOOTH = os.environ.get("PRINTER_BLUETOOTH", "").strip()


def build_cmd(target_path=None, text=None):
    cmd = ["python3", TIMINI_CLI]
    if PRINTER_BLUETOOTH:
        cmd += ["--bluetooth", PRINTER_BLUETOOTH]
    if PRINTER_MODEL:
        cmd += ["--printer-model", PRINTER_MODEL]
    if text is not None:
        cmd += ["--text", text]
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


@app.route("/print/text", methods=["POST"])
def print_text():
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text")
    if not text:
        return jsonify({"error": "missing 'text' field in JSON body"}), 400

    with print_lock:
        ok, output = run_print(build_cmd(text=text))

    if not ok:
        return jsonify({"error": output}), 500
    return jsonify({"status": "ok", "output": output})


@app.route("/print/file", methods=["POST"])
def print_file():
    if "file" not in request.files:
        return jsonify({"error": "missing multipart 'file' upload"}), 400

    f = request.files["file"]
    suffix = os.path.splitext(f.filename or "")[1] or ".png"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    try:
        with print_lock:
            ok, output = run_print(build_cmd(target_path=tmp_path), timeout=90)
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
