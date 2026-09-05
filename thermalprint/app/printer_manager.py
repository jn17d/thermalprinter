"""Persistent printer connection manager for the Thermal Print Bridge.

Cheap Chinese Bluetooth thermal printers (the TiMini family) auto power off
after roughly an hour without a *connection*, and they count disconnected time.
The old bridge connected, printed, and disconnected per job, so the printer
spent its whole life disconnected and kept turning itself off.

This manager keeps one TiMini-Print ``ConnectedPrinter`` open for as long as
the bridge runs. On top of the open link, a periodic keep-alive runs
``feed()`` + ``retract()`` (a net-zero paper wiggle) every 30 minutes, because
some printers count idle *activity*, not connection time, when deciding to
power off.

It also supports deliberately *releasing* the printer so a phone app can use it:

  - ``released`` (aka "handed off to phone"): the bridge drops the link and
    stops trying to reconnect. Prints fail fast with a clear message. The
    phone app can connect normally.
  - reclaiming: the bridge starts connecting again immediately. If the phone
    still holds the printer, connect attempts fail and the bridge retries with
    an exponential backoff until the printer is free.

The connection is owned by a background asyncio event-loop thread. Flask (sync)
submits coroutines to that loop with ``asyncio.run_coroutine_threadsafe``.

Set ``TIMINI_FAKE_PRINTER=1`` for a dry-run mode that fakes the printer, so the
web UI (and this module) can be exercised without any Bluetooth hardware.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

log = logging.getLogger("printer_manager")

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# Reconnect pacing: start by retrying quickly, then back off to at most a
# minute between attempts. Anything faster would hammer Bluetooth scanning
# while the printer is genuinely unreachable (off, or taken over by a phone).
BACKOFF_START_SECONDS = 5
BACKOFF_MAX_SECONDS = 60

# How long a print request is willing to wait for a connect/reconnect attempt
# to succeed before giving up and reporting the printer as unavailable.
ENSURE_CONNECTED_WAIT_SECONDS = 45

# Per-operation timeout passed to TiMini Print's session/send machinery
# (control packet round-trips, completion wait after the last write, ...).
PRINT_OP_TIMEOUT_SECONDS = 30

# How long a synchronous Flask call is willing to block on the loop thread.
# Generous: PDF rasterization + BLE send can be slow.
PRINT_WAIT_SECONDS = 180

# Add-on state lives under /data in Home Assistant. The hand-off toggle is
# persisted here so a restart doesn't rip the printer away from a phone.
CONTROL_STATE_PATH = os.environ.get("TIMINI_CONTROL_STATE", "/data/printer_control.json")

# Monospace bold font bundled with this add-on. TiMini Print only scales the
# rendered text when given a real TTF; the Alpine base image ships no fonts.
TEXT_FONT = os.environ.get("TIMINI_TEXT_FONT", "/app/DejaVuSansMono-Bold.ttf")

# Directory where the TiMini-Print CLI/package was cloned by the Dockerfile.
TIMINI_SOURCE = os.environ.get("TIMINI_SOURCE", "/app/timini")

# Dry-run mode: no Bluetooth, no TiMini-Print import, printer is faked.
TIMINI_FAKE = os.environ.get("TIMINI_FAKE_PRINTER", "") == "1"

# The open BLE link alone is not enough to stop some printers powering off
# after ~1 hour of inactivity: their idle timer counts printer *activity*
# (motor/protocol traffic), not just connection time. Periodically feed the
# paper forward a few dots and retract it back so the printer sees activity.
# 30 minutes is comfortably under the ~1 hour idle timeout.
KEEPALIVE_INTERVAL_SECONDS = float(
    os.environ.get("TIMINI_KEEPALIVE_INTERVAL", "") or 1800
)

DISABLED = "released"
CONNECTING = "connecting"
CONNECTED = "connected"
RECONNECTING = "reconnecting"

_RELEASED_DETAIL = "Handed off to the phone app. Tap 'Take back over' to reclaim the printer."
class PrinterReleasedError(RuntimeError):
    """Printing was attempted while the printer is handed off to the phone."""


class PrinterUnavailableError(RuntimeError):
    """The printer could not be connected to right now."""


class _LogSink:
    """Route TiMini Print's ``reporting.Reporter`` calls into python logging."""

    _LEVELS = {
        "debug": logging.DEBUG,
        "status": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }

    def emit(self, message) -> None:
        level = self._LEVELS.get(getattr(message, "level", ""), logging.INFO)
        text = getattr(message, "detail", None) or getattr(message, "short", None)
        if text:
            log.log(level, "%s", text)


