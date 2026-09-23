"""Minimal Wayland client for ext-idle-notify-v1.

It tells when the user stops using keyboard and mouse on any compositor that implements
the protocol (KWin, sway, Hyprland…); KDE's D-Bus GetSessionIdleTime does not work on
Wayland. Only the handful of requests and events needed are implemented.
"""

import asyncio
import contextlib
import logging
import os
import struct
import time
from collections.abc import Callable, Mapping
from pathlib import Path

log = logging.getLogger(__name__)

GRANULARITY = 5.0  # seconds of inactivity before the compositor reports "idled"
HANDSHAKE_LIMIT = 5.0

# Object ids we allocate (the display is always 1).
_DISPLAY, _REGISTRY, _SYNC, _SEAT, _NOTIFIER, _NOTIFICATION = 1, 2, 3, 4, 5, 6
_NOTIFIER_INTERFACE = "ext_idle_notifier_v1"


class WaylandError(Exception):
    pass


def find_socket(env: Mapping[str, str]) -> Path | None:
    """The compositor's socket: $WAYLAND_DISPLAY, or the first wayland-* in the runtime dir
    (a systemd user service often lacks WAYLAND_DISPLAY)."""
    runtime = Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    display = env.get("WAYLAND_DISPLAY")
    if display:
        path = Path(display) if display.startswith("/") else runtime / display
        return path if path.exists() else None
    sockets = sorted(p for p in runtime.glob("wayland-*") if not p.name.endswith(".lock"))
    return sockets[0] if sockets else None


def message(object_id: int, opcode: int, payload: bytes = b"") -> bytes:
    return struct.pack("=II", object_id, ((8 + len(payload)) << 16) | opcode) + payload


def string(text: str) -> bytes:
    data = text.encode() + b"\0"
    return struct.pack("=I", len(data)) + data + b"\0" * (-len(data) % 4)


def read_string(body: bytes, offset: int) -> tuple[str, int]:
    (length,) = struct.unpack_from("=I", body, offset)
    start = offset + 4
    text = body[start : start + length - 1].decode(errors="replace")
    return text, start + length + (-length % 4)


class IdleMonitor:
    def __init__(
        self,
        socket: Path,
        granularity: float = GRANULARITY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.socket = socket
        self._granularity = granularity
        self._clock = clock
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._listener: asyncio.Task[None] | None = None
        self._idle_since: float | None = None
        self.input_only = False  # v2: ignores idle inhibitors such as video players

    @property
    def running(self) -> bool:
        return self._listener is not None and not self._listener.done()

    def idle_seconds(self) -> float:
        return 0.0 if self._idle_since is None else max(0.0, self._clock() - self._idle_since)

    async def start(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(str(self.socket))
        try:
            async with asyncio.timeout(HANDSHAKE_LIMIT):
                globals_ = await self._globals()
            if _NOTIFIER_INTERFACE not in globals_ or "wl_seat" not in globals_:
                raise WaylandError(f"the compositor does not offer {_NOTIFIER_INTERFACE}")
            seat_name, _ = globals_["wl_seat"]
            notifier_name, version = globals_[_NOTIFIER_INTERFACE]
            version = min(version, 2)
            self.input_only = version >= 2
            timeout_ms = round(self._granularity * 1000)
            self._send(_bind(seat_name, "wl_seat", 1, _SEAT))
            self._send(_bind(notifier_name, _NOTIFIER_INTERFACE, version, _NOTIFIER))
            # get_input_idle_notification (v2) or get_idle_notification (v1)
            opcode = 2 if self.input_only else 1
            self._send(
                message(_NOTIFIER, opcode, struct.pack("=III", _NOTIFICATION, timeout_ms, _SEAT))
            )
            await self._writer.drain()
        except BaseException:
            await self.close()
            raise
        self._listener = asyncio.create_task(self._listen(), name="kse-wayland-idle")

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()
            self._writer = None
        self._idle_since = None

    async def _globals(self) -> dict[str, tuple[int, int]]:
        self._send(message(_DISPLAY, 1, struct.pack("=I", _REGISTRY)))  # get_registry
        self._send(message(_DISPLAY, 0, struct.pack("=I", _SYNC)))  # sync
        assert self._writer is not None
        await self._writer.drain()
        found: dict[str, tuple[int, int]] = {}
        while True:
            object_id, opcode, body = await self._receive()
            if object_id == _REGISTRY and opcode == 0:  # global(name, interface, version)
                (name,) = struct.unpack_from("=I", body)
                interface, offset = read_string(body, 4)
                (version,) = struct.unpack_from("=I", body, offset)
                found[interface] = (name, version)
            elif object_id == _SYNC:  # callback.done: every global has been announced
                return found
            elif object_id == _DISPLAY and opcode == 0:
                raise WaylandError(_display_error(body))

    async def _listen(self) -> None:
        try:
            while True:
                object_id, opcode, body = await self._receive()
                if object_id == _NOTIFICATION and opcode == 0:  # idled
                    self._idle_since = self._clock() - self._granularity
                elif object_id == _NOTIFICATION and opcode == 1:  # resumed
                    self._idle_since = None
                elif object_id == _DISPLAY and opcode == 0:
                    log.warning("wayland: %s", _display_error(body))
                    return
        except (asyncio.IncompleteReadError, OSError):
            log.info("wayland: the compositor closed the connection")
        finally:
            self._idle_since = None

    async def _receive(self) -> tuple[int, int, bytes]:
        assert self._reader is not None
        object_id, word = struct.unpack("=II", await self._reader.readexactly(8))
        size = word >> 16
        if size < 8:
            raise WaylandError(f"malformed message of {size} bytes")
        return object_id, word & 0xFFFF, await self._reader.readexactly(size - 8)

    def _send(self, data: bytes) -> None:
        assert self._writer is not None
        self._writer.write(data)


def _bind(name: int, interface: str, version: int, new_id: int) -> bytes:
    payload = struct.pack("=I", name) + string(interface) + struct.pack("=II", version, new_id)
    return message(_REGISTRY, 0, payload)


def _display_error(body: bytes) -> str:
    object_id, code = struct.unpack_from("=II", body)
    text, _ = read_string(body, 8)
    return f"protocol error {code} on object {object_id}: {text}"