class FakeConnectedPrinter:
    """Stand-in for a real ``ConnectedPrinter`` when ``TIMINI_FAKE_PRINTER=1``.

    Only useful for exercising the bridge logic and the web UI without
    hardware. The real object is ``timiniprint.printing.connected.ConnectedPrinter``.
    """

    def __init__(self, name: str = "Fake Printer (dry-run)") -> None:
        self._device = SimpleNamespace(
            display_name=name,
            address="00:00:00:00:00:00",
        )

    def printer_device(self) -> SimpleNamespace:
        return self._device

    async def print_text(self, text, *, settings=None, timeout: float = 30.0) -> None:
        log.info("FAKE print_text: %r", (text[:80] + "...") if len(text) > 80 else text)
        await asyncio.sleep(0.1)

    async def print_file(self, path, *, settings=None, timeout: float = 30.0) -> None:
        log.info("FAKE print_file: %s", path)
        await asyncio.sleep(0.1)

    async def feed(self, *, timeout: float = 1.0) -> None:
        log.info("FAKE feed")

    async def retract(self, *, timeout: float = 1.0) -> None:
        log.info("FAKE retract")

    async def disconnect(self) -> None:
        log.info("FAKE disconnect")
class PrinterManager:
    """Owns the persistent printer connection and the phone hand-off toggle."""

    def __init__(self, control_state_path: str = CONTROL_STATE_PATH) -> None:
        self._path = Path(control_state_path)
        self._loop = asyncio.new_event_loop()

        # asyncio primitives are created inside the loop thread (see
        # _boot_in_loop) so they bind to the loop that actually runs them.
        self._wake: asyncio.Event | None = None
        self._conn_lock: asyncio.Lock | None = None
        self._print_lock: asyncio.Lock | None = None

        self._connected = None  # ConnectedPrinter | FakeConnectedPrinter | None
        self._device = None  # cached resolved PrinterDevice (real mode only)
        self._reporter = None  # lazily-built TiMini reporting.Reporter
        self._released = False
        self._state = CONNECTING
        self._detail = "Starting up..."
        self._backoff = BACKOFF_START_SECONDS
        self._closed = False
        self._thread = None
        self._maintain_task = None
        self._keepalive_task = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background event-loop thread and begin maintaining the link."""
        started = threading.Event()

        def _boot() -> None:
            asyncio.set_event_loop(self._loop)
            asyncio.run_coroutine_threadsafe(self._boot_in_loop(started), self._loop)
            try:
                self._loop.run_forever()
            finally:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                self._loop.close()

        self._thread = threading.Thread(
            target=_boot, name="printer-connection-loop", daemon=True
        )
        self._thread.start()
        if not started.wait(timeout=10):
            raise RuntimeError("printer connection loop failed to start")

    async def _boot_in_loop(self, started: threading.Event) -> None:
        self._wake = asyncio.Event()
        self._conn_lock = asyncio.Lock()
        self._print_lock = asyncio.Lock()

        self._load_state()
        if self._released:
            self._state = DISABLED
            self._detail = _RELEASED_DETAIL
        self._maintain_task = asyncio.create_task(self._maintain())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        started.set()
    async def _maintain(self) -> None:
        """Background loop: keep the printer connected unless released.

        Waits quietly while connected or handed off. When a connection is
        needed (startup, drop, reclaim) it attempts to connect, and on failure
        retries with an exponential backoff. A print request sets ``wake`` to
        interrupt the backoff sleep so the next attempt happens immediately.
        """
        while not self._closed:
            if self._released or self._connected is not None:
                await self._wake.wait()
                self._wake.clear()
                continue

            try:
                ok = await self._attempt_connect()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never let the loop die
                log.exception("Unexpected error during connect attempt")
                ok = False

            if ok:
                continue

            self._state = RECONNECTING
            log.warning("Printer not reachable: %s", self._detail or "unknown error")
            self._backoff = min(self._backoff * 2, BACKOFF_MAX_SECONDS)
            # Sleep up to the backoff delay, but wake early if a print request
            # (or a reclaim) needs an immediate attempt.
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._backoff)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _keepalive_loop(self) -> None:
        """Periodically nudge the printer so it never counts an idle hour.

        Runs ``feed()`` + ``retract()`` (a net-zero paper wiggle) while the
        printer is connected. Skips itself while released or mid-print, and on
        any failure drops the link so ``_maintain`` reconnects.
        """
        while not self._closed:
            try:
                await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise

            if self._closed or self._released or self._connected is None:
                continue
            # Skip if a print is in flight (or pending): it will keep the
            # printer busy on its own, and interleaving protocol traffic
            # with a job could corrupt the stream.
            if self._print_lock.locked():
                continue

            try:
                async with self._print_lock:
                    if self._connected is None or self._released:
                        continue
                    await self._connected.feed()
                    await self._connected.retract()
                log.debug("Keep-alive feed/retract sent")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("Keep-alive failed (%s); dropping link to reconnect", exc)
                try:
                    await self._drop_connection()
                except Exception:  # noqa: BLE001
                    log.exception("Keep-alive reconnect teardown failed")

    async def _attempt_connect(self) -> bool:
        """Try to establish one persistent connection. Returns success."""
        async with self._conn_lock:
            if self._connected is not None:
                return True
            if self._released:
                self._state = DISABLED
                return False

            self._state = CONNECTING
            self._detail = "Searching for the printer..."
            try:
                if TIMINI_FAKE:
                    self._connected = FakeConnectedPrinter()
                    self._detail = ""
                else:
                    self._prepare_timini()
                    device = self._device
                    if device is None:
                        device = await self._resolve_device()
                    from timiniprint.printing.connected import connect_printer

                    connected = await connect_printer(
                        device,
                        self._make_connector(),
                        reporter=self._reporter,
                    )
                    self._device = device
                    self._connected = connected
                    dev = connected.printer_device()
                    log.info(
                        "Connected to %s (%s) [%s]",
                        getattr(dev, "display_name", "") or "?",
                        getattr(dev, "address", "") or "?",
                        getattr(dev, "profile_key", "") or "?",
                    )
                    self._detail = ""

                self._state = CONNECTED
                self._backoff = BACKOFF_START_SECONDS
                return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._state = RECONNECTING
                self._detail = str(exc) or exc.__class__.__name__
                log.warning("Connect failed: %s", self._detail)
                return False
    def _prepare_timini(self) -> None:
        """Make TiMini-Print importable and build the reporter, once."""
        if TIMINI_SOURCE and os.path.isdir(TIMINI_SOURCE):
            if TIMINI_SOURCE not in sys.path:
                sys.path.insert(0, TIMINI_SOURCE)
        if self._reporter is None:
            from timiniprint import reporting

            self._reporter = reporting.Reporter([_LogSink()])

    async def _resolve_device(self):
        """Resolve the printer the same way the TiMini CLI does.

        Honors PRINTER_MODEL / PRINTER_BLUETOOTH (mirroring the add-on's old
        ``--printer-model`` / ``--bluetooth`` flags): with a model key the
        transport target still comes from a scan (so the connector knows the
        address), otherwise the discovery scan picks the first supported
        printer (or the one matching ``printer_bluetooth`` by name/MAC).
        """
        from timiniprint.devices import PrinterCatalog
        from timiniprint.transport.bluetooth import BluetoothDiscovery

        catalog = PrinterCatalog.load()
        discovery = BluetoothDiscovery(catalog, reporter=self._reporter)
        printer_model = os.environ.get("PRINTER_MODEL", "").strip()
        printer_bluetooth = os.environ.get("PRINTER_BLUETOOTH", "").strip()

        if printer_model:
            detected = await discovery.resolve_transport_target(printer_bluetooth or None)
            return catalog.device_from_model(
                printer_model,
                display_name=detected.display_name,
                transport_target=detected.transport_target,
            )
        return await discovery.resolve_device(printer_bluetooth or None)

    def _make_connector(self):
        from timiniprint.transport.bluetooth import BleakBluetoothConnector

        return BleakBluetoothConnector(reporter=self._reporter)
    # ------------------------------------------------------------------
    # Print jobs (called from Flask via _submit)
    # ------------------------------------------------------------------

    async def _print_text_async(self, text, *, darkness, text_columns) -> str:
        if self._released:
            raise PrinterReleasedError(_RELEASED_DETAIL)
        async with self._print_lock:
            connected = await self._ensure_connected_wait()
            settings = None if TIMINI_FAKE else self._build_settings(
                darkness=darkness, text_columns=text_columns
            )
            try:
                await connected.print_text(
                    text, settings=settings, timeout=PRINT_OP_TIMEOUT_SECONDS
                )
            except asyncio.CancelledError:
                raise
            except Exception as first_exc:  # noqa: BLE001
                if not self._should_retry(first_exc):
                    raise
                await self._retry_after_reconnect(
                    connected, text, settings, kind="text"
                )
            return "Printed."

    async def _print_file_async(self, path, *, darkness) -> str:
        if self._released:
            raise PrinterReleasedError(_RELEASED_DETAIL)
        async with self._print_lock:
            connected = await self._ensure_connected_wait()
            settings = None if TIMINI_FAKE else self._build_settings(
                darkness=darkness, text_columns=None
            )
            try:
                await connected.print_file(
                    path, settings=settings, timeout=PRINT_OP_TIMEOUT_SECONDS
                )
            except asyncio.CancelledError:
                raise
            except Exception as first_exc:  # noqa: BLE001
                if not self._should_retry(first_exc):
                    raise
                await self._retry_after_reconnect(
                    connected, path, settings, kind="file"
                )
            return "Printed."

    async def _retry_after_reconnect(self, old_connected, payload, settings, *, kind):
        """After a connection-level failure, drop, reconnect, and retry once."""
        log.warning("Print failed, reconnecting and retrying once...")
        await self._drop_connection()
        connected = await self._ensure_connected_wait()
        if kind == "text":
            await connected.print_text(
                payload, settings=settings, timeout=PRINT_OP_TIMEOUT_SECONDS
            )
        else:
            await connected.print_file(
                payload, settings=settings, timeout=PRINT_OP_TIMEOUT_SECONDS
            )

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """Retry after any exception except clear input/content errors."""
        return not isinstance(
            exc,
            (ValueError, TypeError, FileNotFoundError, IsADirectoryError, PermissionError),
        )

    def _build_settings(self, *, darkness, text_columns):
        from timiniprint.printing.settings import PrintSettings

        settings = PrintSettings(
            text_mode=None,
            text_font=TEXT_FONT if os.path.exists(TEXT_FONT) else None,
            text_columns=text_columns,
            text_wrap=True,
            trim_side_margins=True,
            trim_top_bottom_margins=True,
            pdf_pages=None,
            page_gap_mm=5,
            paper_preset_key=None,
            image_encoding_override=None,
            debug_row_markers_interval=None,
        )
        if darkness is not None:
            settings.blackening = darkness
        return settings
    # ------------------------------------------------------------------
    # Connection promise + teardown
    # ------------------------------------------------------------------

    async def _ensure_connected_wait(
        self, wait_seconds: float = ENSURE_CONNECTED_WAIT_SECONDS
    ):
        """Return the current connection, waiting for one if it is establishing.

        Nudges the maintainer with ``wake`` so a backoff sleep is interrupted
        (reconnect-on-demand). Raises ``PrinterReleasedError`` when handed off
        and ``PrinterUnavailableError`` when the printer can't be reached in
        time (typically: it's powered off and needs the power button).
        """
        if self._connected is not None:
            return self._connected
        if self._released:
            raise PrinterReleasedError(_RELEASED_DETAIL)

        self._wake.set()
        deadline = self._loop.time() + wait_seconds
        while self._connected is None and not self._released:
            if self._loop.time() >= deadline:
                break
            await asyncio.sleep(0.25)

        if self._connected is not None:
            return self._connected
        if self._released:
            raise PrinterReleasedError(_RELEASED_DETAIL)
        detail = self._detail or "no supported printer found"
        if "No supported printers found" in detail or "No device matches" in detail:
            detail = (
                f"{detail}. If the printer is powered off, press its power "
                "button and the bridge will reconnect automatically."
            )
        raise PrinterUnavailableError(detail)

    async def _drop_connection(self) -> None:
        """Tear down the current connection (if any) and clear the reference."""
        async with self._conn_lock:
            connected = self._connected
            self._connected = None
            if connected is not None:
                try:
                    await connected.disconnect()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.debug("Disconnect cleanup failed: %s", exc)
            self._wake.set()

    async def _set_released_async(self, released: bool) -> None:
        released = bool(released)
        if released == self._released:
            return
        self._released = released
        self._save_state()
        if released:
            await self._drop_connection()
            self._state = DISABLED
            self._detail = _RELEASED_DETAIL
            log.info("Printer handed off to phone app")
        else:
            self._detail = ""
            log.info("Reclaiming printer")
            self._wake.set()
    async def _status_async(self) -> dict:
        device = None
        if self._connected is not None:
            try:
                device = self._connected.printer_device()
            except Exception:  # noqa: BLE001
                device = None
        if device is None:
            device = self._device

        released = self._released
        if released:
            state = DISABLED
        elif self._connected is not None:
            state = CONNECTED
        else:
            state = self._state

        return {
            "state": state,
            "released": released,
            "model": (getattr(device, "display_name", "") or "") if device else "",
            "address": (getattr(device, "address", "") or "") if device else "",
            "detail": self._detail or "",
            "fake": TIMINI_FAKE,
        }

    # ------------------------------------------------------------------
    # Synchronous API used by Flask (submits to the loop thread)
    # ------------------------------------------------------------------

    def print_text(self, text: str, *, darkness=None, text_columns=None) -> str:
        return self._submit(
            self._print_text_async(text, darkness=darkness, text_columns=text_columns),
            timeout=PRINT_WAIT_SECONDS,
        )

    def print_file(self, path: str, *, darkness=None) -> str:
        return self._submit(
            self._print_file_async(path, darkness=darkness),
            timeout=PRINT_WAIT_SECONDS,
        )

    def status(self) -> dict:
        return self._submit(self._status_async(), timeout=10)

    def set_released(self, released: bool) -> None:
        self._submit(self._set_released_async(released), timeout=15)

    def _submit(self, coro, *, timeout: float):
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError as exc:  # loop is closed
            raise PrinterUnavailableError(
                f"Printer connection loop is not running: {exc}"
            ) from exc
        try:
            return future.result(timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise PrinterUnavailableError(
                "Timed out waiting for the printer loop (the operation may still be running)."
            ) from exc
    # ------------------------------------------------------------------
    # State persistence + shutdown
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._released = bool(data.get("released", False))
        except FileNotFoundError:
            self._released = False
        except (ValueError, OSError) as exc:
            log.warning("Could not read printer control state %s: %s", self._path, exc)
            self._released = False

    def _save_state(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"released": self._released}, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("Could not save printer control state %s: %s", self._path, exc)

    def close(self) -> None:
        """Stop the connection loop and release the printer."""
        if self._loop.is_closed():
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
            future.result(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    async def _shutdown(self) -> None:
        self._closed = True
        if self._wake is not None:
            self._wake.set()
        if self._maintain_task is not None:
            self._maintain_task.cancel()
            try:
                await self._maintain_task
            except Exception:  # noqa: BLE001 - CancelledError included on 3.8
                pass
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except Exception:  # noqa: BLE001 - CancelledError included on 3.8
                pass
        if self._connected is not None:
            await self._drop_connection()
